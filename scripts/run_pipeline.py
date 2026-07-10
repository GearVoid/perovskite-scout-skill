"""run_pipeline.py — MVP 一键管线: discover + text + image。

用法:
  python scripts/run_pipeline.py [--rebuild] [--ignore-state]

说明:
  - 依次执行 discover_papers -> enrich_metadata -> text_renderer -> image_renderer
  - renderer 各自在写入前清理旧的 digest/card 分页产物, 避免投递错文件
  - image_renderer 需 Pillow 出 PNG; 缺 Pillow 时退回 HTML (不卡住)
  - 全链路不调用 LLM
"""

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import discover_papers  # noqa: E402
import enrich_metadata  # noqa: E402
import text_renderer   # noqa: E402
import image_renderer  # noqa: E402


def run_step(label: str, module, child_args: list) -> bool:
    print(f"\n=== {label} ===")
    saved = sys.argv
    sys.argv = [f"{module.__name__}.py"] + list(child_args)
    try:
        rc = module.main()
    finally:
        sys.argv = saved
    if rc not in (None, 0):
        print(f"[FAIL] {label} exited {rc}")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="perovskite-scout MVP pipeline")
    ap.add_argument("--rebuild", action="store_true", help="清空 state 重新生成")
    ap.add_argument("--ignore-state", action="store_true", help="忽略去重")
    args = ap.parse_args()

    discover_args = []
    if args.rebuild:
        discover_args.append("--rebuild")
    if args.ignore_state:
        discover_args.append("--ignore-state")

    ok = True
    ok &= run_step("1/4 discover_papers (arXiv + 过滤 + 去重)", discover_papers, discover_args)
    ok &= run_step("2/4 enrich_metadata (Crossref/OpenAlex 补字段)", enrich_metadata, [])
    ok &= run_step("3/4 text_renderer (digest.txt)", text_renderer, [])
    ok &= run_step("4/4 image_renderer (card.png/html)", image_renderer, [])

    print("\n" + ("[OK] 管线完成" if ok else "[FAIL] 管线存在失败步骤"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
