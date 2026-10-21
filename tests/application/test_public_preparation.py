"""Public preparation contracts: fake homes, local bytes, no real CLI or model."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mrh.application import skills
from mrh.infrastructure import temporary
from mrh.presentation import cli, ctrl
from mrh.application.ctrl_logic import CtrlError
from mrh.adapters.providers import typesafe_models


class PublicPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mrh-public-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = patch.dict(os.environ, MRH_PROJECT_ROOT=str(self.root))
        env.start(); self.addCleanup(env.stop)

    def test_both_skills_install_idempotently_and_only_remove_unchanged_owned_content(self):
        for host in ('codex', 'claude'):
            base = self.root / host
            base.mkdir(); foreign = base / 'other-skill'; foreign.mkdir()
            (foreign / 'SKILL.md').write_bytes(b'other operator')
            self.assertEqual(skills.status(host, base)['status'], 'not_installed')
            installed = skills.run('install', host, base)
            target = Path(installed['path']); stamp = (target / 'SKILL.md').stat().st_mtime_ns
            self.assertEqual(installed['status'], 'latest')
            self.assertFalse(skills.run('install', host, base)['changed'])
            self.assertEqual((target / 'SKILL.md').stat().st_mtime_ns, stamp)
            with patch.object(skills, 'payload', return_value=b'new release'):
                self.assertEqual(skills.status(host, base)['status'], 'outdated')
                with self.assertRaises(ValueError):skills.run('install', host, base)
            (target / 'SKILL.md').write_bytes(b'local customization')
            self.assertEqual(skills.status(host, base)['status'], 'modified')
            with self.assertRaises(ValueError):skills.run('remove', host, base)
            (target / 'SKILL.md').write_bytes(skills.payload(host))
            self.assertEqual(skills.run('remove', host, base)['status'], 'not_installed')
            self.assertEqual((foreign / 'SKILL.md').read_bytes(), b'other operator')
            target.mkdir(); (target / 'SKILL.md').write_bytes(b'foreign content')
            with self.assertRaises(ValueError):skills.run('install', host, base)
            with self.assertRaises(ValueError):skills.run('remove', host, base)

    def test_unsupported_skill_platform_is_a_chinese_exit_two(self):
        error = io.StringIO()
        self.assertEqual(cli.main(['skill', 'install', '--host', 'gemini'], stderr=error), 2)
        self.assertIn('尚未支援', error.getvalue())

    def test_a_forged_local_marker_does_not_make_modified_content_removable(self):
        import hashlib
        installed = skills.run('install', 'codex', self.root / 'skills')
        target = Path(installed['path'])
        changed = b'user customization, not a known MRH release'
        (target / 'SKILL.md').write_bytes(changed)
        marker = target / skills.MARKER
        meta = json.loads(marker.read_text()); meta['sha256'] = hashlib.sha256(changed).hexdigest()
        marker.write_text(json.dumps(meta))
        self.assertEqual(skills.status('codex', self.root / 'skills')['status'], 'unmanaged')
        with self.assertRaises(ValueError):skills.run('remove', 'codex', self.root / 'skills')
        self.assertEqual((target / 'SKILL.md').read_bytes(), changed)

    def test_installed_generation_root_wins_over_caller_environment(self):
        generation = self.root / 'generation'; generation.mkdir()
        bound = self.root / 'bound-project'; bound.mkdir()
        (generation / 'generation.json').write_text(json.dumps({'project_root': str(bound)}))
        file = generation / 'app/mrh.pyz/mrh/infrastructure/temporary.py'
        with patch.object(temporary, '__file__', str(file)):
            self.assertEqual(temporary.project_root(), bound)

    def test_linked_runtime_ancestor_is_rejected_before_creating_outside_directories(self):
        project = self.root / 'project'; project.mkdir()
        external = self.root / 'outside'; external.mkdir()
        try:(project / 'runtime').symlink_to(external, target_is_directory=True)
        except OSError:self.skipTest('host cannot create an unprivileged symlink')
        with patch.dict(os.environ, MRH_PROJECT_ROOT=str(project)):
            with self.assertRaises(ValueError):temporary.area()
        self.assertEqual(list(external.iterdir()), [])

    def test_atomic_publish_failure_preserves_target_and_removes_target_side_intermediate(self):
        import errno
        from mrh.infrastructure import claude_hook, owned
        target = self.root / 'settings.json'
        original = b'{"keep":"original"}\n'
        target.write_bytes(original); target.chmod(0o600)
        for writer in (lambda: owned.replace_owned(target, b'new bytes'),
                       lambda: claude_hook.apply(target, '{"keep":"updated"}\n')):
            with self.subTest(writer=writer), patch('os.replace', side_effect=OSError(errno.EXDEV, 'synthetic rename refusal')) as replace:
                with self.assertRaises(OSError):writer()
                self.assertEqual(Path(replace.call_args.args[0]).parent, target.parent)
                self.assertEqual(Path(replace.call_args.args[1]), target)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(target.parent.glob('.mrh-write-*')), [])

    def test_reset_is_disposable_only_and_cache_rebuilds_without_a_model(self):
        protected = ['profile/settings.json', 'profile/advice.sqlite3', 'experiments/spool/request.json',
                     'reports/report.html', 'setup-state/journal.json', 'receipts/receipt.json']
        for name in protected:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode())
        with temporary.directory(prefix='classification-') as work:
            (Path(work) / 'body.txt').write_bytes(b'synthetic task')
            cache = typesafe_models.cache_path()
            models = [{'name': 'jev-latest', 'description': '', 'release_date': ''}]
            typesafe_models.known_models(cache, 100, fetcher=lambda: models)
            self.assertTrue(cache.is_file())
            self.assertGreater(temporary.cleanup()['files'], 0)
            self.assertTrue(cache.is_file())
            result = temporary.cleanup(apply=True)
            self.assertGreater(result['files'], 0)
            self.assertFalse(Path(work).exists()); self.assertFalse(cache.exists())
        for name in protected:self.assertEqual((self.root / name).read_bytes(), name.encode())
        self.assertEqual(typesafe_models.known_models(typesafe_models.cache_path(), 101, fetcher=lambda: models)[0], models)
        self.assertTrue(cache.is_file())
        temporary.cleanup(apply=True)
        self.assertEqual(temporary.cleanup(apply=True)['files'], 0)

    def test_cleanup_cli_preview_apply_and_menu_action_do_not_require_settings_or_confirmation(self):
        body = temporary.area() / 'synthetic-brief.txt'; body.write_bytes(b'brief')
        output = io.StringIO()
        self.assertEqual(cli.main(['cleanup'], stdout=output, stderr=io.StringIO()), 0)
        self.assertFalse(json.loads(output.getvalue())['applied']); self.assertTrue(body.exists())
        output = io.StringIO()
        self.assertEqual(cli.main(['cleanup', '--apply'], stdout=output, stderr=io.StringIO()), 0)
        self.assertTrue(json.loads(output.getvalue())['applied']); self.assertFalse(body.exists())
        body.write_bytes(b'next synthetic brief')
        notes = []
        class Menu:
            def note(self, message):notes.append(message)
            def pick(self, *args, **kwargs):raise AssertionError('Reset must not ask for a second confirmation')
        ctrl.Session(None, Menu(), io.StringIO()).cleanup()
        self.assertFalse(body.exists()); self.assertIn('統計與實驗資料不變', notes[0])

    def test_reset_does_not_follow_external_links_and_root_does_not_follow_cwd(self):
        external = self.root / 'keep.txt'; external.write_bytes(b'keep')
        base = temporary.area()
        try:(base / 'link').symlink_to(external)
        except OSError:self.skipTest('host cannot create an unprivileged symlink')
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        original = Path.cwd()
        try:
            os.chdir(elsewhere)
            self.assertEqual(temporary.project_root(), self.root)
            self.assertTrue(temporary.cleanup(apply=True)['skipped'])
        finally:os.chdir(original)
        self.assertEqual(external.read_bytes(), b'keep')
        with patch.dict(os.environ, MRH_PROJECT_ROOT=str(self.root / 'missing')):
            with self.assertRaises(ValueError):temporary.directory()

    @unittest.skipIf(os.name == 'nt', 'Mac packet/manual-catalog contract; Windows remains unsupported')
    def test_reset_keeps_unknown_release_identity_and_next_new_packet_can_classify(self):
        from tests.application.test_codex_packets import PacketTests
        from mrh.adapters.hosts import codex_packets
        fixture = PacketTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        first = fixture.prep(); fixture.run_hook(fixture.event(first))
        fixture.run_hook(fixture.event(first, True))
        receipt_path = codex_packets._directory(fixture.settings, first['packet_id']) / 'receipt.json'
        before = receipt_path.read_bytes()
        database = fixture.settings.parent / 'advice.sqlite3'
        from contextlib import closing
        from mrh.advisory.store import AdviceStore
        with closing(AdviceStore(database).connect()) as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        facts = database.read_bytes()
        temporary.cleanup(apply=True)
        self.assertEqual(receipt_path.read_bytes(), before)
        self.assertEqual(database.read_bytes(), facts)
        self.assertIn('outcome_unknown', fixture.reason(fixture.run_hook(fixture.event(first, True))))
        self.assertEqual(fixture.fake.calls, 1)
        fresh = fixture.prep(); fixture.run_hook(fixture.event(fresh))
        self.assertEqual(fixture.fake.calls, 2)

    @unittest.skipIf(os.name == 'nt', 'Mac packet/manual-catalog contract; Windows remains unsupported')
    def test_reset_during_classification_fails_current_packet_without_requery(self):
        from tests.application.test_codex_packets import PacketTests
        fixture = PacketTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        packet = fixture.prep()
        original = fixture.fake.classify
        def classify(*args):
            temporary.cleanup(apply=True)
            return original(*args)
        fixture.fake.classify = classify
        self.assertIn('body_removed', fixture.reason(fixture.run_hook(fixture.event(packet))))
        fixture.run_hook(fixture.event(packet)); fixture.run_hook(fixture.event(packet, True))
        self.assertEqual(fixture.fake.calls, 1)

    def test_busy_cache_is_skipped_and_new_entries_are_not_deleted(self):
        from mrh.infrastructure import owned
        root = temporary.area('cache')
        (root / 'asset').write_bytes(b'in use')
        with owned.locked(root, 'disposable_cache'):
            result = temporary.cleanup(apply=True)
            self.assertIn({'name': 'cache', 'reason': 'in_use'}, result['skipped'])
            self.assertTrue((root / 'asset').exists())
        original = temporary._inventory
        def inventory(path):
            if path.name == 'asset':(root / 'new').write_bytes(b'new operation')
            return original(path)
        with patch.object(temporary, '_inventory', side_effect=inventory):temporary.cleanup(apply=True)
        self.assertEqual((root / 'new').read_bytes(), b'new operation')

    @unittest.skipIf(os.name == 'nt', 'Mac packet/manual-catalog contract; Windows remains unsupported')
    def test_cli_and_ui_require_a_working_claude_cli_before_manual_unknown_choices(self):
        from mrh.infrastructure import settings_v2
        from mrh.adapters.catalogs import catalog
        path = self.root / 'profile/settings.json'; settings_v2.init(path)
        unverified = ctrl.ModelChoices(manual_allowed=True)
        with patch.object(catalog, 'discover', return_value=[{'tool': 'claude', 'supported': True}]), \
             patch.object(catalog, 'describe_tool', return_value={}), \
             patch.object(catalog.ToolCatalog, 'refresh', side_effect=catalog.CatalogError('claude_catalog_protocol_incompatible')):
            self.assertTrue(ctrl.list_models('claude', {}).manual_allowed)
        with patch.object(catalog, 'discover', return_value=[]):
            unavailable = ctrl.list_models('claude', {})
        self.assertFalse(unavailable.manual_allowed)
        before = path.read_bytes()
        with self.assertRaises(CtrlError):
            ctrl.apply_set(path, settings_v2.read(path), 'tiers.Light.claude', 'future-model:high', models=lambda _: unavailable)
        self.assertEqual(path.read_bytes(), before)
        message = ctrl.apply_set(path, settings_v2.read(path), 'tiers.Light.claude', 'future-model:high', models=lambda _: unverified)
        self.assertIn('未確認', message)
        self.assertEqual(settings_v2.read(path)['policy']['tiers']['Light']['claude'], [{'model': 'future-model', 'effort': 'high'}])
        with patch.object(ctrl.os, 'name', 'nt'):
            with self.assertRaises(CtrlError):ctrl.validate_candidates([{'model': 'future-model'}], unverified, platform='claude', manual=True)

    @unittest.skipIf(os.name == 'nt', 'Mac packet/manual-catalog contract; Windows remains unsupported')
    def test_claude_manual_unknown_is_distinct_from_known_unsupported_and_other_hosts(self):
        class Menu:
            def note(self, message):pass
        session = ctrl.Session(None, Menu(), io.StringIO())
        unknown = ctrl.ModelChoices(manual_allowed=True)
        item = [{'model': 'future-model', 'effort': 'high'}]
        self.assertEqual(session.check_new_candidates(item, unknown, platform='claude', manual=True), item)
        with self.assertRaises(CtrlError):session.check_new_candidates(item, unknown, platform='codex', manual=True)
        blocked = ctrl.ModelChoices([('future-model', ('low',))], status='advertised', blocked=['retired'])
        for candidate in ([{'model': 'retired'}], item):
            with self.assertRaises(CtrlError):session.check_new_candidates(candidate, blocked, platform='claude', manual=True)
