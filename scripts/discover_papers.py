"""discover_papers.py — arXiv 论文发现 + 相关性过滤 (MVP 只接 arXiv)。

流程:
  config/sources.json -> 调 arXiv API -> 解析 Atom -> relevance_filter 质量门
  -> tier_mapper 机器判级 -> state-feed.json 去重
  -> feed-papers.json (keep=true) + rejected-papers.json (审计)

约束（MVP 红线）:
  - 不下载 PDF，不做指标抽取
  - LLM 不参与（tier 由 tier_mapper.py 硬判定；相关性由 relevance_filter.py 规则判定）
  - 仅依赖标准库 + 同目录 tier_mapper / relevance_filter
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

# 允许从同目录 import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tier_mapper import tier_for_url  # noqa: E402
from relevance_filter import filter_item  # noqa: E402
from text_utils import sanitize_text, safe_reconfigure_stdout  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config" / "sources.json"
FEED_PATH = BASE / "feed-papers.json"
REJECTED_PATH = BASE / "rejected-papers.json"
STATE_PATH = BASE / "state-feed.json"

ATOM_NS = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "perovskite-scout/0.1 (MVP discovery; local run)"


def load_sources() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def fetch_arxiv(cfg: dict) -> str:
    params = {
        "search_query": cfg["search_query"],
        "start": cfg.get("start", 0),
        "max_results": cfg.get("max_results", 30),
        "sortBy": cfg.get("sortBy", "submittedDate"),
        "sortOrder": cfg.get("sortOrder", "descending"),
    }
    url = cfg["base_url"] + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):  # 429/503 指数退避重试 (arXiv 限流)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise last


def parse_entries(xml_text: str, doc_type: str) -> list:
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        raw_id = (entry.findtext(f"{ATOM_NS}id") or "").strip()
        # 在摄入时即清洗, 保证 feed 干净 (控制字符/零宽/不间断空格一律剔除)
        title = sanitize_text(entry.findtext(f"{ATOM_NS}title"))
        summary = sanitize_text(entry.findtext(f"{ATOM_NS}summary"))
        published = (entry.findtext(f"{ATOM_NS}published") or "").strip()
        published_date = published[:10] if published else ""

        authors = []
        for a in entry.findall(f"{ATOM_NS}author"):
            name = sanitize_text(a.findtext(f"{ATOM_NS}name"))
            if name:
                authors.append(name)

        aid = raw_id.rsplit("/", 1)[-1] if raw_id else ""
        aid_no_ver = aid.rsplit("v", 1)[0] if "v" in aid else aid
        url = f"https://arxiv.org/abs/{aid_no_ver}"
        source_domain = "arxiv.org"

        out.append(
            {
                "id": f"arxiv:{aid_no_ver}",
                "title": title,
                "url": url,
                "source_domain": source_domain,
                "provenance_tier": tier_for_url(url),
                "type": doc_type,
                "category": None,
                "published_date": published_date,
                "abstract": summary,
                "authors": authors,
                "raw_metrics": None,
            }
        )
    return out


def main() -> None:
    safe_reconfigure_stdout()  # Windows GBK 终端下避免打印中文/特殊符号时崩溃
    parser = argparse.ArgumentParser(description="perovskite-scout arXiv discovery")
    parser.add_argument(
        "--ignore-state",
        action="store_true",
        help="忽略 state-feed.json 去重，处理全部 fetch 条目（调过滤规则用）",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空 state 重新生成（等同删 state 后运行）",
    )
    args = parser.parse_args()

    if args.rebuild and STATE_PATH.exists():
        STATE_PATH.unlink()
        print("state-feed.json cleared (--rebuild)")

    sources = load_sources()
    arxiv_cfg = sources.get("arxiv")
    if not arxiv_cfg or not arxiv_cfg.get("enabled", True):
        print("arxiv source not enabled; nothing to do.")
        return

    doc_type = arxiv_cfg.get("type", "paper")
    print(f"Fetching arXiv: {arxiv_cfg['search_query']} (max {arxiv_cfg.get('max_results', 30)})")
    xml_text = fetch_arxiv(arxiv_cfg)
    entries = parse_entries(xml_text, doc_type)
    print(f"Fetched {len(entries)} entries from arXiv API.")

    # quality gate: 相关性过滤
    filtered = [filter_item(e) for e in entries]
    kept = [e for e in filtered if e["keep"]]
    rejected = [e for e in filtered if not e["keep"]]
    print(f"Relevance filter: kept={len(kept)} rejected={len(rejected)}")

    # 去重（基于 kept）
    use_state = not args.ignore_state
    state = load_state() if use_state else {}
    new_kept = [e for e in kept if e["id"] not in state]
    seen = len(kept) - len(new_kept)

    today = time.strftime("%Y-%m-%d")
    if use_state:
        for e in new_kept:
            state[e["id"]] = today

    feed = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "arxiv",
        "count": len(new_kept),
        "items": new_kept,
    }
    rejected_feed = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "arxiv",
        "count": len(rejected),
        "items": rejected,
    }

    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    REJECTED_PATH.write_text(
        json.dumps(rejected_feed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if use_state:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"New: {len(new_kept)} | Already seen: {seen} | "
        f"Feed -> {FEED_PATH} | Rejected -> {REJECTED_PATH}"
        + ("" if use_state else " | (state ignored)")
    )


if __name__ == "__main__":
    main()
