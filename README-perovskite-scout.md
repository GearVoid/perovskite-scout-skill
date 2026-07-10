# perovskite-scout — 钙钛矿情报雷达 MVP

可信源钙钛矿科研情报雷达。定时抓取 arXiv 论文 → 机器相关性过滤 → 机器可信度分级 → 输出纯文本简报 + 微信图片卡片。

**全链路不调用 LLM**（红线 R3）：发现、过滤、分级、渲染全部为确定性规则。

---

## 两条命令即可运行

```bash
# 1) 跑全链路：抓取 -> 过滤 -> 去重 -> enrich -> 文本/图片渲染
python scripts/run_pipeline.py [--rebuild | --ignore-state]

# 2) 校验产物完整性 + Top5 一致性
python scripts/validate_outputs.py
```

`validate_outputs.py` 退出码：`0` = 全绿，`1` = 有失败项。

---

## 依赖

- **必需**：Python 3.10+，仅标准库（`json` / `urllib` / `pathlib` 等）。发现、过滤、分级、文本渲染、校验都不需第三方包。
- **可选**：`Pillow>=12`，仅用于生成 PNG 图片卡片。见 `requirements-optional.txt`。

```bash
pip install -r requirements-optional.txt   # 仅当需要 PNG 卡片
```

未安装 Pillow 时，`image_renderer` 自动退回生成 `output/perovskite-scout-card.html`，其余环节不受影响，不会报错卡住。

---

## 运行环境

- 任意 **Python 3.10+** 解释器即可；本地用系统 `python` 或项目托管 Python 都可。
- **openclaw 部署时，由运行环境自带的 Python 执行 `run_pipeline.py`**，无需在仓库里固化解释器路径。
- 终端编码问题：脚本会在入口把 stdout/stderr 重设为 UTF-8（errors=replace），即使 Windows GBK 控制台也不会因中文/希腊字母/下标符号崩溃。

---

## OpenAlex 联系邮箱（配置化）

OpenAlex 鼓励在请求里带 `mailto` 以进入“礼貌池”（更高限速）。默认占位为 `perovskite-scout@example.com`。

改成真实邮箱有两种方式（**优先级：环境变量 > 配置文件**）：

```bash
# 方式 1: 环境变量 (推荐用于 openclaw / CI, 不落盘)
export OPENALEX_MAILTO=you@example.com

# 方式 2: 配置文件 config/enrich.json
{ "openalex_mailto": "you@example.com" }
```

`enrich_metadata.py` 会在每次运行时读取；改完无需动代码。`validate_outputs.py` 也会检查该邮箱是否已配置。

---

## `--rebuild` 与 `--ignore-state` 的区别

| 参数 | 行为 | 何时用 |
|------|------|--------|
| （默认，无参数） | 正常去重：已见过的 arXiv id 不再输出，只吐新增 | **每周定时跑的正确用法**，不要加任何参数 |
| `--ignore-state` | 忽略去重判定，但**仍会更新** `state-feed.json`；本次把本轮抓到的全部论文当作新增输出 | 调试 / 想看本轮全部抓取结果（注意：下次默认跑不会再重复，因为 state 已记录） |
| `--rebuild` | 先清空 `state-feed.json` 再正常去重 = 从头生成 | 改了过滤规则后重置基线 |

> 注意：`--rebuild` 会删除 `state-feed.json`（去重记忆）。改 `relevance_filter.py` 规则后用它重跑，才能看到新的过滤结果。
>
> 定时任务（openclaw）**只调用 `python scripts/run_pipeline.py`，不加任何参数**，由 `state-feed.json` 自动去重，避免每周重复投递。

---

## 输出产物

| 文件 | 说明 |
|------|------|
| `feed-papers.json` | 本轮命中过滤的论文（每条含 tier / score / reason） |
| `rejected-papers.json` | 被相关性过滤拒绝的论文 + `reject_reason`（审计用） |
| `output/perovskite-scout-digest.txt` | 纯文本简报，可直接复制到微信 |
| `output/perovskite-scout-card.png` | 微信图片卡片（Top5，`1080px` 宽；需 Pillow） |
| `output/perovskite-scout-card.html` | 无 Pillow 时的图片卡片回退产物 |
| `state-feed.json` | 去重状态（已见 arXiv id），勿手动编辑 |

`digest.txt` 含完整链接；`card.png` 为排版美观**不放链接**，二者组合发出即"图片 + 文本"的微信呈现。

---

## 文件结构

```
config/sources.json          # 数据源（当前仅 arXiv）
config/enrich.json           # OpenAlex 联系邮箱等 enrich 配置
scripts/discover_papers.py   # 抓取 + 去重（含 429 退避重试 + 文本清洗）
scripts/relevance_filter.py  # v2 相关性过滤（探测器硬拒 / 多铁降权）
scripts/tier_mapper.py       # 机器可信度分级 T1-T4
scripts/enrich_metadata.py   # Crossref/OpenAlex 字段补全（只补字段, 不新增发现源）
scripts/text_renderer.py     # 纯文本简报
scripts/image_renderer.py    # 微信图片卡片（Pillow / HTML fallback）
scripts/text_utils.py        # 共享文本卫生（防乱码 / 终端 UTF-8 重设）
scripts/run_pipeline.py      # 一键串联
scripts/validate_outputs.py  # 产出校验
requirements-optional.txt    # 仅 Pillow
```

---

## 设计锚点

完整决策与红线见 `perovskite-scout-playbook.md`，架构细节见 `perovskite-scout-spec.md`。

---

## 暂未做（阶段规划）

- Crossref / OpenAlex **作为发现源**接入（当前仅用于 enrich；arXiv 仍是唯一发现源）
- 微信实际投递通道（openclaw + 个人微信）
- PDF 指标抽取（第二阶段，复用 perla-extract + NOMAD gold set）
- 抽象为通用"可信源情报雷达" skill（待多领域验证后再做）

> 阶段 1.5 已完成：`enrich_metadata.py` 用 OpenAlex（优先，给机构 + openalex_id + doi）与 Crossref（回退，补 DOI）补全 `doi / openalex_id / institutions / corresponding_source / enrich_errors`。不新增发现源、不影响 keep/reject/tier/rank。
>
> 注意：arXiv **预印本**在 OpenAlex 通常不携带机构信息，故 `institutions` 对新鲜预印本多为空列表；发表后的期刊论文才会有机构。`doi` 字段对预印本为 `10.48550/arxiv.{id}`。OpenAlex 查询必须用 `filter=doi:https://doi.org/10.48550/arxiv.{id}`（`arxiv` / `arxiv_id` 均不是合法 filter 字段）。
