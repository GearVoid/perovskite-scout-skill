"""enrich_metadata.py — 阶段1.5: 用 Crossref / OpenAlex 补全论文元数据字段。

约束 (来自 playbook / spec):
  - arXiv 是唯一发现源; 本脚本只补字段, 不决定 keep / reject / tier / rank
  - 无 API key
  - 速率限制 / 失败不得中断主流程; enrich 失败不能影响原 feed
  - tier 仍只由 tier_mapper 判定; relevance 仍只由 relevance_filter 判定

新增字段 (每条 item):
  - doi: str | None
  - openalex_id: str | None
  - institutions: list[str]            # 去重后的机构名
  - corresponding_source: "openalex" | "crossref" | None
  - enrich_errors: list[str]           # 失败/未索引原因, 便于审计

策略:
  OpenAlex 优先, 用 arXiv 预印本 DOI (10.48550/arxiv.{id}) 走 `filter=doi:` 精确命中
    -> 给 institutions + openalex_id + doi (journal doi 或 arxiv doi)
  未命中则 Crossref 回退 (按 arXiv DOI 查, 仅补 DOI)

注意: OpenAlex 没有 `arxiv` / `arxiv_id` 这种 filter 字段, 必须用 DOI 路径。
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FEED = BASE / "feed-papers.json"
ENRICH_CONFIG = BASE / "config" / "enrich.json"

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
SLEEP = 0.2  # 礼貌性限速: 请求间最小间隔(秒)
TIMEOUT = 20


def load_openalex_mailto() -> str:
    """读取 OpenAlex 联系邮箱, 优先级: 环境变量 > config/enrich.json > 默认占位。

    OpenAlex 鼓励带 mailto 以进入"礼貌池"(更高限速)。
    """
    env = os.environ.get("OPENALEX_MAILTO")
    if env:
        return env
    try:
        if ENRICH_CONFIG.exists():
            cfg = json.load(open(ENRICH_CONFIG, encoding="utf-8")) or {}
            v = cfg.get("openalex_mailto")
            if v:
                return v
    except Exception:  # noqa: BLE001
        pass
    return "perovskite-scout@example.com"


OPENALEX_MAILTO = load_openalex_mailto()
USER_AGENT = f"perovskite-scout/0.1 (mailto:{OPENALEX_MAILTO})"


def _fetch_json(url):
    """GET JSON; 返回 (data, error_str). 任何异常都记录 error 而不抛出。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None, f"http {resp.status}"
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def extract_arxiv_id(item: dict) -> str | None:
    """从 id / url 提取 arXiv 短 id (去版本号), 如 2606.12345。"""
    text = " ".join(str(item.get(k, "")) for k in ("id", "url"))
    m = re.search(r"(\d{4}\.\d{4,5})", text)
    return m.group(1) if m else None


def _dedupe(names: list) -> list:
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def query_openalex(arxiv_id: str, errors: list) -> dict | None:
    # arXiv 预印本在 OpenAlex 的 DOI 为 10.48550/arxiv.{id} (小写)
    arxiv_doi = f"https://doi.org/10.48550/arxiv.{arxiv_id}"
    url = f"{OPENALEX_URL}?filter=doi:{arxiv_doi}&mailto={OPENALEX_MAILTO}&per-page=1"
    data, err = _fetch_json(url)
    if err:
        errors.append(f"openalex: {err}")
        return None
    if not data or not data.get("results"):
        errors.append("openalex: no record (not indexed)")
        return None
    w = data["results"][0]
    insts = []
    for a in w.get("authorships", []):
        for inst in a.get("institutions", []):
            nm = inst.get("display_name")
            if nm:
                insts.append(nm)
    return {
        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
        "openalex_id": (w.get("ids", {}) or {}).get("openalex"),
        "institutions": _dedupe(insts),
    }


def query_crossref(arxiv_id: str, errors: list) -> dict | None:
    # Crossref 按 arXiv DOI 查 (大小写都试)
    for doi in (f"10.48550/arXiv.{arxiv_id}", f"10.48550/arxiv.{arxiv_id}"):
        data, err = _fetch_json(f"{CROSSREF_URL}/{doi}")
        if err:
            errors.append(f"crossref({doi}): {err}")
            continue
        it = data.get("message", {})
        if it.get("DOI"):
            return {"doi": it.get("DOI"), "openalex_id": None, "institutions": []}
    return None


def enrich_item(item: dict) -> dict:
    """返回 item 副本并附加 enrich 字段; 任何失败均降级为 null, 不影响原字段。"""
    out = dict(item)
    out["doi"] = None
    out["openalex_id"] = None
    out["institutions"] = []
    out["corresponding_source"] = None
    out["enrich_errors"] = []

    arxiv_id = extract_arxiv_id(item)
    if not arxiv_id:
        out["enrich_errors"].append("no arxiv id found")
        return out

    # 1) OpenAlex 优先 (机构 + openalex_id + doi)
    oa = query_openalex(arxiv_id, out["enrich_errors"])
    if oa:
        out["doi"] = oa["doi"]
        out["openalex_id"] = oa["openalex_id"]
        out["institutions"] = oa["institutions"]
        out["corresponding_source"] = "openalex"
        return out

    # 2) Crossref 回退 (仅补 DOI)
    cr = query_crossref(arxiv_id, out["enrich_errors"])
    if cr:
        out["doi"] = cr["doi"]
        out["corresponding_source"] = "crossref"
    return out


def main() -> int:
    if not FEED.exists():
        print("[FAIL] feed-papers.json 不存在, 请先运行 discover_papers")
        return 1
    feed = json.load(open(FEED, encoding="utf-8"))
    items = feed.get("items", [])
    enriched = []
    for it in items:
        enriched.append(enrich_item(it))
        time.sleep(SLEEP)  # 礼貌限速, 防触发远端限流
    feed["items"] = enriched
    feed["enriched"] = True
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    got = sum(1 for e in enriched if e["corresponding_source"])
    nulls = [e for e in enriched if not e["corresponding_source"]]
    print(f"[OK] enrich 完成: {got}/{len(enriched)} 条获得来源, {len(nulls)} 条为 null")
    return 0


if __name__ == "__main__":
    sys.exit(main())
