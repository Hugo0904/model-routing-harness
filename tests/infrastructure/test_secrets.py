import subprocess
import unittest
from types import SimpleNamespace

from mrh.infrastructure import secrets

KEY = "tsk_synthetic_test_value_00000000"


def fake_run(stored=None, calls=None):
    def run(argv, **kwargs):
        calls.append((argv, kwargs)) if calls is not None else None
        if "find-generic-password" in argv and "-w" in argv:
            return SimpleNamespace(returncode=0 if stored else 44, stdout=(stored or "") + "\n")
        return SimpleNamespace(returncode=0 if stored else 44, stdout="")
    return run


class SecretsTests(unittest.TestCase):
    def test_environment_wins_then_keychain_then_none(self):
        run = fake_run(KEY)
        self.assertEqual(secrets.credential_resolver("jev", {"TYPESAFE_API_KEY": "from-env"}, run)(), "from-env")
        self.assertEqual(secrets.credential_resolver("jev", {"TYPESAFE_API_KEY": ""}, run)(), KEY)
        self.assertIsNone(secrets.credential_resolver("jev", {}, fake_run(None))())

    def test_keychain_failure_modes_degrade_to_missing(self):
        def hangs(argv, **kw): raise subprocess.TimeoutExpired(argv, 5)     # blocked by an access prompt
        def absent(argv, **kw): raise FileNotFoundError(argv[0])
        self.assertIsNone(secrets.read("jev", hangs))
        self.assertIsNone(secrets.read("jev", absent))
        self.assertFalse(secrets.is_set("jev", hangs))

    def test_status_never_requests_the_value_and_store_never_carries_it(self):
        calls = []
        self.assertTrue(secrets.is_set("jev", fake_run(KEY, calls)))
        self.assertNotIn("-w", calls[0][0])
        calls.clear()
        secrets.store_interactively("jev", fake_run(KEY, calls))
        argv = calls[0][0]
        self.assertEqual(argv[-1], "-w")                                   # no value follows -w
        self.assertNotIn("capture_output", calls[0][1])                    # prompt stays on the terminal

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(secrets.SecretError):
            secrets.read("openai", fake_run(KEY))


if __name__ == "__main__":
    unittest.main()
