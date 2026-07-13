# webhook 投递协议（最小约定）

`scripts/deliver.py --transport webhook` 在投递就绪时，向环境变量 `$DELIVERY_WEBHOOK` 指向的地址发送一次 `POST`（JSON，`Content-Type: application/json`）。

> 仅在 `status=ready` 时发送。`skipped` 与 `failed` 都**不**发 webhook（对应「安静周不刷屏」「校验失败不发坏内容」）。

## 状态机

| status | 含义 | 是否 POST | 调度器动作 |
|--------|------|-----------|------------|
| `ready` | 校验全绿且有新内容 | 是 | 发 `card_path` + `compact_message_path`，缺短版再回退长版 |
| `skipped` | 本轮无新内容（安静周） | 否 | 不发；旧文件已清空，不要发历史图文 |
| `failed` | 校验未全绿（命令退出码非 0） | 否 | 不发正文；改发错误通知 |
| `preparing` | 组包中的瞬时状态 | 否 | 不发、不告警；等待命令结束后重读 manifest |

## 载荷字段（最小协议）

```json
{
  "status": "ready",
  "mode": "production",
  "message_path": "output/delivery/message.txt",
  "compact_message_path": "output/delivery/message-compact.txt",
  "card_path": "output/delivery/card.png",
  "paper_count": 3,
  "industry_count": 2
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 稳定终态为 `ready` / `skipped` / `failed`；组包时可能短暂为 `preparing` |
| `mode` | string | `production`（默认）或 `preview` |
| `message_path` | string | 微信文本正文路径（相对项目根） |
| `compact_message_path` | string | 微信短版路径（相对项目根；新接收端优先） |
| `card_path` | string | 微信图片卡片路径（相对项目根） |
| `paper_count` | int | 本周期进入 feed-papers 的新论文数 |
| `industry_count` | int | 本周期进入 feed-industry 的新产业动态数 |

## 调度器实现要点

- 读 `status` 决定动作，不要自行判断内容是否值得发。
- `ready`：读取 `card_path` 与 `compact_message_path` 并发到个人微信；短版字段不存在时回退 `message_path`。
- `skipped`：结束，不发任何东西。
- `failed`：发错误告警（不要发 `message_path` 正文，可能不完整）。
- 路径为相对项目根的路径，调度器需以项目根为基准解析。
- 若走「读目录」而非 webhook：`python scripts/deliver.py` 默认写 `output/delivery/`，按 `delivery-manifest.json` 的 `status` 同样决策（见 openclaw-manual.md）。

为兼容已有接收端，实际 POST 还保留 `text`、`image_path`、嵌套 `manifest`；新增 `compact_text` 可直接发送，无需接收端再次读取文件。以上字段均为加法，旧字段不删除。

`card_path` / `image_path` 是任务机器上的文件路径，并不上传图片二进制。远端 webhook 接收器必须有共享挂载或另行实现上传层。
