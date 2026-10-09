from __future__ import annotations

import unittest

from mrh.terminal import render_stats


def provider_stats() -> dict:
    return {
        "schema_version": 2,
        "updated_at": "2026-10-10T04:30:00Z",
        "partition": "live",
        "proposals": 10,
        "jev_attempts": 10,
        "synthetic_attempts": 0,
        "classified_tasks": 10,
        "low_confidence_tasks": 1,
        "tiers": {"Light": 5, "Small": 3, "Mid": 1, "Top": 1},
        "outcomes": {"routed": 8, "preserved": 2},
        "requested_models": {"gpt-6-luna": 4},
        "confirmed_children": 2,
        "actual_models": {"gpt-6-luna": 1},
        "unknown_actual_model_children": 1,
        "cost": None,
        "tokens": None,
        "quota": None,
        "capabilities": {"jev": "available"},
        "jev": {
            "attempt_states": {"returned": 8, "error": 1, "unknown": 1},
            "requested_models": {"jev-1.13.0": 10},
            "response_models": {"jev-1.13.0": 9, "jev-1.14.0": 1},
            "input_tokens": None,
            "output_tokens": 240,
            "known_input_tokens": 1800,
            "known_output_tokens": 240,
            "usage_unavailable_attempts": 2,
            "estimated_cost": {
                "amount": 0.0000756,
                "currency": "USD",
                "kind": "estimate",
                "model": "jev-1.13.0",
                "price_source": "TypeSafe pricing page",
                "price_date": "2026-10-10",
                "unit": "per 1,000,000 input tokens",
            },
        },
        "handback_anomalies": 1,
    }


class ProviderTelemetryRenderTests(unittest.TestCase):
    def test_plain_composition_bar_is_segmented_and_shows_counts_and_shares(self) -> None:
        rendered = render_stats(provider_stats(), width=80, color=False)
        bar = rendered.split("TIER COMPOSITION\n", 1)[1].splitlines()[0]

        self.assertGreaterEqual(bar.count("|"), 3)
        for glyph in ("·", "░", "▒", "█"):
            self.assertIn(glyph, bar)
        for item in (
            "Light 5 (50.0%)",
            "Small 3 (30.0%)",
            "Mid 1 (10.0%)",
            "Top 1 (10.0%)",
        ):
            self.assertIn(item, rendered)
        self.assertNotIn("\x1b[", rendered)

    def test_narrow_composition_and_sections_fit_width_28(self) -> None:
        rendered = render_stats(provider_stats(), width=28, color=False)
        self.assertTrue(all(len(line) <= 28 for line in rendered.splitlines()))
        bar = rendered.split("TIER COMPOSITION\n", 1)[1].splitlines()[0]
        self.assertGreaterEqual(bar.count("|"), 3)
        self.assertIn("Top 1 (10.0%)", rendered)

    def test_jev_telemetry_is_separate_from_child_actual_models(self) -> None:
        rendered = render_stats(provider_stats(), width=80, color=False)
        actual_models, jev = rendered.split("JEV TELEMETRY\n", 1)

        self.assertIn("ACTUAL MODELS", actual_models)
        self.assertIn("gpt-6-luna: 1", actual_models)
        self.assertIn("Attempt states", jev)
        self.assertIn("returned: 8", jev)
        self.assertIn("Requested Jev model versions", jev)
        self.assertIn("jev-1.13.0: 10", jev)
        self.assertIn("Returned Jev model versions", jev)
        self.assertIn("jev-1.14.0: 1", jev)
        self.assertIn("Input token total: Unavailable", jev)
        self.assertIn("Output token total: 240", jev)
        self.assertIn("Known input tokens: 1800", jev)
        self.assertIn("Attempts with unavailable usage: 2", jev)
        self.assertIn("Cost type: Estimate", jev)
        self.assertIn("Price source: TypeSafe pricing page", jev)
        self.assertIn("Price date: 2026-10-10", jev)
        self.assertIn("Recorded anomaly count: 1", jev)

    def test_old_e2_statistics_show_new_fields_as_unavailable(self) -> None:
        stats = provider_stats()
        stats.pop("jev")
        stats.pop("handback_anomalies")
        rendered = render_stats(stats, width=80, color=False)

        self.assertIn("Attempt states: Unavailable", rendered)
        self.assertIn("Input token total: Unavailable", rendered)
        self.assertIn("Estimated Jev cost: Unavailable", rendered)
        self.assertIn("Recorded anomaly count: Unavailable", rendered)


if __name__ == "__main__":
    unittest.main()
