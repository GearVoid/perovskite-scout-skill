"""deliver.py — 钙钛矿情报雷达 投递闭环 (MVP+ 最后一公里).

把「跑管线 → 校验 → 组装投递包 → 推送到出口」串成一条命令，
让 openclaw 定时任务能直接调用，无需人工干预。

用法:
  python scripts/deliver.py                      # 生产: 正常去重, 只推本周期新增
  python scripts/deliver.py --mode preview       # 预览: --ignore-state, 看完整本轮内容
  python scripts/deliver.py --transport webhook  # 推送到一个 HTTP 出口(需 $DELIVERY_WEBHOOK)

两种运行模式 (对齐 run_pipeline 的去重语义):
  production  默认。run_pipeline 不带 --ignore-state, 已见过的 arXiv id / 行业条目
              不再重复推送, 只发本周期新增。适合长期每周定时跑。
  preview     等价于 run_pipeline --ignore-state。每次生成完整本轮内容 (忽略 state),
              适合你现在看效果 / 调试。注意: preview 会重复发历史内容, 不要接生产出口。

出口 (transport):
  local    默认。校验全绿后, 把投递包写到 output/delivery/ :
              message.txt         微信文本正文 (digest 内容 + 头部一行)
              message-compact.txt 微信短版 (标题 + 可点击原始链接)
              card.png            图片卡片副本 (直接可发)
              delivery-manifest.json  元数据 (模式/时间/各 feed 条数/文件路径)
            openclaw 优先发送 compact + card；旧消费者继续读 message.txt 也可用。
  webhook  可选。保留 {text, image_path, manifest}，并新增 compact_text 与扁平
            契约字段。用于已有 HTTP 推送端点 (openclaw / 自建 bot) 的情况。

安全红线:
  - 校验 (validate_outputs) 不全绿, 清理旧 payload 并写 failed，绝不投递。
  - 无新增内容 (production 模式下 papers+industry 都为 0 新增) 时, 跳过投递并提示,
    不会发一条空消息刷屏。

退出码: 0=已投递(或确认无新内容跳过); 1=管线/校验失败未投递。
"""

import argparse
import json
import os
import shutil
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
BASE = Path(__file__).resolve().parent.parent
OUTPUT = BASE / "output"
DELIVERY_DIR = OUTPUT / "delivery"

import run_pipeline  # noqa: E402
import validate_outputs  # noqa: E402

# 复用 feed 路径常量
FEED_PAPERS = BASE / "feed-papers.json"
FEED_INDUSTRY = BASE / "feed-industry.json"
STATE_PAPERS = BASE / "state-feed.json"
STATE_INDUSTRY = BASE / "state-industry.json"
DIGEST = OUTPUT / "perovskite-scout-digest.txt"
COMPACT_DIGEST = OUTPUT / "perovskite-scout-digest-compact.txt"
CARD_PNG = OUTPUT / "perovskite-scout-card.png"
DELIVERY_PAYLOADS = ("message.txt", "message-compact.txt", "card.png")
STATE_PATHS = (STATE_PAPERS, STATE_INDUSTRY)


def new_count(state_path: Path) -> int:
    """估算本周期新增条数 = 当前 feed 总条数 (state 文件不一定含增量标记, 用全量近似)。

    说明: 去重后的 feed 就是「当前已发现全部」。真正「本周期新增」需要 diff state,
    但 MVP 阶段我们用更稳妥的策略: 若 feed 非空就投递 (preview 永远投递; production
    由 run_pipeline 的去重保证只含新增)。这里返回 feed 条数仅用于 manifest 展示。
    """
    if not state_path.exists():
        return 0
    return 0  # 详见 run_pipeline 去重; 实际是否投递由下方 has_content 决定


def feed_len(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
        return len(items) if isinstance(items, list) else 0
    except Exception:  # noqa: BLE001
        return 0


def has_new_content(mode: str) -> bool:
    """是否值得投递: 至少 feed 之一有内容。

    preview 模式: 有内容就投。
    production 模式: 同样有内容就投 —— run_pipeline 已保证只含去重后的结果;
                    若某周 arXiv/行业都无新命中, feed 为空, 自然跳过。
    """
    return feed_len(FEED_PAPERS) > 0 or feed_len(FEED_INDUSTRY) > 0


def build_message(
    mode: str,
    digest_path: Path = DIGEST,
    compact: bool = False,
) -> str:
    """组装微信文本正文；digest_path 可指向兼容长版或微信短版。"""
    if not digest_path.exists():
        return ""
    body = digest_path.read_text(encoding="utf-8")
    if compact:
        # compact 本身已有日期/计数头，只保留醒目的预览标记，避免技术头重复。
        return ("【预览模式】\n" if mode == "preview" else "") + body
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = (
        f"# 钙钛矿情报雷达 · {stamp}\n"
        f"# 模式: {mode}\n"
        f"# 论文 {feed_len(FEED_PAPERS)} 条 · 产业 {feed_len(FEED_INDUSTRY)} 条\n"
        f"{'-' * 24}\n"
    )
    return header + body


def clear_delivery_payloads() -> None:
    """清除可发送正文，避免失败/安静周留下上一轮 ready 内容。"""
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    for name in DELIVERY_PAYLOADS:
        try:
            (DELIVERY_DIR / name).unlink()
        except OSError:
            pass
    # 兼容未来多卡片命名，也清理历史 card-part-*.png。
    for old in DELIVERY_DIR.glob("card*.png"):
        try:
            old.unlink()
        except OSError:
            pass


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """在同目录写临时文件，再原子替换目标。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def write_json_atomic(path: Path, payload: dict) -> None:
    write_bytes_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def snapshot_states() -> dict[Path, bytes | None]:
    """快照 production 去重 state；失败时必须恢复，避免吃掉未投递内容。"""
    return {path: path.read_bytes() if path.exists() else None for path in STATE_PATHS}


def restore_states(snapshot: dict[Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            write_bytes_atomic(path, data)


def write_status_manifest(status: str, mode: str, reason: str) -> Path:
    """原子写 non-ready 状态，并清理可发送正文。"""
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": status,
        "reason": reason,
        "papers_count": feed_len(FEED_PAPERS),
        "paper_count": feed_len(FEED_PAPERS),
        "industry_count": feed_len(FEED_INDUSTRY),
    }
    mpath = DELIVERY_DIR / "delivery-manifest.json"
    # 先原子切换到 non-ready，再尽力清 payload；消费者始终以 manifest 为准。
    write_json_atomic(mpath, manifest)
    clear_delivery_payloads()
    return mpath


def write_local(message: str, compact_message: str, mode: str) -> Path:
    """事务式组包：payload 全部就绪后，最后原子切换 manifest=ready。"""
    write_status_manifest("preparing", mode, "packaging_in_progress")
    if not CARD_PNG.exists():
        raise FileNotFoundError(f"微信投递缺 PNG 卡片: {CARD_PNG}")

    token = uuid.uuid4().hex
    staged = {
        "message.txt": DELIVERY_DIR / f".message.{token}.tmp",
        "message-compact.txt": DELIVERY_DIR / f".message-compact.{token}.tmp",
        "card.png": DELIVERY_DIR / f".card.{token}.tmp",
    }
    try:
        staged["message.txt"].write_text(message, encoding="utf-8")
        staged["message-compact.txt"].write_text(compact_message, encoding="utf-8")
        shutil.copy2(CARD_PNG, staged["card.png"])

        for name in DELIVERY_PAYLOADS:
            os.replace(staged[name], DELIVERY_DIR / name)
    except Exception:
        for temp in staged.values():
            try:
                temp.unlink()
            except OSError:
                pass
        clear_delivery_payloads()
        write_status_manifest("failed", mode, "packaging_failed")
        raise

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "ready",
        "papers_count": feed_len(FEED_PAPERS),
        "paper_count": feed_len(FEED_PAPERS),
        "industry_count": feed_len(FEED_INDUSTRY),
        "text_file": "message.txt",
        "compact_text_file": "message-compact.txt",
        "preferred_text_file": "message-compact.txt",
        "image_file": "card.png",
        "message_path": "output/delivery/message.txt",
        "compact_message_path": "output/delivery/message-compact.txt",
        "card_path": "output/delivery/card.png",
        "delivery_dir": str(DELIVERY_DIR),
    }
    mpath = DELIVERY_DIR / "delivery-manifest.json"
    # ready 是整个事务的最后一步；此前消费者只能看到 failed/preparing。
    write_json_atomic(mpath, manifest)
    return mpath


def send_webhook(message: str, compact_message: str, manifest: dict) -> bool:
    """transport=webhook: POST 到 $DELIVERY_WEBHOOK。返回是否成功。"""
    url = os.environ.get("DELIVERY_WEBHOOK")
    if not url:
        print("[SKIP] webhook 未配置 $DELIVERY_WEBHOOK, 退回 local 模式写入")
        return False
    payload = {
        "text": message,
        "compact_text": compact_message,
        "image_path": str(DELIVERY_DIR / "card.png")
        if (DELIVERY_DIR / "card.png").exists() else None,
        "manifest": manifest,
        # 扁平别名与文档契约对齐；保留上方旧字段以兼容已有接收端。
        "status": manifest.get("status"),
        "mode": manifest.get("mode"),
        "message_path": manifest.get("message_path"),
        "compact_message_path": manifest.get("compact_message_path"),
        "card_path": manifest.get("card_path"),
        "paper_count": manifest.get("paper_count"),
        "industry_count": manifest.get("industry_count"),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"[OK] webhook POST -> {resp.status}")
            return True
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] webhook POST 失败: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="钙钛矿情报雷达 投递闭环")
    ap.add_argument(
        "--mode",
        choices=["production", "preview"],
        default="production",
        help="production=正常去重只推新增(默认); preview=--ignore-state 看完整内容",
    )
    ap.add_argument(
        "--transport",
        choices=["local", "webhook"],
        default="local",
        help="local=写 output/delivery/(默认); webhook=POST 到 $DELIVERY_WEBHOOK",
    )
    args = ap.parse_args()

    print(f"\n=== deliver [{args.mode}] transport={args.transport} ===")

    state_snapshot: dict[Path, bytes | None] = {}
    if args.mode == "production":
        try:
            state_snapshot = snapshot_states()
        except OSError as exc:
            write_status_manifest("failed", args.mode, "state_snapshot_failed")
            print(f"[FAIL] 无法快照去重 state，未启动管线: {exc}")
            return 1

    def rollback_state() -> None:
        if not state_snapshot:
            return
        try:
            restore_states(state_snapshot)
        except OSError as exc:
            print(f"[FAIL] 去重 state 回滚失败，请人工检查: {exc}")

    # 1) 跑管线
    pipeline_args = ["--ignore-state"] if args.mode == "preview" else []
    saved = sys.argv
    try:
        sys.argv = ["run_pipeline.py"] + pipeline_args
        rc = run_pipeline.main()
    except Exception as exc:  # noqa: BLE001
        rollback_state()
        write_status_manifest("failed", args.mode, "pipeline_exception")
        print(f"[FAIL] 管线异常, 终止投递: {exc}")
        return 1
    finally:
        sys.argv = saved
    if rc != 0:
        rollback_state()
        write_status_manifest("failed", args.mode, "pipeline_failed")
        print("[FAIL] 管线失败, 终止投递")
        return 1

    # 2) 校验 (全绿才投)
    #    定时投递模式下允许 feed 为空 (安静周不报错), 但其它检查 (字段/乱码/tier/
    #    跨 feed 去重/卡片/邮箱) 仍严格。这等同于手动跑 validate_outputs 时设
    #    ALLOW_EMPTY_FEED=1。开发/CI 直接跑 validate 仍保持非空硬要求。
    previous_allow_empty = os.environ.get("ALLOW_EMPTY_FEED")
    os.environ["ALLOW_EMPTY_FEED"] = "1"
    saved = sys.argv
    try:
        sys.argv = ["validate_outputs.py"]
        vrc = validate_outputs.main()
    except Exception as exc:  # noqa: BLE001
        rollback_state()
        write_status_manifest("failed", args.mode, "validation_exception")
        print(f"[FAIL] 校验异常, 终止投递: {exc}")
        return 1
    finally:
        sys.argv = saved
        if previous_allow_empty is None:
            os.environ.pop("ALLOW_EMPTY_FEED", None)
        else:
            os.environ["ALLOW_EMPTY_FEED"] = previous_allow_empty
    if vrc != 0:
        rollback_state()
        write_status_manifest("failed", args.mode, "validation_failed")
        print("[FAIL] 校验未全绿, 终止投递 (不把坏数据推到微信)")
        return 1

    # 3) 是否值得投 (安静周: 两 feed 都为空 -> 跳过, 不刷屏)
    if not has_new_content(args.mode):
        print("[OK] 本轮无新内容 (论文0 产业0), 跳过投递 (不刷屏)")
        write_status_manifest("skipped", args.mode, "no_new_content")
        return 0

    # standalone validate 可接受 HTML 预览回退；个人微信 ready 契约必须有 PNG。
    if not CARD_PNG.exists():
        rollback_state()
        write_status_manifest("failed", args.mode, "card_png_missing")
        print("[FAIL] 有可投内容但缺少 card.png；请安装 Pillow 后重跑")
        return 1

    # 4) 组装投递包
    message = build_message(args.mode)
    compact_message = build_message(args.mode, COMPACT_DIGEST, compact=True)
    try:
        mpath = write_local(message, compact_message, args.mode)
    except Exception as exc:  # noqa: BLE001
        rollback_state()
        try:
            write_status_manifest("failed", args.mode, "packaging_failed")
        except OSError:
            pass
        print(f"[FAIL] 投递包组装失败，未切换 ready: {exc}")
        return 1
    print(f"[OK] 本地投递包已生成: {DELIVERY_DIR}")
    print(f"     - message.txt ({len(message)} 字)")
    print(f"     - message-compact.txt ({len(compact_message)} 字，微信优先)")
    if (DELIVERY_DIR / 'card.png').exists():
        print(f"     - card.png")

    # 5) 推送出口
    if args.transport == "webhook":
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        ok = send_webhook(message, compact_message, manifest)
        if not ok:
            # 已经写好了 local 包, 这里只提示
            print("[NOTE] 已退回 local 包, openclaw 可读 output/delivery/ 推送")
    else:
        print("[NOTE] transport=local: openclaw 优先发送 message-compact.txt + card.png；长版保留为 message.txt")

    print("\n[OK] 投递闭环完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
