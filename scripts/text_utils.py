"""text_utils.py — 共享文本卫生工具 (hardening: 防乱码 / 防终端崩溃)。

- sanitize_text: 去除控制字符 / 零宽字符 / 软连字符 / 不间断空格, 归一空白,
  杜绝不可见乱码进入 feed / digest / 卡片图。
- safe_reconfigure_stdout: 在 Windows GBK 终端下把 stdout/stderr 重设为 UTF-8,
  避免打印含希腊字母 / 下标 / 特殊符号的 arXiv 摘要时抛 UnicodeEncodeError。
"""

import sys

# 需要剥离的"不可见 / 易致乱码"字符
_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"  # ZWSP / ZWNJ / ZWJ / WORD JOINER / BOM
_SOFT_HYPHEN = "\u00ad"
_NBSP = "\u00a0"


def sanitize_text(s: str | None) -> str:
    """清洗任意文本, 返回紧凑、无不可见字符的 UTF-8 字符串。

    - 丢弃 C0/C1 控制字符 (\n \t \r 也折叠为空格)
    - 丢弃零宽字符与软连字符 (它们会让微信/图片显示错位或空行)
    - 不间断空格 -> 普通空格
    - 多空白折叠为单空格, 去首尾
    """
    if not s:
        return ""
    out = []
    for ch in s:
        o = ord(ch)
        if o < 0x20 or (0x7F <= o <= 0x9F):
            # 控制字符整类丢弃 (含 \n \t \r)
            continue
        if ch in _ZERO_WIDTH or ch == _SOFT_HYPHEN:
            continue
        if ch == _NBSP:
            out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    return " ".join(text.split()).strip()


def safe_reconfigure_stdout() -> None:
    """尽量把 stdout/stderr 设为 UTF-8(errors=replace), 失败则静默。

    在 Windows 中文 GBK 控制台下, 打印含 α/β/₂/→/× 等符号的 arXiv 摘要
    会触发 UnicodeEncodeError 并使脚本崩溃; 重设编码可避免。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            reconf = getattr(stream, "reconfigure", None)
            if callable(reconf):
                reconf(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
