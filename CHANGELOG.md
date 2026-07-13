# Changelog

All notable changes to Perovskite Scout are documented here.

## v0.2.0 — 2026-07-13

- Made image cards easier to read: numbered card entries map deterministically to clickable text links, evidence tiers carry matching colors, and the legend explains T1–T4.
- Added a platform-neutral `message-portable.txt` and target policies in `config/delivery-targets.json`.
- Added `--target wechat|generic|feishu`; the manifest now declares the target, preferred text artifact, send order, and image mode.
- Kept WeChat as the default: send `card.png` first, then `message-compact.txt`. Generic targets send portable text; Feishu adapters must upload images rather than use local paths.
- Hardened delivery with a cross-platform single-instance lock, stable `delivery_id`, webhook idempotency, strict webhook failure behavior, and state rollback.
- Reworked arXiv discovery to page to a persisted watermark with bounded bootstrap/preview windows, so a busy week does not permanently hide older new entries.
- Documented the current delivery contract consistently across the README, handoff, agent entrypoints, OpenClaw manual, and webhook reference.

## v0.1.0

- Initial trusted-source perovskite paper and industry intelligence pipeline.
