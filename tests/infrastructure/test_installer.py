from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import mrh.infrastructure.installer as installer
from mrh.infrastructure.installer import SyntheticHome, apply as apply_public, prepare


_MANAGED = "MRH_INSTALLER_ID=org.model-routing-harness.hooks.v1"


def write_hooks(home: Path, value: object) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    (home / "hooks.json").write_bytes(data)
    return data


def read_hooks(home: Path) -> dict:
    return json.loads((home / "hooks.json").read_text())


class InstallerTests(unittest.TestCase):
    command = "/opt/model routing/mrh"

    def test_preview_is_read_only_and_explains_public_mutation_boundary(self) -> None:
        with SyntheticHome() as fixture:
            hooks_bytes = write_hooks(fixture.home, {
                "hooks": {
                    "PreToolUse": [{
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": "private-existing-command --secret"}],
                    }],
                },
            })
            config_bytes = (
                b'model = "main-model"\nmodel_reasoning_effort = "high"\n'
                b'approval_policy = "never"\ntrusted = true\n'
            )
            (fixture.home / "config.toml").write_bytes(config_bytes)
            before_names = {p.name for p in fixture.home.iterdir()}

            plan = prepare(fixture.home, self.command)
            preview = json.dumps(plan.public())

            self.assertEqual(plan.status, "ready")
            self.assertTrue(plan.public()["candidate_change"])
            self.assertFalse(plan.public()["will_write"])
            self.assertFalse(plan.public()["mutation_supported"])
            self.assertEqual(plan.public()["mutation_reason"], "exclusive_target_unverified")
            self.assertNotIn("private-existing-command", preview)
            self.assertNotIn("--secret", preview)
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), hooks_bytes)
            self.assertEqual((fixture.home / "config.toml").read_bytes(), config_bytes)
            self.assertEqual({p.name for p in fixture.home.iterdir()}, before_names)

    def test_public_apply_and_disable_refuse_without_reaching_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "existing-home"
            home.mkdir()
            original = write_hooks(home, {
                "hooks": {
                    "PreToolUse": [{
                        "matcher": "^spawn_agent$",
                        "hooks": [{"type": "command", "command": _MANAGED + " /old/mrh hook --candidate"}],
                    }],
                    "PostToolUse": [{
                        "matcher": "^spawn_agent$",
                        "hooks": [{"type": "command", "command": _MANAGED + " /old/mrh hook --candidate"}],
                    }],
                },
            })
            config_bytes = b'model = "main-model"\nmodel_reasoning_effort = "high"\ntrusted = true\n'
            (home / "config.toml").write_bytes(config_bytes)
            before_names = {p.name for p in home.iterdir()}
            plans = (
                prepare(home, self.command, action="apply"),
                prepare(home, "", action="disable"),
            )
            self.assertTrue(all(plan.candidate_change for plan in plans))

            with patch("mrh.infrastructure.installer._write_atomically") as write_atomic, patch("mrh.infrastructure.installer.os.replace") as replace:
                results = [apply_public(plan) for plan in plans]

            self.assertEqual(
                results,
                [
                    {"ok": False, "status": "refused", "reason": "exclusive_target_unverified", "changed": False},
                    {"ok": False, "status": "refused", "reason": "exclusive_target_unverified", "changed": False},
                ],
            )
            write_atomic.assert_not_called()
            replace.assert_not_called()
            self.assertEqual((home / "hooks.json").read_bytes(), original)
            self.assertEqual((home / "config.toml").read_bytes(), config_bytes)
            self.assertEqual({p.name for p in home.iterdir()}, before_names)

    def test_fixture_rejects_a_plan_for_any_other_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp, SyntheticHome() as fixture:
            outside = Path(temp) / "other-home"
            outside.mkdir()
            original = write_hooks(outside, {"hooks": {}})
            plan = prepare(outside, self.command)

            result = fixture.apply(plan)

            self.assertEqual(result["reason"], "fixture_target_mismatch")
            self.assertEqual((outside / "hooks.json").read_bytes(), original)
            self.assertFalse((fixture.home / "hooks.json").exists())

    def test_apply_is_idempotent_and_preserves_other_entries_and_config_bytes(self) -> None:
        with SyntheticHome() as fixture:
            unrelated_pre = {
                "matcher": "^other_tool$",
                "hooks": [{"type": "command", "command": "other-plugin --keep"}],
            }
            original = write_hooks(fixture.home, {
                "extra": {"keep": True},
                "hooks": {
                    "PreToolUse": [unrelated_pre],
                    "SessionStart": [{"matcher": "*", "hooks": [{"command": "untouched"}]}],
                },
            })
            config_bytes = b'model = "main-model"\nmodel_reasoning_effort = "high"\ntrusted = true\n'
            (fixture.home / "config.toml").write_bytes(config_bytes)

            first = fixture.apply(prepare(fixture.home, self.command))
            first_bytes = (fixture.home / "hooks.json").read_bytes()
            after_first = read_hooks(fixture.home)
            self.assertTrue(first["ok"])
            self.assertTrue(first["changed"])
            self.assertEqual(after_first["extra"], {"keep": True})
            self.assertEqual(after_first["hooks"]["PreToolUse"][0], unrelated_pre)
            self.assertEqual(after_first["hooks"]["SessionStart"], [{"matcher": "*", "hooks": [{"command": "untouched"}]}])
            self.assertEqual(len(after_first["hooks"]["PreToolUse"]), 2)
            self.assertEqual(len(after_first["hooks"]["PostToolUse"]), 1)
            self.assertEqual((fixture.home / "config.toml").read_bytes(), config_bytes)
            self.assertNotEqual(first_bytes, original)

            second = fixture.apply(prepare(fixture.home, self.command))
            self.assertTrue(second["ok"])
            self.assertFalse(second["changed"])
            self.assertEqual(second["status"], "already_installed")
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), first_bytes)

    def test_disable_removes_only_owned_entries_and_keeps_later_edits(self) -> None:
        with SyntheticHome() as fixture:
            original_pre = {"matcher": "*", "hooks": [{"type": "command", "command": "later-plugin"}]}
            write_hooks(fixture.home, {"hooks": {"PreToolUse": [original_pre]}})
            config_bytes = b'model = "main-model"\nmodel_reasoning_effort = "high"\napproval_policy = "never"\n'
            (fixture.home / "config.toml").write_bytes(config_bytes)
            self.assertTrue(fixture.apply(prepare(fixture.home, self.command))["ok"])

            # This unrelated edit happens after installation and before a new disable preview.
            current = read_hooks(fixture.home)
            later = {"matcher": "^later_tool$", "hooks": [{"type": "command", "command": "later-edit"}]}
            current["hooks"]["PreToolUse"].append(later)
            current["hooks"]["FutureEvent"] = [{"command": "preserve-future"}]
            (fixture.home / "hooks.json").write_text(json.dumps(current, indent=2) + "\n")

            result = fixture.apply(prepare(fixture.home, "", action="disable"))
            final = read_hooks(fixture.home)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "disabled")
            self.assertEqual(final["hooks"]["PreToolUse"], [original_pre, later])
            self.assertEqual(final["hooks"]["PostToolUse"], [])
            self.assertEqual(final["hooks"]["FutureEvent"], [{"command": "preserve-future"}])
            self.assertEqual((fixture.home / "config.toml").read_bytes(), config_bytes)

            again = fixture.apply(prepare(fixture.home, "", action="disable"))
            self.assertTrue(again["ok"])
            self.assertFalse(again["changed"])
            self.assertEqual(again["status"], "not_installed")

    def test_fixture_does_not_claim_an_unmarked_matching_hook(self) -> None:
        with SyntheticHome() as fixture:
            unmarked = {
                "matcher": "^spawn_agent$",
                "hooks": [{"type": "command", "command": self.command + " hook --candidate"}],
            }
            write_hooks(fixture.home, {"hooks": {"PreToolUse": [unmarked]}})
            self.assertTrue(fixture.apply(prepare(fixture.home, self.command))["ok"])
            disabled = fixture.apply(prepare(fixture.home, "", action="disable"))
            self.assertTrue(disabled["ok"])
            self.assertEqual(read_hooks(fixture.home)["hooks"]["PreToolUse"], [unmarked])

    def test_toml_hooks_are_refused_without_any_fixture_write(self) -> None:
        with SyntheticHome() as fixture:
            hooks_bytes = write_hooks(fixture.home, {"hooks": {}})
            config_bytes = b'model = "main"\n[hooks.PreToolUse]\n'
            (fixture.home / "config.toml").write_bytes(config_bytes)

            plan = prepare(fixture.home, self.command)
            self.assertEqual(plan.status, "refused")
            self.assertEqual(plan.reason, "toml_hooks_present")
            result = fixture.apply(plan)
            self.assertFalse(result["ok"])
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), hooks_bytes)
            self.assertEqual((fixture.home / "config.toml").read_bytes(), config_bytes)

    def test_invalid_json_and_duplicate_keys_are_refused(self) -> None:
        with SyntheticHome() as fixture:
            target = fixture.home / "hooks.json"
            for data in (b"{not json", b'{"hooks": {}, "hooks": {}}'):
                target.write_bytes(data)
                plan = prepare(fixture.home, self.command)
                self.assertEqual(plan.status, "refused")
                self.assertEqual(plan.reason, "invalid_hooks_json")
                result = fixture.apply(plan)
                self.assertFalse(result["ok"])
                self.assertEqual(target.read_bytes(), data)

    def test_symlink_targets_are_refused(self) -> None:
        with SyntheticHome() as fixture:
            target = fixture.home / "hooks.json"
            outside = fixture.home.parent / "outside.json"
            outside.write_text('{"hooks": {}}')
            target.symlink_to(outside)
            plan = prepare(fixture.home, self.command)
            self.assertEqual(plan.reason, "symlink_target")
            self.assertFalse(fixture.apply(plan)["ok"])
            self.assertEqual(outside.read_text(), '{"hooks": {}}')

            target.unlink()
            config = fixture.home / "config.toml"
            outside_config = fixture.home.parent / "outside.toml"
            outside_config.write_text('model = "safe"\n')
            config.symlink_to(outside_config)
            self.assertEqual(prepare(fixture.home, self.command).reason, "symlink_target")
            self.assertEqual(outside_config.read_text(), 'model = "safe"\n')

    def test_source_hash_change_after_preview_is_refused(self) -> None:
        with SyntheticHome() as fixture:
            write_hooks(fixture.home, {"hooks": {}})
            plan = prepare(fixture.home, self.command)
            changed = read_hooks(fixture.home)
            changed["hooks"]["UserEvent"] = [{"command": "concurrent-edit"}]
            target = fixture.home / "hooks.json"
            concurrent_bytes = (json.dumps(changed, indent=2) + "\n").encode()
            target.write_bytes(concurrent_bytes)

            result = fixture.apply(plan)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "source_changed")
            self.assertEqual(target.read_bytes(), concurrent_bytes)

    def test_malformed_owned_marker_is_ambiguous_and_left_untouched(self) -> None:
        with SyntheticHome() as fixture:
            malformed = {
                "matcher": "^spawn_agent$",
                "extra": "do not claim",
                "hooks": [{
                    "type": "command",
                    "command": _MANAGED + " /old/mrh hook --candidate",
                }],
            }
            original = write_hooks(fixture.home, {"hooks": {"PreToolUse": [malformed]}})
            plan = prepare(fixture.home, self.command)
            self.assertEqual(plan.status, "refused")
            self.assertEqual(plan.reason, "ambiguous_managed_entry")
            result = fixture.apply(plan)
            self.assertFalse(result["ok"])
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), original)

    def test_config_change_after_preview_is_refused(self) -> None:
        with SyntheticHome() as fixture:
            write_hooks(fixture.home, {"hooks": {}})
            config = fixture.home / "config.toml"
            config.write_text('model = "main"\n')
            plan = prepare(fixture.home, self.command)
            changed = b'model = "main"\n[hooks]\n'
            config.write_bytes(changed)

            result = fixture.apply(plan)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "source_changed")
            self.assertEqual(config.read_bytes(), changed)
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), b'{\n  "hooks": {}\n}\n')

    def test_invalid_toml_is_refused(self) -> None:
        with SyntheticHome() as fixture:
            hooks_bytes = write_hooks(fixture.home, {"hooks": {}})
            config_bytes = b'model = "unterminated\n'
            (fixture.home / "config.toml").write_bytes(config_bytes)
            plan = prepare(fixture.home, self.command)
            self.assertEqual(plan.status, "refused")
            self.assertEqual(plan.reason, "invalid_config_toml")
            self.assertEqual((fixture.home / "hooks.json").read_bytes(), hooks_bytes)
            self.assertEqual((fixture.home / "config.toml").read_bytes(), config_bytes)

    def test_cooperating_writers_serialize_and_stale_plan_cannot_overwrite(self) -> None:
        with SyntheticHome() as fixture:
            write_hooks(fixture.home, {"hooks": {}})
            plans = (
                prepare(fixture.home, "/mrh/first"),
                prepare(fixture.home, "/mrh/second"),
            )
            barrier = threading.Barrier(3)
            results: list[dict | None] = [None, None]

            def apply_in_thread(index: int) -> None:
                barrier.wait(timeout=2)
                results[index] = fixture.apply(plans[index])

            workers = [threading.Thread(target=apply_in_thread, args=(i,)) for i in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=2)
            for worker in workers:
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())

            completed = [result for result in results if result is not None]
            self.assertEqual(sum(result["ok"] for result in completed), 1)
            refused = [result for result in completed if not result["ok"]]
            self.assertEqual(len(refused), 1)
            self.assertEqual(refused[0]["reason"], "source_changed")
            final = read_hooks(fixture.home)["hooks"]
            self.assertEqual(len(final["PreToolUse"]), 1)
            self.assertEqual(len(final["PostToolUse"]), 1)
            successful_index = next(i for i, result in enumerate(results) if result is not None and result["ok"])
            expected_command = _MANAGED + (" /mrh/first" if successful_index == 0 else " /mrh/second") + " hook --candidate"
            self.assertEqual(final["PreToolUse"][0]["hooks"][0]["command"], expected_command)
            self.assertEqual(final["PostToolUse"][0]["hooks"][0]["command"], expected_command)

    def test_noncooperating_edit_after_hash_check_remains_a_known_race(self) -> None:
        with SyntheticHome() as fixture:
            write_hooks(fixture.home, {"hooks": {}})
            plan = prepare(fixture.home, self.command)
            real_write_atomically = installer._write_atomically

            def inject_external_edit(path: Path, data: bytes, mode: int | None) -> None:
                # This controlled non-cooperating editor runs after the last
                # source hash check and does not take SyntheticHome's lock.
                current = json.loads(path.read_text())
                current["hooks"]["EditorEvent"] = [{"command": "external-late-edit"}]
                path.write_text(json.dumps(current, indent=2) + "\n")
                real_write_atomically(path, data, mode)

            with patch.object(installer, "_write_atomically", side_effect=inject_external_edit):
                result = fixture.apply(plan)

            self.assertTrue(result["ok"])
            self.assertNotIn("EditorEvent", read_hooks(fixture.home)["hooks"])

    def test_fixture_cannot_apply_after_its_scope_closes(self) -> None:
        fixture = SyntheticHome()
        plan = prepare(fixture.home, self.command)
        fixture.close()
        result = fixture.apply(plan)
        self.assertEqual(result["reason"], "fixture_inactive")


if __name__ == "__main__":
    unittest.main()
