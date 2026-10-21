import unittest

from mrh.advisory import pricing as p
from mrh.advisory.usage_collect import MIXED

M = 1_000_000


def entry(inp=0, w5=0, w1=0, write=0, read=0, out=None, large=None, max_request=1000):
    e = {"requests": 1, "output": out, "reasoning": None,
         "small": {"input": inp, "cache_write_5m": w5, "cache_write_1h": w1, "cache_write": write, "cache_read": read},
         "large": {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0, "cache_read": 0, **(large or {})}}
    if max_request is not None:
        e["max_request_input"] = max_request
    return e


class PriceTableTests(unittest.TestCase):
    def test_every_price_is_the_published_one_with_a_source_and_a_date(self):
        # Claude page, 2026-10-16. Sonnet 5.5 cache reads are $0.10 there (an SDK doc said $0.20: the pricing page wins).
        expected = {"claude-opus-5-5": (4, 5, 8, 0.20, 20), "claude-sonnet-5-5": (2, 2.5, 4, 0.10, 10), "claude-fable-5-1": (10, 12.5, 20, 0.25, 50)}
        for model, (inp, w5, w1, read, out) in expected.items():
            row = p.PRICES[model]["small"]
            self.assertEqual((row["input"], row["cache_write_5m"], row["cache_write_1h"], row["cache_read"], row["output"]), (inp, w5, w1, read, out), model)
            self.assertEqual(p.PRICES[model]["source"], p.CLAUDE_URL)
        haiku = p.PRICES["claude-haiku-5-5"]
        self.assertEqual((haiku["small"]["input"], haiku["small"]["cache_read"], haiku["small"]["output"]), (0.10, 0.01, 0.50))
        self.assertEqual((haiku["large"]["input"], haiku["large"]["cache_read"], haiku["large"]["output"]), (0.50, 0.05, 2.50))
        for model, (inp, read, write, out) in {"gpt-6-luna": (0.10, 0.01, 0.125, 0.50), "gpt-6.1-sol": (2, 0.10, 2.5, 10), "gpt-6-astra": (10, 1, 12.5, 50)}.items():
            row = p.PRICES[model]["small"]
            self.assertEqual((row["input"], row["cache_read"], row["cache_write"], row["output"]), (inp, read, write, out), model)
            self.assertEqual(p.PRICES[model]["source"], p.OPENAI_URL)
        self.assertRegex(p.CHECKED, r"^\d{4}-\d{2}-\d{2}$")

    def test_a_context_suffix_is_not_part_of_the_identity_and_unknown_models_are_unknown(self):
        self.assertTrue(p.known("claude-opus-5-5[1m]")); self.assertFalse(p.known("claude-haiku-4-5-20251001")); self.assertFalse(p.known(None))


class ChildCostTests(unittest.TestCase):
    def test_each_token_kind_uses_its_own_rate(self):
        cost = p.price_entry("claude-sonnet-5-5", entry(inp=M, w5=M, w1=M, read=M))
        self.assertAlmostEqual(cost["input_side"], 2 + 2.5 + 4 + 0.10)

    def test_haiku_large_prompts_pay_the_higher_tier_per_request(self):
        cost = p.price_entry("claude-haiku-5-5", entry(inp=M, read=M, large={"input": M, "cache_read": M}))
        self.assertAlmostEqual(cost["input_side"], 0.10 + 0.01 + 0.50 + 0.05)

    def test_zero_is_zero_but_a_missing_price_with_tokens_is_unknown_not_zero(self):
        self.assertEqual(p.price_entry("claude-opus-5-5", entry(write=0))["input_side"], 0.0)        # no tokens: nothing to price
        unpriced = p.price_entry("claude-opus-5-5", entry(inp=M, write=500))                         # cache write with no TTL split
        self.assertIsNone(unpriced["input_side"]); self.assertTrue(any("cache_write" in r for r in unpriced["unknown"]))
        self.assertIsNone(p.price_entry("claude-haiku-4-5-20251001", entry(inp=5))["input_side"])
        self.assertIsNone(p.price_entry(MIXED, entry(inp=5))["input_side"])

    def test_claude_output_is_never_priced_and_the_total_stays_unknown(self):
        cost = p.price_child({"claude-haiku-5-5": entry(inp=M)})
        self.assertAlmostEqual(cost["input_side"], 0.10); self.assertIsNone(cost["output"]); self.assertIsNone(cost["total"])
        self.assertTrue(any("輸出 token 未知" in r for r in cost["unknown"]))

    def test_codex_prices_input_cached_and_output_and_a_long_context_request_is_unknown(self):
        cost = p.price_child({"gpt-6.1-sol": entry(inp=M, read=M, write=M, out=M)})
        self.assertAlmostEqual(cost["total"], 2 + 0.10 + 2.5 + 10)
        long = p.price_child({"gpt-6.1-sol": entry(inp=M, out=10, max_request=300_000)})
        self.assertIsNone(long["total"]); self.assertIn("長上下文", long["unknown"][0])
        self.assertIsNotNone(p.price_child({"gpt-6.1-sol": entry(inp=M, out=10, max_request=272_000)})["total"])     # at the limit is still short context


class SavingTests(unittest.TestCase):
    def test_claude_saving_is_the_input_side_difference_and_says_so(self):
        result = p.saving({"claude-haiku-5-5": entry(inp=M, read=M)}, "claude-opus-5-5")
        self.assertAlmostEqual(result["usd"], (4 + 0.20) - (0.10 + 0.01)); self.assertEqual(result["scope"], "輸入端")

    def test_codex_saving_includes_the_exact_output(self):
        result = p.saving({"gpt-6-luna": entry(inp=M, out=M)}, "gpt-6.1-sol")
        self.assertAlmostEqual(result["usd"], (2 + 10) - (0.10 + 0.50)); self.assertEqual(result["scope"], "輸入＋輸出")

    def test_the_sign_is_kept_when_the_sub_agent_cost_more_and_the_same_model_saves_nothing(self):
        self.assertLess(p.saving({"claude-opus-5-5": entry(inp=M)}, "claude-haiku-5-5")["usd"], 0)
        self.assertAlmostEqual(p.saving({"claude-sonnet-5-5": entry(inp=M)}, "claude-sonnet-5-5")["usd"], 0)

    def test_unknown_parent_or_prices_or_platform_give_a_reason_never_a_number(self):
        usage = {"claude-haiku-5-5": entry(inp=M)}
        for parent, fragment in ((None, "不知道主模型"), ("claude-haiku-4-5-20251001", "沒有官方價格"), ("gpt-6.1-sol", "不是同一個平台")):
            result = p.saving(usage, parent)
            self.assertIsNone(result["usd"]); self.assertIn(fragment, result["reason"])
        self.assertIsNone(p.saving({"claude-opus-5-5": entry(inp=M, write=10)}, "claude-fable-5-1")["usd"])   # an unpriced write blocks it
        self.assertIsNone(p.saving({MIXED: entry(inp=M, out=5)}, "gpt-6.1-sol")["usd"])


class UnknownValidityTests(unittest.TestCase):
    def test_unknown_request_length_blocks_all_tier_dependent_money(self):
        usage = {"gpt-6-luna": entry(inp=M, out=M, max_request=None)}
        self.assertIsNone(p.price_child(usage)["total"])
        self.assertIn("長度未知", p.price_child(usage)["unknown"][0])
        self.assertIsNone(p.saving(usage, "gpt-6.1-sol")["usd"])

    def test_missing_invalid_components_are_not_free_and_empty_is_unknown(self):
        for invalid in (None, True, -1, "0"):
            e = entry(inp=0); e["small"]["input"] = invalid
            self.assertIsNone(p.price_entry("claude-haiku-5-5", e)["input_side"])
        e = entry(inp=0); e["large"].pop("cache_read")
        self.assertIsNone(p.price_entry("claude-haiku-5-5", e)["input_side"])
        self.assertIsNone(p.price_child({})["total"])


if __name__ == "__main__":
    unittest.main()
