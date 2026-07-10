# Perovskite Scout

**Version:** v0.1.0  
**中文名:** 钙钛矿情报雷达

Perovskite Scout is a trusted-source intelligence radar for perovskite photovoltaics. It watches papers and industry RSS feeds, filters noise with deterministic rules, enriches metadata, deduplicates across feeds, renders a WeChat-ready text digest and image card, validates the outputs, and packages the result for scheduled delivery.

The project is intentionally conservative: **LLMs do not decide relevance, provenance tier, or whether an item enters a feed**. Those decisions are made by rule-based scripts and checked before delivery.

## What It Does

- Discovers perovskite PV papers from arXiv.
- Enriches paper metadata through OpenAlex and Crossref without adding new discovery sources.
- Tracks curated industry RSS sources such as Perovskite-Info and pv magazine.
- Keeps paper and industry feeds separate, then deduplicates across them.
- Generates:
  - `output/delivery/message.txt` for WeChat text.
  - `output/delivery/card.png` for a WeChat image card.
  - `output/delivery/delivery-manifest.json` for delivery decisions.
- Supports local delivery packaging and webhook delivery.
- Provides entry files for Codex, Claude Code, HermesAgent, and openclaw.

## Quick Start

```bash
# Preview mode: generate a full current digest without production delivery semantics.
python scripts/deliver.py --mode preview

# Production mode: normal dedupe; quiet weeks are marked as skipped.
python scripts/deliver.py

# Validate generated outputs.
python scripts/validate_outputs.py
```

Optional PNG rendering dependency:

```bash
pip install -r requirements-optional.txt
```

Without Pillow, the image renderer falls back to HTML.

## Delivery Contract

After `scripts/deliver.py` runs, inspect:

```text
output/delivery/delivery-manifest.json
```

- `status=ready`: send `card.png` + `message.txt`.
- `status=skipped`: no new content; send nothing.
- non-zero command exit: validation or pipeline failure; send an error notification, not the digest.

See [openclaw-manual.md](openclaw-manual.md) and [perovskite-scout-skill/references/webhook-contract.md](perovskite-scout-skill/references/webhook-contract.md) for scheduler and webhook details.

## Agent Entrypoints

```text
perovskite-scout-skill/
  SKILL.md       # Codex
  CLAUDE.md      # Claude Code
  HERMES.md      # HermesAgent
  references/    # openclaw manual, webhook contract, spec, playbook
```

All agent entrypoints call the same project scripts from the repository root. The skill package does not copy `scripts/`, which avoids double maintenance.

## Guardrails

- `tier` must be decided by `scripts/tier_mapper.py`.
- `relevance` must be decided by `scripts/relevance_filter.py`.
- LLMs must not decide trustworthiness, relevance, or feed inclusion.
- Delivery must pass `scripts/validate_outputs.py`.
- Quiet production runs must not send stale content.
- Social/blogger tracking is deferred.

## Current Scope

Included in v0.1.0:

- arXiv paper discovery
- OpenAlex/Crossref metadata enrichment
- curated industry RSS discovery
- cross-feed deduplication
- WeChat text/image rendering
- validation gate
- local/webhook delivery packaging
- Codex/Claude/Hermes/openclaw adapter docs

Deferred:

- official newsroom HTML monitors
- NREL efficiency chart monitoring
- social/blogger sources
- PDF device-metric extraction with PERLA/NOMAD-style validation

For implementation details, see [README-perovskite-scout.md](README-perovskite-scout.md).
