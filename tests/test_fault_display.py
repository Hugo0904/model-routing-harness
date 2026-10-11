from __future__ import annotations

import copy
import unittest

from mrh.terminal import cell_width, render_stats, sanitize_text
from test_terminal_provider import provider_stats


def fault_stats() -> dict:
    stats = provider_stats()
    stats.update(
        proposals=15,
        routing_status={
            "classified_child_request": 6,
            "classified_main_request": 1,
            "normal_retention": 5,
            "fault_fallback": 2,
            "operator_stop": 1,
            "unavailable_readiness": 0,
        },
        notifications={
            "state": "active_fault",
            "active_sessions": 1,
            "fault_observations": 4,
            "warning_claims": 1,
            "recoveries": 0,
            "updated_at": "2026-10-11T04:30:00Z",
        },
    )
    return stats


def visible_words(rendered: str) -> str:
    return " ".join(sanitize_text(rendered).split())


class FaultDisplayTests(unittest.TestCase):
    def test_compact_footer_distinguishes_fault_proposals_from_normal_retention(self) -> None:
        stats = fault_stats()
        before = copy.deepcopy(stats)
        rendered = render_stats(stats, width=120, color=False)
        visible = visible_words(rendered)

        self.assertIn("Fault fallback proposals 2 / normal retention 5", visible)
        self.assertIn("Fault state: Active fault / active sessions 1", visible)
        self.assertIn("Fault observations 4 / warning claims 1 / recoveries 0", visible)
        self.assertIn("Recorded history does not prove activation or recovery; warning display unverified.", visible)
        self.assertIn("10 classified tasks", visible)
        self.assertIn("Light 5 (50.0%)", visible)
        self.assertEqual(stats, before)

    def test_details_explain_canonical_counts_replays_and_unverified_warning_display(self) -> None:
        stats = fault_stats()
        rendered = render_stats(stats, width=120, details=True)
        visible = visible_words(rendered)

        self.assertIn("ROUTING / NOTIFICATIONS", rendered)
        for item in (
            "Routing counts are mutually exclusive completed proposals.",
            "Classified child requests: 6",
            "Classified main requests: 1",
            "Normal retention: 5",
            "Fault fallback proposals: 2",
            "Operator stops: 1",
            "Unavailable readiness: 0",
            "Recorded notification state: Active fault",
            "Active fault sessions: 1",
            "Fault observations (includes replays): 4",
            "Warning emission claims: 1",
            "Recorded recoveries: 0",
            "Notification update: 2026-10-11T04:30:00Z",
            "Fault observations include Hook replays, distinct from classifier attempts and canonical proposals.",
            "Warning claims request emission; warning display is unverified.",
            "Recorded history does not prove current activation or recovery.",
        ):
            self.assertIn(item, visible)

    def test_zero_counts_and_historical_states_do_not_imply_health_or_activation(self) -> None:
        for state, label in (("unobserved", "Unobserved"), ("active_fault", "Active fault"),
                             ("recovered", "Recovered"), ("evaluated", "Unobserved"),
                             ("unknown\x1b[31m\u202ePRIVATE_STATE", "Unobserved"), ([], "Unobserved")):
            for details in (False, True):
                with self.subTest(state=state, details=details):
                    stats = fault_stats()
                    stats["routing_status"] = dict.fromkeys(stats["routing_status"], 0)
                    stats["notifications"].update(state=state, active_sessions=0, fault_observations=0,
                                                  warning_claims=0, recoveries=0)
                    visible = visible_words(render_stats(stats, width=120, details=details))
                    self.assertIn("state: " + label, visible)
                    self.assertIn("warning display", visible)
                    self.assertIn("unverified", visible)
                    self.assertNotIn("healthy", visible.casefold())
                    self.assertNotIn("PRIVATE_STATE", visible)

    def test_absent_notification_state_and_missing_counts_remain_unavailable(self) -> None:
        for notifications in (None, {}, {"fault_observations": 0}):
            for details in (False, True):
                with self.subTest(notifications=notifications, details=details):
                    stats = provider_stats()
                    if notifications is not None:
                        stats["notifications"] = notifications
                    visible = visible_words(render_stats(stats, width=120, details=details))
                    self.assertIn("state: Unavailable", visible)
                    self.assertIn("normal retention Unavailable" if not details else "Normal retention: Unavailable", visible)
                    self.assertNotIn("Recovered", visible)

    def test_narrow_and_wide_views_wrap_fault_data_without_crop_or_terminal_controls(self) -> None:
        stats = fault_stats()
        digits = "123456789012345678901234567890123456789012345678901234567890"
        observations = "觀測" * 40 + "observations-end"
        update = "update-" * 30 + "update-end"
        stats["routing_status"]["fault_fallback"] = int(digits)
        stats["notifications"]["fault_observations"] = "\x1b[31m" + observations + "\x1b[0m\n\x00\u202e"
        stats["notifications"]["updated_at"] = "\x1b[2J" + update + "\u202e"
        before = copy.deepcopy(stats)
        for details in (False, True):
            for width in ((28, 56, 120) if details else (56, 120)):
                for color in (False, True):
                    with self.subTest(width=width, color=color, details=details):
                        rendered = render_stats(stats, width=width, color=color, details=details)
                        self.assertTrue(all(cell_width(line) <= width for line in rendered.splitlines()))
                        compacted = "".join(sanitize_text(rendered).split())
                        self.assertIn(digits, compacted)
                        self.assertIn(observations, compacted)
                        if details:
                            self.assertIn(update, compacted)
                        self.assertNotIn("…", rendered)
                        self.assertNotIn("\x1b[31m", rendered)
                        self.assertNotIn("\x1b[2J", rendered)
                        for control in ("\x00", "\u202e"):
                            self.assertNotIn(control, rendered)
                        if color:
                            self.assertIn("\x1b[", rendered)
                        else:
                            self.assertNotIn("\x1b", rendered)
        self.assertEqual(stats, before)


if __name__ == "__main__":
    unittest.main()
