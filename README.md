# perovskite-scout-skill

**中文名：钙钛矿情报雷达**  
**项目名：Perovskite Scout**  
**版本：v0.1.0**

这是一个面向钙钛矿光伏领域的可信源情报雷达。它会定时追踪论文与行业动态，使用确定性规则过滤噪声、判定可信度、跨来源去重，并生成可直接发到微信的文本简报和图片卡片。

这个项目的重点不是“让 LLM 帮你随便搜新闻”，而是建立一条可审计、可复现、可定时运行的情报管线：

```text
论文发现 → 元数据补全 → 行业 RSS → 跨 feed 去重
→ 文本/图片渲染 → 校验 → 投递包
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
- 生成微信可用的：
  - `output/delivery/message.txt`：文本简报
  - `output/delivery/card.png`：图片卡片
  - `output/delivery/delivery-manifest.json`：投递决策
- 支持本地投递包和 webhook 投递出口。
- 提供 Codex / Claude Code / HermesAgent / openclaw 的适配入口。

## 快速运行

```bash
# 预览模式：忽略去重，生成完整本轮内容，适合调试和人工检查
python scripts/deliver.py --mode preview

# 生产模式：正常去重，只推本周期新增内容；无新增时自动 skipped
python scripts/deliver.py

# 只校验，不投递
python scripts/validate_outputs.py
```

如果需要生成 PNG 图片卡片，安装可选依赖：

```bash
pip install -r requirements-optional.txt
```

未安装 Pillow 时，图片渲染会退回 HTML，不影响其他环节。

## 投递规则

`scripts/deliver.py` 运行后读取：

```text
output/delivery/delivery-manifest.json
```

根据 `status` 决定是否发送：

| status | 动作 |
|---|---|
| `ready` | 发送 `card.png` + `message.txt` |
| `skipped` | 本轮无新增，不发送 |
| 命令退出码非 0 | 管线或校验失败，不发送正文，只发错误通知 |

openclaw 定时投递说明见 [openclaw-manual.md](openclaw-manual.md)。webhook 协议见 [perovskite-scout-skill/references/webhook-contract.md](perovskite-scout-skill/references/webhook-contract.md)。

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

当前 v0.1.0 包含：

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
scripts/                      抓取、过滤、去重、渲染、校验、投递脚本
perovskite-scout-skill/       跨 Agent skill 包
openclaw-manual.md            openclaw 定时投递说明
README-perovskite-scout.md    更详细的运行手册
VERSION                       当前版本
```

## English Short Description

Perovskite Scout is a trusted-source intelligence radar for perovskite photovoltaics. It tracks papers and curated industry RSS feeds, filters and ranks items with deterministic rules, renders WeChat-ready digest artifacts, validates them, and packages them for scheduled delivery.
