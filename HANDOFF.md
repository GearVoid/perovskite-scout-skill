# Perovskite Scout Skill 交接文档

本仓库是 **Perovskite Scout / 钙钛矿情报雷达** 的独立 skill 工程。它用于定时追踪钙钛矿光伏论文与产业动态，生成按平台目标投递的文本简报和图片卡片，并通过校验闸门保证不发送坏内容。

## 当前状态

- 版本：`v0.2.0`
- GitHub：`https://github.com/GearVoid/perovskite-scout-skill`
- 入口：`python scripts/deliver.py`
- 当前已支持：
  - arXiv 论文发现
  - OpenAlex / Crossref 元数据补全
  - Perovskite-Info / pv magazine 行业 RSS
  - 论文 + 行业双 feed
  - 跨 feed 去重
  - 微信、通用文本机器人和飞书的投递目标策略
  - local / webhook 投递包、稳定 `delivery_id` 和单实例锁
  - Codex / Claude Code / HermesAgent / openclaw 入口说明

## 未来 Agent 接手第一步

从仓库根目录运行：

```bash
python scripts/deliver.py --mode preview
python scripts/validate_outputs.py
```

若要生产模式：

```bash
python scripts/deliver.py
```

生产模式会正常去重；无新增内容时写 `status=skipped`，不发送旧内容。

## 关键产物

```text
output/delivery/message.txt             微信文本正文
output/delivery/message-compact.txt     微信短版（推荐随卡片发送）
output/delivery/message-portable.txt    平台无关的纯文本链接简报
output/delivery/card.png                微信图片卡片
output/delivery/delivery-manifest.json  投递决策
```

`delivery-manifest.json` 规则：

- `ready`：按 manifest 的 `send_order` 与 `preferred_text_file` 发送；默认微信为 `card.png` + `message-compact.txt`，generic/feishu 使用 `message-portable.txt`
- `skipped`：本轮无新增，不发送
- 命令退出码非 0：校验或管线失败，不发送正文

## 必守红线

1. `tier` 只能由 `scripts/tier_mapper.py` 判定。
2. `relevance` 只能由 `scripts/relevance_filter.py` 判定。
3. LLM 不得决定可信度、相关性或是否进入 feed。
4. 投递前必须通过 `scripts/validate_outputs.py`。
5. validate 失败不得投递。
6. production 安静周不得发送旧内容。
7. 社交 / 博主层继续 defer。

## 配置

建议复制 `.env.example` 或在调度平台设置环境变量：

```bash
OPENALEX_MAILTO=you@example.com
DELIVERY_WEBHOOK=https://example.com/perovskite-scout-delivery
```

`OPENALEX_MAILTO` 不是密钥，只是 OpenAlex 推荐的联系邮箱。

投递目标在 `config/delivery-targets.json` 中维护。默认 `wechat`；通用机器人用 `python scripts/deliver.py --target generic`；飞书图片必须由接收适配器上传为 `image_key`，不可直接使用本机 `card.png` 路径。

## 云端字体说明

如果希望 PNG 图片里的标题和分区保持中文，云端镜像需要安装 CJK 字体，推荐：

- Noto Sans CJK
- Source Han Sans

如果没有完整 CJK 字体，`scripts/image_renderer.py` 会按 title/body/bold 字体角色分别降级固定标签；动态中文用明确的 `[CN]` 占位，避免静默出现方块字。三个文本产物始终保留原始 Unicode 文本。

## 运行时文件

以下文件是运行产物，不应提交：

```text
feed-*.json
rejected-*.json
state-*.json
output/
__pycache__/
.workbuddy/
```

## 后续建议

优先级从高到低：

1. openclaw 真实微信投递跑 1-2 期，观察内容质量。
2. 官方 newsroom HTML monitor。
3. NREL 效率图 monitored asset。
4. PERLA / NOMAD 风格 PDF 指标抽取。
5. 社交 / 博主层，继续暂缓，除非有稳定 API 或登录态方案。
