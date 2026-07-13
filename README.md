# perovskite-scout-skill

<a id="zh"></a>

**中文名：钙钛矿情报雷达**  
**项目名：Perovskite Scout**  
**版本：v0.2.0**

语言：**中文** | [English](#en)

![钙钛矿情报雷达预览](docs/perovskite-scout-card.png)

这是一个面向钙钛矿光伏领域的可信源情报雷达。它会定时追踪论文与行业动态，使用确定性规则过滤噪声、判定可信度、跨来源去重，并生成可按微信、通用机器人或飞书策略投递的文本简报和图片卡片。

这个项目的重点不是“让 LLM 帮你随便搜新闻”，而是建立一条可审计、可复现、可定时运行的情报管线：

```text
论文发现 -> 元数据补全 -> 行业 RSS -> 跨 feed 去重
-> 文本/图片渲染 -> 校验 -> 投递包
```

## 核心原则

**LLM 不参与可信度和相关性判定。**

- 可信度 `tier` 只能由 `scripts/tier_mapper.py` 判定。
- 相关性 `relevance` 只能由 `scripts/relevance_filter.py` 判定。
- LLM 不得决定某条内容是否进入 feed。
- 投递前必须通过 `scripts/validate_outputs.py`。
- 生产模式遇到“安静周”时只写 `skipped`，不发送旧内容。

## 当前能力

- 从 arXiv 发现钙钛矿光伏相关论文。
- 用 OpenAlex / Crossref 补 DOI、OpenAlex ID 等元数据。
- 从 Perovskite-Info、pv magazine 等行业 RSS 抓取产业动态。
- 论文 feed 与行业 feed 分开保存，并做跨 feed 去重。
- 生成可按目标平台选择的投递产物：
  - `output/delivery/message.txt`：文本简报
  - `output/delivery/message-compact.txt`：微信短版（标题 + 可点击原始链接）
  - `output/delivery/message-portable.txt`：平台无关的纯文本链接简报
  - `output/delivery/card.png`：图片卡片
  - `output/delivery/delivery-manifest.json`：投递决策
- 通过 `config/delivery-targets.json` 为 `wechat`、`generic`、`feishu` 声明文本、长度、发送顺序和图片规则。
- 支持带幂等键的本地投递包和 webhook 投递出口。
- 提供 Codex / Claude Code / HermesAgent / openclaw 的适配入口。

## 快速运行

```bash
# 预览模式：忽略去重，生成完整本轮内容，适合调试和人工检查
python scripts/deliver.py --mode preview

# 生产模式：正常去重，只推本周期新增内容；无新增时自动 skipped
python scripts/deliver.py

# 平台无关的机器人 / 文本通道
python scripts/deliver.py --target generic

# 飞书：文本可直接发；图片需由适配器上传并换取 image_key
python scripts/deliver.py --target feishu

# 只校验，不投递
python scripts/validate_outputs.py
```

如果需要生成 PNG 图片卡片，安装可选依赖：

```bash
pip install -r requirements-optional.txt
```

未安装 Pillow 时，图片渲染会退回 HTML，适合人工预览；只有发送顺序包含卡片的目标才要求 PNG。默认微信目标仍要求 PNG，`generic` 文本目标不要求。

## 投递规则

`scripts/deliver.py` 运行后读取：

```text
output/delivery/delivery-manifest.json
```

根据 `status` 决定是否发送：

| status | 动作 |
|---|---|
| `ready` | 按 manifest 的 `send_order` 发送其 `preferred_text_file`；默认 `wechat` 为 `card.png` 后接 `message-compact.txt` |
| `skipped` | 本轮无新增，不发送 |
| 命令退出码非 0 | 管线或校验失败，不发送正文，只发错误通知 |

openclaw 定时投递说明见 [openclaw-manual.md](openclaw-manual.md)。webhook 协议见 [perovskite-scout-skill/references/webhook-contract.md](perovskite-scout-skill/references/webhook-contract.md)。

`generic` 发送 `message-portable.txt`；`feishu` 同样使用该文本，但若发送图片，接收适配器必须先上传 `card.png`，不能把本机路径直接当作飞书图片。

## 跨 Agent 入口

```text
perovskite-scout-skill/
  SKILL.md       # Codex 入口
  CLAUDE.md      # Claude Code 入口
  HERMES.md      # HermesAgent 入口
  references/    # openclaw 手册、webhook 协议、spec、playbook
```

这些入口只引用项目根目录下的同一套 `scripts/`，不复制脚本，避免双源维护。

## 数据源

当前 v0.2.0 包含：

- arXiv：论文发现源
- OpenAlex / Crossref：论文元数据补全，不作为发现源
- Perovskite-Info：行业 RSS
- pv magazine：行业 RSS + 关键词过滤

暂缓内容：

- 官方 newsroom HTML 监控
- NREL 效率图 monitored asset
- X / LinkedIn / 公众号 / 博主社交层
- PDF 器件指标抽取与 PERLA / NOMAD 式验证

## 文件说明

```text
config/                       数据源与 enrich 配置
config/delivery-targets.json  平台投递策略
scripts/                      抓取、过滤、去重、渲染、校验、投递脚本
perovskite-scout-skill/       跨 Agent skill 包
openclaw-manual.md            openclaw 定时投递说明
HANDOFF.md                    给未来 Agent / 新对话的交接文档
.env.example                  可选环境变量示例
README-perovskite-scout.md    更详细的运行手册
CHANGELOG.md                  版本变更记录
VERSION                       当前版本
```

---

<a id="en"></a>

# Perovskite Scout Skill

Language: [中文](#zh) | **English**

![Perovskite Scout preview](docs/perovskite-scout-card.png)

Perovskite Scout is a trusted-source intelligence radar for perovskite photovoltaics. It tracks papers and curated industry RSS feeds, filters and ranks items with deterministic rules, deduplicates across feeds, renders delivery artifacts, validates them, and packages them for scheduled delivery across target platforms.

The project is intentionally conservative: it does not ask an LLM to browse, judge trustworthiness, decide relevance, or choose what enters the feed. Those decisions are handled by auditable rule-based scripts.

```text
paper discovery -> metadata enrichment -> industry RSS -> cross-feed dedupe
-> text/image rendering -> validation -> delivery package
```

## Core Principles

**LLMs do not decide trust or relevance.**

- `tier` must be assigned by `scripts/tier_mapper.py`.
- `relevance` must be assigned by `scripts/relevance_filter.py`.
- LLMs must not decide whether an item enters a feed.
- Delivery must pass `scripts/validate_outputs.py`.
- Quiet production runs write `skipped` and must not send stale content.

## What It Does

- Discovers perovskite PV papers from arXiv.
- Enriches paper metadata through OpenAlex and Crossref.
- Tracks curated industry RSS feeds such as Perovskite-Info and pv magazine.
- Keeps paper and industry feeds separate, then deduplicates across them.
- Generates target-aware delivery artifacts:
  - `output/delivery/message.txt`: text digest
  - `output/delivery/message-compact.txt`: compact WeChat link companion
  - `output/delivery/message-portable.txt`: portable plain-text link digest
  - `output/delivery/card.png`: image card
  - `output/delivery/delivery-manifest.json`: delivery decision manifest
- Declares text, size, send-order, and image policies for `wechat`, `generic`, and `feishu` in `config/delivery-targets.json`.
- Supports idempotent local delivery packaging and webhook delivery.
- Provides adapter entrypoints for Codex, Claude Code, HermesAgent, and openclaw.

## Quick Start

```bash
# Preview mode: ignore state and generate a full current digest.
python scripts/deliver.py --mode preview

# Production mode: normal dedupe; quiet weeks are marked as skipped.
python scripts/deliver.py

# Platform-neutral bot / text channel
python scripts/deliver.py --target generic

# Feishu: send the portable text; an adapter must upload any image first.
python scripts/deliver.py --target feishu

# Validate outputs without delivery.
python scripts/validate_outputs.py
```

Optional PNG rendering dependency:

```bash
pip install -r requirements-optional.txt
```

Without Pillow, the image renderer falls back to HTML for manual preview. Only targets whose send order includes a card require PNG; the default WeChat target does, while the text-only `generic` target does not.

## Delivery Contract

After `scripts/deliver.py` runs, read:

```text
output/delivery/delivery-manifest.json
```

Use `status` to decide what to send:

| status | Action |
|---|---|
| `ready` | Follow manifest `send_order` and `preferred_text_file`; default `wechat` sends `card.png` followed by `message-compact.txt` |
| `skipped` | No new content; send nothing |
| non-zero command exit | Pipeline or validation failed; send an error notification, not the digest |

See [openclaw-manual.md](openclaw-manual.md) for scheduler setup and [perovskite-scout-skill/references/webhook-contract.md](perovskite-scout-skill/references/webhook-contract.md) for the webhook contract. `generic` sends `message-portable.txt`; `feishu` uses the same text but requires its receiving adapter to upload `card.png` rather than treating a local path as an image.

## Cross-Agent Entrypoints

```text
perovskite-scout-skill/
  SKILL.md       # Codex
  CLAUDE.md      # Claude Code
  HERMES.md      # HermesAgent
  references/    # openclaw manual, webhook contract, spec, playbook
```

All entrypoints call the same project-level `scripts/` directory. The skill package does not copy scripts, which avoids double maintenance.

## Data Sources

Included in v0.2.0:

- arXiv: paper discovery
- OpenAlex / Crossref: metadata enrichment, not discovery
- Perovskite-Info: industry RSS
- pv magazine: industry RSS with keyword filtering

Deferred:

- official newsroom HTML monitors
- NREL efficiency chart monitored asset
- X / LinkedIn / WeChat public accounts / blogger-social layer
- PDF device-metric extraction with PERLA / NOMAD-style validation

## Repository Layout

```text
config/                       source and enrichment configuration
config/delivery-targets.json  target delivery policies
scripts/                      discovery, filtering, dedupe, rendering, validation, delivery
perovskite-scout-skill/       cross-agent skill package
openclaw-manual.md            openclaw scheduler and delivery notes
HANDOFF.md                    handoff guide for future agents or new chats
.env.example                  optional environment variable example
README-perovskite-scout.md    detailed running guide
CHANGELOG.md                  release history
VERSION                       current version
```
