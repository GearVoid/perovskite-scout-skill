"""Offline regression tests for rendering and delivery safety contracts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deliver  # noqa: E402
import image_renderer  # noqa: E402
from relevance_filter import filter_industry_item  # noqa: E402
from text_renderer import (  # noqa: E402
    COMPACT_LIMIT,
    render_compact_digest,
    render_portable_digest,
)


class RelevanceContractTests(unittest.TestCase):
    def test_industry_gate_keeps_curated_source_without_terms(self):
        judged = filter_industry_item({"title": "Anything", "summary": ""}, [])
        self.assertTrue(judged["keep"])
        self.assertEqual(judged["relevance_score"], 1.0)
        self.assertEqual(judged["relevance_reason"], "source-curated (no gate)")

    def test_industry_gate_uses_config_order_and_rejects_miss(self):
        item = {"title": "A tandem module", "summary": "perovskite detail"}
        judged = filter_industry_item(item, ["perovskite", "tandem"])
        self.assertEqual(judged["relevance_reason"], "keyword-match: perovskite")

        rejected = filter_industry_item(item, ["silicon-only"])
        self.assertFalse(rejected["keep"])
        self.assertEqual(rejected["reject_reason"], "no keyword match")


class RenderingContractTests(unittest.TestCase):
    def test_image_text_normalizes_font_hostile_dashes(self):
        self.assertEqual(
            image_renderer.image_text("A‑B–C−D", role="body"),
            "A-B-C-D",
        )

    def test_no_cjk_role_uses_explicit_fallback(self):
        with patch.dict(image_renderer.ROLE_HAS_CJK, {"body": False}):
            self.assertEqual(image_renderer.ui_text("中文", "English", role="body"), "English")
            self.assertEqual(image_renderer.image_text("中文 title", role="body"), "[CN] title")

    def test_card_takeaway_is_rule_based_with_font_safe_fallback(self):
        item = {"title": "Interface passivation for stable perovskite devices"}
        self.assertEqual(image_renderer.card_takeaway(item), "看点：钝化策略与缺陷控制")
        with patch.dict(image_renderer.ROLE_HAS_CJK, {"body": False}):
            self.assertEqual(
                image_renderer.card_takeaway(item),
                "Focus: passivation and defect control",
            )

    def test_card_takeaway_prefers_specific_title_signal(self):
        item = {"title": "Mobile ions under reverse bias in stable perovskite diodes"}
        self.assertEqual(image_renderer.card_takeaway(item), "看点：反偏稳定性与离子行为")

    def test_tier_descriptor_explains_badge_and_falls_back_with_font(self):
        self.assertEqual(image_renderer.tier_descriptor("T1"), "原始论文")
        with patch.dict(image_renderer.ROLE_HAS_CJK, {"body": False}):
            self.assertEqual(image_renderer.tier_descriptor("T3"), "Industry media")

    def test_compact_digest_keeps_links_and_omits_abstracts(self):
        papers = [{
            "title": "Paper title",
            "url": "https://arxiv.org/abs/1",
            "provenance_tier": "T1",
            "abstract": "must not leak into compact",
        }]
        industry = [{
            "title": "Industry title",
            "url": "https://example.com/news",
            "source_name": "Example",
            "provenance_tier": "T3",
        }]
        text = render_compact_digest(papers, industry, "2026-07-13", 1, 1)
        self.assertIn("[T1] Paper title", text)
        self.assertIn("https://arxiv.org/abs/1", text)
        self.assertIn("https://example.com/news", text)
        self.assertNotIn("must not leak", text)
        self.assertLessEqual(len(text), COMPACT_LIMIT)

    def test_portable_digest_keeps_links_without_wechat_or_image_instructions(self):
        papers = [{
            "title": "Paper title",
            "url": "https://arxiv.org/abs/1",
            "provenance_tier": "T1",
        }]
        industry = [{
            "title": "Industry title",
            "url": "https://example.com/news",
            "source_name": "Example",
            "provenance_tier": "T3",
        }]
        text = render_portable_digest(papers, industry, "2026-07-13", 1, 1)
        self.assertIn("https://arxiv.org/abs/1", text)
        self.assertIn("https://example.com/news", text)
        self.assertIn("证据等级：T1", text)
        self.assertNotIn("微信", text)
        self.assertNotIn("看图", text)


class DeliveryContractTests(unittest.TestCase):
    def test_compact_delivery_message_has_no_duplicate_technical_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            digest = Path(tmp) / "compact.txt"
            digest.write_text("钙钛矿情报雷达｜2026-07-13\n正文", encoding="utf-8")
            message = deliver.build_message("preview", digest, compact=True)
            self.assertTrue(message.startswith("【预览模式】\n"))
            self.assertEqual(message.count("钙钛矿情报雷达"), 1)

    def test_ready_manifest_is_additive_and_failure_clears_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery_dir = root / "delivery"
            card = root / "card.png"
            papers = root / "feed-papers.json"
            industry = root / "feed-industry.json"
            card.write_bytes(b"png-placeholder")
            papers.write_text('{"count": 2}', encoding="utf-8")
            industry.write_text('{"count": 1}', encoding="utf-8")

            with (
                patch.object(deliver, "DELIVERY_DIR", delivery_dir),
                patch.object(deliver, "CARD_PNG", card),
                patch.object(deliver, "FEED_PAPERS", papers),
                patch.object(deliver, "FEED_INDUSTRY", industry),
            ):
                manifest_path = deliver.write_local("full", "compact", "preview")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["text_file"], "message.txt")
                self.assertEqual(manifest["preferred_text_file"], "message-compact.txt")
                self.assertTrue((delivery_dir / "message-portable.txt").exists())
                self.assertTrue((delivery_dir / "card.png").exists())

                deliver.write_status_manifest("failed", "preview", "validation_failed")
                self.assertFalse((delivery_dir / "message.txt").exists())
                self.assertFalse((delivery_dir / "message-compact.txt").exists())
                self.assertFalse((delivery_dir / "message-portable.txt").exists())
                self.assertFalse((delivery_dir / "card.png").exists())
                failed = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(failed["status"], "failed")

    def test_target_profile_selects_portable_text_and_text_only_delivery(self):
        target, profile = deliver.load_target_profile("generic")
        self.assertEqual(target, "generic")
        self.assertEqual(profile["preferred_text_file"], "message-portable.txt")
        self.assertEqual(profile["send_order"], ["text"])
        feishu_target, feishu_profile = deliver.load_target_profile("feishu")
        self.assertEqual(feishu_target, "feishu")
        self.assertEqual(feishu_profile["image_mode"], "upload_required")
        self.assertEqual(feishu_profile["max_text_chars"], 8000)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(deliver, "DELIVERY_DIR", root / "delivery"),
                patch.object(deliver, "CARD_PNG", root / "missing-card.png"),
                patch.object(deliver, "FEED_PAPERS", root / "feed-papers.json"),
                patch.object(deliver, "FEED_INDUSTRY", root / "feed-industry.json"),
            ):
                (root / "feed-papers.json").write_text('{"items": []}', encoding="utf-8")
                (root / "feed-industry.json").write_text('{"items": []}', encoding="utf-8")
                manifest_path = deliver.write_local(
                    "full", "compact", "production",
                    portable_message="portable",
                    target_name=target,
                    target_profile=profile,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["preferred_text_file"], "message-portable.txt")
        self.assertIsNone(manifest["image_file"])
        self.assertFalse((root / "delivery" / "card.png").exists())

    def test_pipeline_exception_replaces_old_ready_package_with_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            delivery_dir = Path(tmp) / "delivery"
            delivery_dir.mkdir()
            (delivery_dir / "message.txt").write_text("stale", encoding="utf-8")
            (delivery_dir / "card.png").write_bytes(b"stale")
            (delivery_dir / "delivery-manifest.json").write_text(
                '{"status":"ready"}', encoding="utf-8"
            )

            with (
                patch.object(deliver, "DELIVERY_DIR", delivery_dir),
                patch.object(deliver.run_pipeline, "main", side_effect=RuntimeError("boom")),
                patch.object(sys, "argv", ["deliver.py", "--mode", "preview"]),
            ):
                self.assertEqual(deliver.main(), 1)

            manifest = json.loads(
                (delivery_dir / "delivery-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse((delivery_dir / "message.txt").exists())
            self.assertFalse((delivery_dir / "card.png").exists())


if __name__ == "__main__":
    unittest.main()
