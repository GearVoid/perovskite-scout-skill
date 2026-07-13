# openclaw 配置说明（Perovskite Scout v0.2.0）

外部调度系统只需做两件事：**定时调用 `deliver.py`**，再按 manifest 状态投递。

## 1. 定时任务

- **触发**：每周一 09:00（本地时区）
- **命令**（工作目录 = 项目根目录）：
  - 生产（默认微信目标）：`python scripts/deliver.py`
  - 通用机器人 / 纯文本通道：`python scripts/deliver.py --target generic`
  - 飞书：`python scripts/deliver.py --target feishu`
  - 预览 / 调试：`python scripts/deliver.py --mode preview`
- **超时**：建议 ≥ 240s（arxiv + 行业 RSS + enrich + 渲染 + 校验）

## 2. 投递决策（读 manifest）

管线结束后读 `output/delivery/delivery-manifest.json`：

| `status` | 动作 |
|----------|------|
| `ready` | 按 manifest 的 `send_order` 与 `preferred_text_file` 发送；默认微信先发 `card.png` 再发 `message-compact.txt`，两者用 01–07 对应 |
| `skipped` | 不发送（本轮无新内容，旧文件已清空） |
| `preparing` | 组包中的瞬时状态；不发送、不告警，等待命令结束后重读 |
| 命令退出码非 0 | 不发正文，发错误通知 |

> 退出码 `0` = 成功（`ready` 或 `skipped`）；非 `0` = 校验失败，脚本已主动终止，**绝不投递**。

### 目标策略

投递目标由 `config/delivery-targets.json` 定义，调用方不要仅按文件名猜测发送顺序：

| target | 推荐文本 | 图片处理 |
|---|---|---|
| `wechat`（默认） | `message-compact.txt` | 先发 `card.png`，再发短版链接索引；使用本机图片路径 |
| `generic` | `message-portable.txt` | 只发文本；图片可选 |
| `feishu` | `message-portable.txt` | 文本先发；如需图片，接收适配器先上传 `card.png` 并使用飞书 `image_key` |

## 3. webhook 模式（可选）

接收端与任务共享文件系统（或能解析这些路径）时，可用 webhook 出口通知就绪状态：

```bash
python scripts/deliver.py --transport webhook
```

最小协议（脚本自动 POST）：

```json
{
  "status": "ready",
  "mode": "production",
  "target": "wechat",
  "send_order": ["card", "text"],
  "image_mode": "local_path",
  "message_path": "output/delivery/message.txt",
  "compact_message_path": "output/delivery/message-compact.txt",
  "portable_message_path": "output/delivery/message-portable.txt",
  "preferred_text_file": "message-compact.txt",
  "card_path": "output/delivery/card.png",
  "paper_count": 3,
  "industry_count": 2
}
```

`status=skipped` 时不发 webhook。

> webhook 会直接携带长版、短版、通用文本以及按目标选出的 `preferred_text`，但图片仍以本地路径提供，不上传二进制；纯远端接收器若没有共享挂载，应自行增加上传层。飞书适配器必须把 `card.png` 上传为 `image_key`，不能直接发送本地路径。

## 4. 前置（一次性）

- Python 3.13 + Pillow：`pip install -r requirements-optional.txt`
- OpenAlex 邮箱：填 `config/enrich.json` 的 `openalex_mailto`，或设环境变量 `OPENALEX_MAILTO`
- 中文 PNG 字体：若希望图片标题/分区保持中文，云端镜像需安装 CJK 字体（推荐 Noto Sans CJK / Source Han Sans）。渲染器会按字体角色降级固定标签并规整易缺字标点；无 CJK 时动态中文显示为 `[CN]` 占位，两个文本文件仍保留原文。
- 工作目录须含 `config/`、`scripts/`、`README-perovskite-scout.md`

## 边界（已守住，调度方无需关心）

- 校验不全绿 → 不投递
- 安静周 → `skipped` + 清旧文件，openclaw 不会误发历史图文
- `production` 正常去重只推本周期新增；`preview` 看完整本轮内容
