import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mrh.application.runtime import configured_event
from mrh.infrastructure import settings
from mrh.infrastructure.settings_schema import parse_settings
from mrh.infrastructure.store import Store
from mrh.presentation import cli
from tests.application.test_codex_subscription import Runner, Host


class WorkspaceAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.work=self.root/'work';self.work.mkdir()
        self.child=self.work/'child';self.child.mkdir();self.outside=self.root/'work-sibling';self.outside.mkdir()
        self.path=self.root/'state/settings.json';settings.init(self.path)
        settings.update(self.path,enabled=True,task_export_permitted=True,allowed_workspaces=[str(self.outside)],policy={
            'top_mode':'Main','timeout_seconds':2,'tiers':{'Light':{'model':'cheap','effort':'low'}},
            'rates':{m:{'currency':'test','unit':'token','service':'test','source_ref':'fixture','components':{'input':v}}
                     for m,v in (('cheap',1),('main',2))}})
        self.file=self.root/'allowlist.json';self.save([str(self.work)])
        self.runner=Runner()

    def save(self,roots):
        self.file.write_text(json.dumps({'schema_version':1,'roots':roots}))

    def event(self,call,cwd=None,post=False):
        return {'hook_event_name':'PostToolUse' if post else 'PreToolUse','tool_name':'spawn_agent',
                'session_id':'s','turn_id':'t','tool_use_id':call,'cwd':str(cwd or self.work),
                'tool_input':{'message':'literal task'},'tool_response':{'agent_id':'child-'+call} if post else None}

    def hook(self,event):
        return configured_event(event,self.path,host_resolver=Host(),subscription_runner=self.runner)


    def test_root_descendant_sibling_symlink_escape_and_next_call_reload(self):
        settings.update(self.path,workspace_allowlist_file=str(self.file))
        self.assertIn('updatedInput',self.hook(self.event('root'))['hookSpecificOutput'])
        self.hook(self.event('child',self.child));self.assertEqual(self.runner.calls,2)
        self.assertEqual(self.hook(self.event('sibling',self.outside)),{})
        link=self.work/'escape';link.symlink_to(self.outside,target_is_directory=True)
        self.assertEqual(self.hook(self.event('escape',link)),{})
        outside=self.event('text',self.outside);outside['tool_input']['message']=str(self.work)
        self.assertEqual(self.hook(outside),{});self.assertEqual(self.runner.calls,2)
        self.save([str(self.outside)])
        self.assertEqual(self.hook(self.event('old')),{});self.hook(self.event('new',self.outside))
        self.assertEqual(self.runner.calls,3)
        self.assertEqual(Store(self.path.parent/'events.sqlite3').stats(True)['proposals'],3)
        self.save(['/'])
        self.hook(self.event('all-sibling',self.outside));self.hook(self.event('all-root',Path('/')))
        for cwd in (None,'https://other-host/work'):
            event=self.event('nonlocal');event['cwd']=cwd
            self.assertEqual(self.hook(event),{})
        self.assertEqual(self.runner.calls,5)
        self.assertEqual(Store(self.path.parent/'events.sqlite3').stats(True)['proposals'],5)

    def test_invalid_missing_empty_file_never_invokes_or_admits(self):
        settings.update(self.path,workspace_allowlist_file=str(self.file))
        for data in ('{}','{"schema_version":true,"roots":[]}',
                     '{"schema_version":1,"roots":["relative"]}',
                     '{"schema_version":1,"roots":[],"roots":[]}', 'x'*65537):
            self.file.write_text(data)
            with patch('mrh.application.runtime.classifier_from_config',side_effect=AssertionError('factory')),\
                 patch('sys.stderr',io.StringIO()):
                self.assertIn('systemMessage',self.hook(self.event('invalid')))
            self.assertFalse((self.path.parent/'events.sqlite3').exists())
        self.save([]);self.assertEqual(self.hook(self.event('empty')),{});self.file.unlink()
        with patch('sys.stderr',io.StringIO()):self.assertIn('systemMessage',self.hook(self.event('missing')))
        self.assertEqual(self.runner.calls,0);self.assertFalse((self.path.parent/'events.sqlite3').exists())
        self.file.symlink_to(self.root/'missing')
        with patch('sys.stderr',io.StringIO()):self.assertIn('systemMessage',self.hook(self.event('link')))
        self.assertFalse((self.path.parent/'events.sqlite3').exists())

    def test_post_keeps_admitted_receipt_after_edit_and_unadmitted_post_is_neutral(self):
        settings.update(self.path,workspace_allowlist_file=str(self.file))
        self.assertEqual(self.hook(self.event('unadmitted',post=True)),{})
        self.assertFalse((self.path.parent/'events.sqlite3').exists())
        self.hook(self.event('admitted'));self.file.unlink()
        with patch('mrh.infrastructure.store.Store.__init__',side_effect=AssertionError('store init')):
            self.assertEqual(self.hook(self.event('admitted',post=True)),{})
            self.assertEqual(self.hook(self.event('foreign',post=True)),{})
        stats=Store(self.path.parent/'events.sqlite3').stats(True)
        self.assertEqual((stats['proposals'],stats['simulated_children'],self.runner.calls),(1,1,1))
        settings.update(self.path,enabled=False)
        self.assertEqual(self.hook(self.event('admitted',post=True)),{})
