"""image_renderer.py — MVP 图片卡片 (Top 5)。

输入: feed-papers.json
输出: output/perovskite-scout-card.png (超长分页 card-part-N.png)
      环境无 Pillow 时退回 output/perovskite-scout-card.html (不卡住)

约束 (MVP 红线):
  - 不调用 LLM
  - 图片内不含完整链接: 仅标题/日期/tier/score/作者简写/短摘要
  - 链接仍由 text_renderer 的 digest.txt 补发
  - 排序逻辑复用 text_renderer: score>=TOP_MIN_SCORE 优先, 按 score/date 排, 封顶 TOP_N
"""

import json
import re
import sys
import time
from pathlib import Path

# 复用 text_renderer 的阈值, 保证 Top 5 与纯文本简报一致
sys.path.insert(0, str(Path(__file__).resolve().parent))
from text_renderer import TOP_N, TOP_MIN_SCORE  # noqa: E402
from text_utils import sanitize_text, safe_reconfigure_stdout  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_OK = True
except ImportError:
    PIL_OK = False

BASE = Path(__file__).resolve().parent.parent
FEED_PATH = BASE / "feed-papers.json"
OUTPUT_DIR = BASE / "output"

WIDTH = 1080
PADDING = 60
CONTENT_W = WIDTH - 2 * PADDING
MAX_PAGE_HEIGHT = 4000
HEADER_H = 170
FOOTER_H = 70

TIER_COLORS = {
    "T1": (26, 127, 55),
    "T2": (9, 105, 218),
    "T3": (154, 103, 0),
    "T4": (110, 119, 129),
}
COL_BG = (255, 255, 255)
COL_TEXT = (31, 35, 40)
COL_SUB = (101, 109, 118)
COL_LINE = (222, 226, 230)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
]


def load_font(size: int):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int) -> list:
    tokens = re.findall(r"[\u4e00-\u9fff]|[^\u4e00-\u9fff\s]+|\s+", text)
    lines, cur = [], ""
    for tok in tokens:
        test = cur + tok
        if font.getlength(test.replace("\n", "")) <= max_width:
            cur = test
        else:
            if cur.strip():
                lines.append(cur.rstrip())
            cur = tok if tok.strip() else ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def fmt_authors(authors: list) -> str:
    if not authors:
        return "未知"
    return authors[0] + " et al." if len(authors) > 1 else authors[0]


def short_summary(abstract: str) -> str:
    text = (abstract or "").replace("\n", " ").strip()
    return text[:120] + "…" if len(text) > 120 else text


def sort_top(items: list) -> list:
    items_sorted = sorted(
        items,
        key=lambda x: (x.get("relevance_score", 0), x.get("published_date", "")),
        reverse=True,
    )
    qualified = [it for it in items_sorted if (it.get("relevance_score") or 0) >= TOP_MIN_SCORE]
    capped = qualified[:TOP_N]
    top = list(capped)
    if len(top) < TOP_N:
        top_ids = {id(it) for it in capped}
        for it in items_sorted:
            if id(it) not in top_ids:
                top.append(it)
                if len(top) >= TOP_N:
                    break
    return top


# ---------- PIL 渲染路径 ----------

def measure_item(it: dict, fonts: tuple) -> int:
    title_font, meta_font, sum_font, _ = fonts
    h = 16
    tl = wrap_text(it.get("title", "(无标题)"), title_font, CONTENT_W - 90)
    h += len(tl) * (title_font.size + 8) + 10
    h += meta_font.size + 8
    sl = wrap_text(short_summary(it.get("abstract", "")), sum_font, CONTENT_W)
    h += len(sl) * (sum_font.size + 6) + 24
    return h


def draw_item(draw, it: dict, x: int, y: int, fonts: tuple) -> int:
    title_font, meta_font, sum_font, badge_font = fonts
    tier = str(it.get("provenance_tier", "T?"))[:2]
    color = TIER_COLORS.get(tier, COL_SUB)
    title = sanitize_text(it.get("title", "(无标题)"))

    bw, bh = 66, 42
    draw.rounded_rectangle([x, y, x + bw, y + bh], radius=8, fill=color)
    bt = tier
    draw.text(
        (x + (bw - badge_font.getlength(bt)) / 2, y + (bh - badge_font.size) / 2),
        bt,
        font=badge_font,
        fill=(255, 255, 255),
    )

    tl = wrap_text(title, title_font, CONTENT_W - 90)
    ty = y
    for line in tl:
        draw.text((x + bw + 16, ty), line, font=title_font, fill=COL_TEXT)
        ty += title_font.size + 8

    date = it.get("published_date", "")
    meta = f"{date}｜{fmt_authors(it.get('authors', []))}｜{it.get('relevance_score', '')}"
    draw.text((x, ty + 6), meta, font=meta_font, fill=COL_SUB)
    my = ty + 6 + meta_font.size + 8

    sl = wrap_text(short_summary(sanitize_text(it.get("abstract", ""))), sum_font, CONTENT_W)
    sy = my
    for line in sl:
        draw.text((x, sy), line, font=sum_font, fill=COL_SUB)
        sy += sum_font.size + 6

    sep_y = sy + 12
    draw.line([(x, sep_y), (x + CONTENT_W, sep_y)], fill=COL_LINE, width=2)
    return sep_y + 16


def render_pil(top: list, today: str) -> list:
    fonts = (load_font(34), load_font(28), load_font(26), load_font(24))
    header_font, sub_font = load_font(48), load_font(30)

    # 分页
    pages, cur, cur_h = [], [], HEADER_H + FOOTER_H
    for it in top:
        ih = measure_item(it, fonts)
        if cur and cur_h + ih > MAX_PAGE_HEIGHT:
            pages.append(cur)
            cur, cur_h = [], HEADER_H + FOOTER_H
        cur.append(it)
        cur_h += ih
    if cur:
        pages.append(cur)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for pi, pg in enumerate(pages, 1):
        h = HEADER_H + FOOTER_H + sum(measure_item(it, fonts) for it in pg) + 10
        img = Image.new("RGB", (WIDTH, h), COL_BG)
        d = ImageDraw.Draw(img)

        # header
        d.text((PADDING, 30), f"钙钛矿情报雷达 {today}", font=header_font, fill=COL_TEXT)
        d.text((PADDING, 92), f"本周重点 Top {len(top)} (评分≥{TOP_MIN_SCORE} 优先)", font=sub_font, fill=COL_SUB)
        d.line([(PADDING, HEADER_H - 14), (PADDING + CONTENT_W, HEADER_H - 14)], fill=COL_LINE, width=3)

        y = HEADER_H
        for it in pg:
            y = draw_item(d, it, PADDING, y, fonts)

        # footer
        foot = "完整链接见配套 digest.txt"
        if len(pages) > 1:
            foot += f"  ·  {pi}/{len(pages)}"
        d.text((PADDING, h - FOOTER_H + 20), foot, font=sub_font, fill=COL_SUB)

        out = OUTPUT_DIR / (
            f"perovskite-scout-card-part-{pi}.png" if len(pages) > 1 else "perovskite-scout-card.png"
        )
        img.save(out)
        files.append(out)
    return files


# ---------- HTML 退回路径 (无 Pillow) ----------

def render_html(top: list, today: str) -> list:
    cards = []
    for it in top:
        tier = str(it.get("provenance_tier", "T?"))[:2]
        color = "#%02x%02x%02x" % TIER_COLORS.get(tier, COL_SUB)
        cards.append(
            f'<div class="card">'
            f'<span class="badge" style="background:{color}">{tier}</span>'
            f'<div class="title">{it.get("title","(无标题)")}</div>'
            f'<div class="meta">{it.get("published_date","")}｜{fmt_authors(it.get("authors",[]))}｜{it.get("relevance_score","")}</div>'
            f'<div class="sum">{short_summary(it.get("abstract",""))}</div>'
            f"</div>"
        )
    html = (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>钙钛矿情报雷达 {today}</title><style>"
        "body{font-family:'Microsoft YaHei',sans-serif;background:#fff;margin:0;padding:24px;}"
        ".head{font-size:24px;font-weight:700;margin-bottom:4px;}"
        ".sub{color:#656d76;margin-bottom:16px;}"
        ".card{border:1px solid #dee2e6;border-radius:10px;padding:14px;margin-bottom:14px;}"
        ".badge{display:inline-block;color:#fff;border-radius:6px;padding:2px 8px;font-size:13px;font-weight:700;}"
        ".title{font-size:17px;font-weight:700;margin:8px 0 4px;}"
        ".meta{color:#656d76;font-size:13px;margin-bottom:6px;}"
        ".sum{color:#656d76;font-size:14px;line-height:1.5;}"
        ".foot{color:#656d76;font-size:13px;margin-top:8px;}"
        "</style></head><body>"
        f"<div class='head'>钙钛矿情报雷达 {today}</div>"
        f"<div class='sub'>本周重点 Top {len(top)} (评分≥{TOP_MIN_SCORE} 优先) · 完整链接见配套 digest.txt</div>"
        + "".join(cards)
        + "</body></html>"
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "perovskite-scout-card.html"
    out.write_text(html, encoding="utf-8")
    return [out]


def main() -> int:
    safe_reconfigure_stdout()  # Windows GBK 终端下避免打印中文/特殊符号时崩溃
    if not FEED_PATH.exists():
        print(f"ERROR: {FEED_PATH} 不存在, 请先运行 discover_papers.py", file=sys.stderr)
        return 1
    feed = json.load(open(FEED_PATH, encoding="utf-8"))
    top = sort_top(feed.get("items", []))
    today = time.strftime("%Y-%m-%d")

    # 清理旧卡片产物, 避免投递错文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for pat in (
        "perovskite-scout-card.png",
        "perovskite-scout-card-part-*.png",
        "perovskite-scout-card.html",
    ):
        for old in OUTPUT_DIR.glob(pat):
            try:
                old.unlink()
            except OSError:
                pass

    if not PIL_OK:
        files = render_html(top, today)
        print("Pillow 不可用, 已退回 HTML:")
        for f in files:
            print(f"  {f}")
        return 0

    files = render_pil(top, today)
    print(f"Pillow OK, 生成 {len(files)} 张卡片图:")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
