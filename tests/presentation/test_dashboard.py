import re
import unittest

from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import dashboard
from mrh.presentation.terminal import cell_width

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def settings():
    s = v2.default_settings()
    s["enabled"] = s["task_export_permitted"] = True
    s["policy"] = v2.validate({**s, "policy": {"threshold": 0.65, "tiers": {
        "Light": {"claude": [{"model": "haiku", "effort": "medium"}], "codex": [{"model": "gpt-5.6-luna", "effort": "low"}]},
        "Mid": {"claude": [{"model": "sonnet", "effort": "high"}]}}}})["policy"]
    return s


DATA = {"decisions": {"advise": 40, "continue_main": 3, "preserve": 22}, "per_platform": {"claude": {"advise": 40}},
        "kept_unchanged": {"named_role": 11, "explicit_model": 6, "low_confidence": 5}, "tiers": {"Light": 14, "Small": 14, "Mid": 17, "Top": 3},
        "classifier_usage": {"jev": {"calls": 48, "input_tokens": 21120, "output_tokens": 2160}}, "children_following_advice": 23,
        "followed_models": {"claude-haiku-5-5": 23}}
EMPTY = {"decisions": {}, "per_platform": {}, "kept_unchanged": {}, "tiers": {}, "classifier_usage": {}, "children_following_advice": 0, "followed_models": {}}


class DashboardTests(unittest.TestCase):
    def test_every_card_line_has_the_same_width_with_or_without_colour_at_each_size(self):
        for width in (80, 100, 120):
            for color in (False, True):
                for data in (DATA, EMPTY):
                    with self.subTest(width=width, color=color, empty=data is EMPTY):
                        text = dashboard.render(settings(), data, "過去 7 天", width, color, today="2026-10-13")
                        self.assertEqual(bool(ANSI.search(text)), color)
                        plain = ANSI.sub("", text)
                        card_lines = [l for l in plain.splitlines() if l[:1] in "│╭╰" and cell_width(l) > 40]
                        self.assertTrue(card_lines)
                        self.assertEqual({cell_width(l) for l in card_lines}, {width}, plain)

    def test_numbers_and_choices_appear(self):
        text = ANSI.sub("", dashboard.render(settings(), DATA, "過去 7 天", 110, True))
        for expected in ("haiku:medium", "sonnet:high", "0.10 / 0.50", "主模型自己做", "WHERE 65 DELEGATIONS WENT", "29%", "35%", "照 MRH 建議 23 / 40 次"):
            self.assertIn(expected, text)

    def test_empty_period_says_so_instead_of_drawing_empty_bars(self):
        self.assertIn("還沒有子代理委派", dashboard.render(settings(), EMPTY, "過去 24 小時", 100, False))


if __name__ == "__main__":
    unittest.main()
