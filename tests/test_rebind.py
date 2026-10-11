"""Same-profile metadata CAS and explicit selector update recovery."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from mrh import cli, settings
from mrh.bindings import BindingError, Registry
from mrh.catalog import CatalogError, Model, executable_hash
from mrh.store import Store
from mrh.types import Decision, Proposal
from test_model_selector import Provider, Tty


class RebindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mrh-rebind-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.exe = self.root/'codex';self.exe.write_text('#!/bin/sh\nexit 0\n');self.exe.chmod(0o755)
        self.registry = Registry(self.root/'registry');self.provider = Provider()
        self.binding = self.registry.associate(self.candidate(), expected_revision=0)
        self.path = Path(self.binding['settings_path'])
        self.snapshot = self.provider.snapshot(self.binding)
        self.registry.record_refresh(self.binding, self.snapshot, expected_revision=1)
        self.binding = self.registry.read()['bindings'][0]

    def candidate(self, exe=None):
        exe = exe or self.exe
        return {'tool':'codex','label':'Owned synthetic CLI','supported':True,
                'executable':str(exe),'executable_sha256':executable_hash(exe),'version':'synthetic-version'}

    def update(self):
        self.exe.write_text(self.exe.read_text()+'# owned compatible update\n')
        candidate = self.candidate()
        proposed = self.registry.candidate_binding(self.binding, candidate)
        return candidate, self.provider.snapshot(proposed)

    def bytes(self):
        return {p.name:p.read_bytes() for p in self.path.parent.iterdir() if p.is_file()}

    def run_cli(self, text, *, change_on_save=False, describe=None, discovery=None, rows=None):
        owner = self
        class Input(Tty):
            def readline(self, *args):
                line = super().readline(*args)
                if line.strip() == 'save' and change_on_save and not getattr(self, 'changed', False):
                    owner.update();self.changed = True
                return line
        def refresh(binding, calls):
            if executable_hash(binding['executable']) != binding['executable_sha256']:
                raise CatalogError('tool_changed_rebind_required')
            return self.provider.snapshot(binding, rows)
        self.provider.effect = refresh
        out = io.StringIO();err = io.StringIO()
        code = cli.main(['model','light','--root',str(self.registry.root),'--plain','--width','56'],
                        stdin=Input(text),stdout=out,stderr=err,model_dependencies={
                            'provider':self.provider,'discovery':discovery or (lambda:[self.candidate()]),
                            'describe':describe or (lambda c:c)})
        self.assertEqual(err.getvalue(), '')
        return code,' '.join(out.getvalue().split())

    def test_atomic_rebind_retains_profile_policy_history_and_stored_stop(self):
        store = Store(self.path.parent/'events.sqlite3')
        proposal = Proposal('codex','simulation','s','t','stop-fixture',{},True)
        decision = Decision('operator_update_required','unsupported_model','Light',.9,{},True,
                            target_model='canonical-small')
        store.claim(proposal);store.complete(proposal.identity, decision)
        before = self.bytes();candidate,snapshot = self.update()
        old_revision = self.registry.read()['revision']
        result = self.registry.rebind(self.binding,candidate,snapshot,expected_revision=old_revision)
        current = self.registry.read()
        self.assertEqual(len(current['bindings']),1)
        self.assertEqual((result['id'],result['settings_path']),(self.binding['id'],str(self.path)))
        self.assertEqual(result['catalog']['scope'],candidate['executable_sha256'])
        self.assertEqual(result['catalog'],snapshot.public())
        self.assertIsNone(result['refresh_error'])
        self.assertEqual(current['revision'],old_revision+1)
        self.assertEqual(self.bytes(),before)
        self.assertEqual(store.claim(proposal),('cached',decision))

    def test_mismatched_catalog_other_tool_or_commit_time_change_never_writes(self):
        candidate,snapshot = self.update();before = (self.registry.root/'registry.json').read_bytes()
        for proposed,snap in ((candidate,self.snapshot),({**candidate,'tool':'claude'},snapshot)):
            with self.assertRaises(BindingError):self.registry.rebind(self.binding,proposed,snap,expected_revision=2)
            self.assertEqual((self.registry.root/'registry.json').read_bytes(),before)
        self.exe.write_text(self.exe.read_text()+'# second update during review\n')
        with self.assertRaisesRegex(BindingError,'tool_changed_rebind_required'):
            self.registry.rebind(self.binding,candidate,snapshot,expected_revision=2)
        self.assertEqual((self.registry.root/'registry.json').read_bytes(),before)

    def test_stale_revision_refresh_and_rebind_preserve_concurrent_winner(self):
        candidate,snapshot = self.update()
        self.registry.record_refresh(self.binding,error='catalog_refresh_failed',expected_revision=2)
        winner = (self.registry.root/'registry.json').read_bytes()
        with self.assertRaisesRegex(BindingError,'binding_conflict'):
            self.registry.rebind(self.binding,candidate,snapshot,expected_revision=2)
        with self.assertRaisesRegex(BindingError,'binding_conflict'):
            self.registry.record_refresh(self.binding,self.snapshot,expected_revision=2)
        self.assertEqual((self.registry.root/'registry.json').read_bytes(),winner)
        self.registry.rebind(self.binding,candidate,snapshot,expected_revision=3)
        winner = (self.registry.root/'registry.json').read_bytes()
        with self.assertRaisesRegex(BindingError,'binding_conflict'):
            self.registry.record_refresh(self.binding,self.snapshot,expected_revision=4)
        with self.assertRaises(BindingError):
            self.registry.save(self.binding,settings.read(self.path),{},self.snapshot,expected_revision=4)
        self.assertEqual((self.registry.root/'registry.json').read_bytes(),winner)

    def test_save_registry_revision_cas_rejects_concurrent_refresh(self):
        initial = settings.read(self.path);policy = copy.deepcopy(initial['policy'])
        policy['tiers']['Light'] = {'model':'canonical-small'}
        self.registry.record_refresh(self.binding,self.snapshot,expected_revision=2)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(BindingError,'binding_or_catalog_conflict'):
            self.registry.save(self.binding,initial,policy,self.snapshot,'canonical-small',expected_revision=2)
        self.assertEqual(self.path.read_bytes(),before)

    def test_stale_candidate_catalog_never_updates_identity(self):
        candidate,snapshot = self.update();before = (self.registry.root/'registry.json').read_bytes()
        with self.assertRaisesRegex(BindingError,'rebind_catalog_stale'):
            self.registry.rebind(self.binding,candidate,replace(snapshot,fetched_at=snapshot.fetched_at-301),expected_revision=2)
        self.assertEqual((self.registry.root/'registry.json').read_bytes(),before)

    def test_selector_refresh_cas_does_not_overwrite_concurrent_diagnostic(self):
        before = self.bytes();out = io.StringIO()
        def refresh(binding, calls):
            self.registry.record_refresh(binding,error='concurrent_winner',expected_revision=2)
            return self.provider.snapshot(binding)
        self.provider.effect = refresh
        code = cli.main(['model','light','--root',str(self.registry.root),'--plain'],stdin=Tty('cancel\n'),
                        stdout=out,stderr=io.StringIO(),model_dependencies={
                            'provider':self.provider,'discovery':lambda:[self.candidate()],'describe':lambda c:c})
        self.assertEqual(code,2)
        self.assertEqual(self.registry.read()['bindings'][0]['refresh_error'],'concurrent_winner')
        self.assertEqual(self.bytes(),before)

    def test_cancel_before_rebind_confirmation_retains_old_identity_and_bytes(self):
        before = self.bytes();self.update()
        code,out = self.run_cli('inspect\n1\ncancel\n')
        self.assertEqual(code,0);self.assertIn('CONFIRM CLI UPDATE',out)
        self.assertEqual(self.registry.identity(self.registry.read()['bindings'][0]),self.registry.identity(self.binding))
        self.assertEqual(self.bytes(),before)

    def test_unsupported_inspection_or_failed_candidate_catalog_keeps_old_binding(self):
        def unsupported(candidate):raise CatalogError('gemini_catalog_version_unsupported')
        before = self.bytes();self.update()
        code,out = self.run_cli('inspect\n1\ncancel\n',describe=unsupported)
        self.assertEqual(code,0);self.assertIn('Unsupported versions require a supported CLI',out)
        self.assertEqual(self.bytes(),before)
        self.assertEqual(self.registry.identity(self.registry.read()['bindings'][0]),self.registry.identity(self.binding))
        self.provider.snapshot = lambda *a: (_ for _ in ()).throw(CatalogError('catalog_refresh_failed'))
        code,out = self.run_cli('inspect\n1\ncancel\n')
        self.assertEqual(code,0);self.assertIn('CLI update cannot be confirmed',out)
        self.assertEqual(self.bytes(),before)

    def test_confirmed_update_keeps_unsaved_draft_and_cancel_keeps_metadata_only(self):
        before = self.bytes()
        code,out = self.run_cli('1\n3\nsave\ninspect\n1\nconfirm\ncancel\n',change_on_save=True)
        self.assertEqual(code,0);self.assertIn('Confirmed CLI update retained',out)
        self.assertIn('Friendly Small (canonical-small) [current]',out)
        self.assertEqual(self.bytes(),before)
        current = self.registry.read()['bindings'][0]
        self.assertEqual(current['id'],self.binding['id'])
        self.assertEqual(current['executable_sha256'],executable_hash(self.exe))
        self.assertNotEqual(current['executable_sha256'],self.binding['executable_sha256'])

    def test_confirmed_update_retains_draft_effort_until_separate_save(self):
        code,out = self.run_cli('1\n3\nsave\ninspect\n1\nconfirm\n\n\nsave\n',change_on_save=True)
        self.assertEqual(code,0);self.assertIn('Same profile and draft retained',out)
        value = settings.read(self.path)
        self.assertEqual(value['policy']['tiers']['Light'],{'model':'canonical-small','effort':'high'})
        self.assertEqual(value['revision'],1)
        self.assertEqual(self.registry.read()['bindings'][0]['settings_path'],str(self.path))

    def test_removed_model_or_incompatible_effort_requires_choice_or_cancel(self):
        settings.update(self.path,policy={'tiers':{'Light':{'model':'canonical-small','effort':'high'}}})
        before = self.bytes();self.update()
        for rows,message in (((Model('replacement','Explicit replacement'),),'unavailable in this list'),
                             ((Model('canonical-small','Friendly Small',('low',)),),'reasoning effort high is unavailable')):
            code,out = self.run_cli('inspect\n1\nconfirm\ncancel\n',rows=rows)
            self.assertEqual(code,0);self.assertIn(message,out)
            self.assertEqual(self.bytes(),before)
            self.binding = self.registry.read()['bindings'][0];self.update()

    def test_same_tool_candidate_picker_can_choose_other_installation(self):
        self.update();other = self.root/'other-codex';other.write_text('#!/bin/sh\nexit 0\n# other\n');other.chmod(0o755)
        discovery = lambda:[{**self.candidate(),'tool':'claude'},self.candidate(),self.candidate(other)]
        code,out = self.run_cli('inspect\n2\nconfirm\ncancel\n',discovery=discovery)
        self.assertEqual(code,0);self.assertIn('INSPECT UPDATED CLI',out)
        current = self.registry.read()['bindings'][0]
        self.assertEqual((current['executable'],current['tool'],current['id']),
                         (str(other),'codex',self.binding['id']))


if __name__ == '__main__':unittest.main()
