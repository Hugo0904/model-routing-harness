import unittest
from unittest.mock import patch

from mrh.advisory import main_cap, pricing
from mrh.advisory.main_cap import NOT_SMALLER, SMALLER, UNKNOWN, below_main, compare

LOW, SMALL, MID, HIGH = ({"model": "haiku", "effort": "medium"}, {"model": "sonnet", "effort": "medium"},
                         {"model": "sonnet", "effort": "xhigh"}, {"model": "opus", "effort": "high"})


class UserLadderTests(unittest.TestCase):
    """The user's Claude gear table, checked against the main models it actually runs under."""

    def test_opus_high_main_keeps_the_three_smaller_gears_and_drops_its_own_twin(self):
        main = ("claude-opus-5-5", "high")
        self.assertEqual([compare(c, main) for c in (LOW, SMALL, MID, HIGH)], [SMALLER, SMALLER, SMALLER, NOT_SMALLER])

    def test_opus_xhigh_main_still_takes_opus_high(self):
        self.assertEqual(compare(HIGH, ("claude-opus-5-5", "xhigh")), SMALLER)

    def test_a_main_model_without_a_listed_price_keeps_every_suggestion(self):
        main = ("claude-fable-5-2", "high")                 # not in the price table: no guess, the advice stays as it was
        self.assertEqual([compare(c, main) for c in (LOW, SMALL, MID, HIGH)], [UNKNOWN] * 4)
        self.assertEqual(below_main((LOW, SMALL, MID, HIGH), main), (LOW, SMALL, MID, HIGH))


class SameModelTests(unittest.TestCase):
    def test_same_model_compares_effort_only(self):
        main = ("claude-opus-5-5", "high")
        for effort, expected in (("low", SMALLER), ("medium", SMALLER), ("high", NOT_SMALLER), ("xhigh", NOT_SMALLER), ("max", NOT_SMALLER)):
            self.assertEqual(compare({"model": "opus", "effort": effort}, main), expected, effort)
            self.assertEqual(compare({"model": "claude-opus-5-5", "effort": effort}, main), expected, effort)

    def test_a_context_suffix_is_not_part_of_the_identity(self):
        self.assertEqual(compare({"model": "opus[1m]", "effort": "high"}, ("claude-opus-5-5[1m]", "high")), NOT_SMALLER)
        self.assertEqual(compare({"model": "claude-opus-5-5", "effort": "low"}, ("claude-opus-5-5[1m]", "high")), SMALLER)

    def test_without_a_known_effort_the_same_model_is_unknown(self):
        main = ("claude-opus-5-5", "high")
        self.assertEqual(compare({"model": "opus"}, main), UNKNOWN)
        self.assertEqual(compare({"model": "opus", "effort": "minimal"}, main), UNKNOWN)

    def test_names_only_match_exactly(self):
        main = ("claude-opus-5-5", "high")
        self.assertEqual(compare({"model": "opusplan", "effort": "high"}, main), UNKNOWN)     # not the opus family by substring
        self.assertEqual(compare({"model": "Opus", "effort": "high"}, main), UNKNOWN)
        self.assertEqual(compare({"model": "claude-opus-5-1", "effort": "high"}, main), UNKNOWN)   # another version, no price

    def test_a_main_id_of_another_shape_is_unknown(self):
        for main in (("opus", "high"), ("gpt-6.1-sol", "high"), ("claude-opus", "high"), ("claude-opus-5-5", "turbo")):
            self.assertEqual(compare(HIGH, main), UNKNOWN, main)


class PriceTests(unittest.TestCase):
    def test_other_models_compare_by_official_input_and_output_price(self):
        main = ("claude-sonnet-5-5", "low")
        self.assertEqual(compare({"model": "opus", "effort": "low"}, main), NOT_SMALLER)       # effort plays no part across models
        self.assertEqual(compare({"model": "claude-haiku-5-5", "effort": "max"}, main), SMALLER)
        self.assertEqual(compare({"model": "fable", "effort": "low"}, ("claude-opus-5-5", "max")), NOT_SMALLER)  # one fable entry listed

    def test_an_alias_needs_exactly_one_listed_family_member(self):
        two = {**pricing.PRICES, "claude-haiku-5-6": pricing.PRICES["claude-haiku-5-5"]}
        with patch.object(pricing, "PRICES", two):
            self.assertEqual(compare(LOW, ("claude-opus-5-5", "high")), UNKNOWN)
            self.assertEqual(compare({"model": "claude-haiku-5-6", "effort": "low"}, ("claude-opus-5-5", "high")), SMALLER)

    def test_prices_that_point_both_ways_are_unknown(self):
        odd = {**pricing.PRICES, "claude-mixed-1": {"source": "synthetic", "small": {"input": 5, "output": 1}}}
        with patch.object(pricing, "PRICES", odd):
            self.assertEqual(compare({"model": "claude-mixed-1", "effort": "low"}, ("claude-opus-5-5", "high")), UNKNOWN)
        equal = {**pricing.PRICES, "claude-twin-1": pricing.PRICES["claude-opus-5-5"]}
        with patch.object(pricing, "PRICES", equal):
            self.assertEqual(compare({"model": "claude-twin-1", "effort": "low"}, ("claude-opus-5-5", "high")), NOT_SMALLER)

    def test_non_claude_or_unpriced_candidates_are_unknown(self):
        main = ("claude-opus-5-5", "high")
        for model in ("gpt-6-astra", "claude-fable-5-2", "local-model", "fable-5"):
            self.assertEqual(compare({"model": model, "effort": "high"}, main), UNKNOWN, model)

    def test_filtering_keeps_order_and_unknowns(self):
        candidates = ({"model": "opus", "effort": "max"}, MID, {"model": "opus"}, LOW, HIGH)
        self.assertEqual(below_main(candidates, ("claude-opus-5-5", "high")), (MID, {"model": "opus"}, LOW))
        self.assertEqual(below_main((HIGH,), ("claude-opus-5-5", "high")), ())

    def test_the_price_table_is_loaded_only_when_comparing(self):
        self.assertNotIn("pricing", vars(main_cap))


if __name__ == "__main__":
    unittest.main()
