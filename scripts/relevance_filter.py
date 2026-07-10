"""relevance_filter.py — 相关性过滤 (discovery quality gate)。

输入 arXiv item dict，输出是否保留 + 相关性评分 + 原因。
纯规则，无 LLM（与 tier_mapper 一致，MVP 不引入 LLM 判定）。

目标：挡掉含 perovskite/solar 字样但非"钙钛矿光伏情报核心"的噪声，
如 photocatalysis / thermoelectric / planetary / geophysics / battery /
LED-only / sensor-only / DFT-theory-only / SCAPS-only / ML-only。

判定优先级：
  1) 无光伏核心信号 (CORE_PV) -> reject
  2) 有核心信号但命中硬排除 (EXCLUDE_HARD) 且无器件上下文 -> reject
  3) 否则 keep，软排除 (EXCLUDE_SOFT) 降权
"""

# 光伏核心信号：命中任一即认为主题是钙钛矿光伏（keep 的基础）
CORE_PV = [
    "perovskite solar cell",
    "perovskite solar",
    "perovskite photovoltaic",
    "photovoltaic",
    "solar cell",
    "power conversion efficiency",
    "pce",
    "tandem solar",
    "silicon tandem",
    "perovskite device",
    "perovskite film",
    "absorber layer",
    "hole transport",
    "electron transport",
    "perovskite absorber",
]

# 探测器类：与 solar cell 无关，无条件硬拒（即使含 device 等词也不保留）
DETECTOR_HARD = [
    "radiation detector",
    "charged particle",
    "particle detector",
    "radiation detection",
    "x-ray detector",
    "xray detector",
]

# 硬排除：非光伏主题；命中且无器件上下文 -> reject
EXCLUDE_HARD = [
    "photocatalysis",
    "photocatalytic",
    "thermoelectric",
    "planetary",
    "geophysics",
    "earth's interior",
    "mantle",
    "lithium battery",
    "battery",
]

# 软排除：降权，不必然 reject；仅当同时无光伏上下文才 reject
EXCLUDE_SOFT = [
    "light-emitting diode",
    "led",
    "sensor",
    "density functional theory",
    "dft",
    "first-principles",
    "theoretical",
    "scaps",
    "machine learning",
    "neural network",
    "deep learning",
    "simulation",
    # 非 solar-cell 物理光电流 / 多铁 / 铁电
    "multiferroic",
    "ferroelectric",
    "bulk photovoltaic effect",
    "bulk photovoltaicity",
    "photovoltage",
]

# 强器件信号：命中任一即认为是实质钙钛矿光伏器件工作
STRONG_PV = {
    "perovskite solar cell",
    "perovskite solar",
    "perovskite photovoltaic",
    "solar cell",
    "power conversion efficiency",
    "pce",
    "tandem solar",
    "silicon tandem",
    "perovskite device",
    "perovskite film",
    "absorber layer",
    "hole transport",
    "electron transport",
    "perovskite absorber",
    "device stack",
    "transport layer",
}

# 通用 PV 词：仅命中这些而无强器件信号 -> 降权（非实质 solar-cell 工作）
GENERIC_PV = {"photovoltaic", "photovoltage"}

# 器件/材料上下文：用于判断硬排除是否误伤光伏论文
DEVICE_CONTEXT = [
    "hole transport",
    "electron transport",
    "absorber",
    "device",
    "module",
    "interfacial",
    "passivation",
    "stability",
    "j-v",
    "open-circuit",
    "fill factor",
    "perovskite layer",
    "thin film",
    "pce",
    "power conversion",
]


def _text_of(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('abstract', '')}".lower()


def filter_item(item: dict) -> dict:
    """返回 item 的副本，附加 keep / relevance_score / relevance_reason / reject_reason。"""
    text = _text_of(item)
    core_hits = [w for w in CORE_PV if w in text]
    detector_hits = [w for w in DETECTOR_HARD if w in text]
    hard_hits = [w for w in EXCLUDE_HARD if w in text]
    soft_hits = [w for w in EXCLUDE_SOFT if w in text]
    device_hits = [w for w in DEVICE_CONTEXT if w in text]
    strong_hits = [w for w in STRONG_PV if w in text]

    result = dict(item)
    result["relevance_score"] = None
    result["relevance_reason"] = None
    result["reject_reason"] = None

    # 1) 无光伏核心信号 -> reject
    if not core_hits:
        result["keep"] = False
        result["reject_reason"] = (
            "no core PV signal (perovskite without solar-cell/photovoltaic context)"
        )
        return result

    # 2) 探测器类（radiation/charged particle detector）无条件硬拒
    if detector_hits:
        result["keep"] = False
        result["reject_reason"] = "off-topic: detector (" + ", ".join(detector_hits) + ")"
        return result

    # 3) 有核心但命中硬排除且无器件上下文 -> reject
    if hard_hits and not device_hits:
        result["keep"] = False
        result["reject_reason"] = "off-topic: " + ", ".join(hard_hits)
        return result

    # 4) keep，软排除降权
    score = 1.0
    if soft_hits:
        score -= 0.15 * len(soft_hits)
    if hard_hits and device_hits:
        score -= 0.3  # 硬排除词但含器件上下文，降权保留

    # 5) 仅命中通用 PV 词（photovoltaic/photovoltage）而无强器件信号 -> 压到 <=0.4
    generic_only = (not strong_hits) and any(w in GENERIC_PV for w in core_hits)
    if generic_only:
        score = min(score, 0.4)
        reason_suffix = " (generic PV only, no device signal -> downweighted)"
    else:
        reason_suffix = ""

    score = max(0.3, round(score, 2))

    result["keep"] = True
    reason = "core PV signal: " + ", ".join(core_hits[:3])
    if hard_hits and device_hits:
        reason += " (kept despite: " + ", ".join(hard_hits) + ")"
    if soft_hits:
        reason += " (soft: " + ", ".join(soft_hits[:3]) + ")"
    result["relevance_reason"] = reason + reason_suffix
    result["relevance_score"] = score
    return result


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) > 1:
        feed = json.load(open(sys.argv[1], encoding="utf-8"))
        items = feed.get("items", feed if isinstance(feed, list) else [])
    else:
        items = [json.loads(l) for l in sys.stdin if l.strip()]

    kept, rej = [], []
    for it in items:
        r = filter_item(it)
        (kept if r["keep"] else rej).append(r)

    print(f"KEPT={len(kept)} REJECTED={len(rej)}")
    for r in rej:
        print(f"  REJECT {r.get('id')}: {r['reject_reason']}")
