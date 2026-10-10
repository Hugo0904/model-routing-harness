"""Public CLI settings flow; real owned files, no provider or host execution."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mrh import cli, settings
from mrh.settings_schema import SettingsError
from mrh.store import Store
from mrh.terminal import cell_width, render_stats
from mrh.simulation import demo_policy
from mrh.types import Proposal, Decision


class SettingsCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root/'owned/settings.json'
        settings.init(self.path)

    def run_cli(self, args, text='', stream=None, output=None):
        out, err = output or io.StringIO(), io.StringIO()
        result = cli.main(args, stdin=stream or io.StringIO(text), stdout=out, stderr=err)
        return result, out.getvalue(), err.getvalue()

    def edit(self, text='', **kwargs):
        return self.run_cli(['settings','edit','--path',str(self.path),'--plain'],text,**kwargs)

    def test_save_readback_preserves_other_fields_and_json_dashboard_shape(self):
        policy = settings.read(self.path)['policy']
        policy['rates'] = {'old-model':{'currency':'USD','unit':'per-token','service':'standard','source_ref':'fixture-rate','components':{'input':1.0}}}
        policy['tiers']['Top'] = {'model':'IGNORED-LEGACY-TOP'}
        settings.update(self.path, policy=policy, allowed_workspaces=[str(self.root)], task_export_permitted=True)
        before = settings.read(self.path)
        with patch('mrh.typesafe.environment_credential', side_effect=AssertionError('credential read')):
            code, out, err = self.edit('light-choice\ninherit\nsmall-choice\nlow\nmid-choice\nhigh\nFixed\nfixed-choice\ninherit\nsave\n')
        self.assertEqual((code,err),(0,'')); self.assertIn('BEFORE -> AFTER',out)
        after = settings.read(self.path)
        expected = copy.deepcopy(before); expected['revision'] += 1
        expected['policy']['tiers'].update(Light={'model':'light-choice'},Small={'model':'small-choice','effort':'low'},Mid={'model':'mid-choice','effort':'high'})
        expected['policy'].update(top_mode='Fixed',fixed={'model':'fixed-choice'})
        self.assertEqual(after,expected)
        self.assertFalse(after['enabled'])
        self.assertFalse((self.path.parent/'events.sqlite3').exists())
        store=Store(self.path.parent/'events.sqlite3')
        previous=Proposal('codex','simulation','prior-session','prior-turn','prior-call',{'message':'prior fixture','model':'historical-choice'},True)
        store.claim(previous);store.complete(previous.identity,Decision(reason='explicit_model',synthetic=True))
        self.assertEqual(json.loads(self.run_cli(['stats','--settings',str(self.path),'--json'])[1]),store.stats())
        history=json.loads(self.run_cli(['stats','--settings',str(self.path),'--synthetic','--json'])[1])
        self.assertEqual(history,store.stats(True));self.assertEqual(history['proposals'],1)
        self.assertEqual(json.loads(self.run_cli(['settings','show','--path',str(self.path)])[1])['settings'],after)
        dash=self.run_cli(['status','--settings',str(self.path),'--synthetic','--plain','--width','120'])[1]
        for text in ('CURRENT CONFIGURATION','light-choice / inherit','Fixed / fixed-choice / inherit','historical counts','Confirmed children 0'):
            self.assertIn(text,dash)
        self.assertNotIn('IGNORED-LEGACY-TOP',dash)

    def test_cancel_eof_and_ctrl_c_before_save_have_zero_writes(self):
        initial=self.path.read_bytes()
        class Interrupt(io.StringIO):
            def readline(self,*args): raise KeyboardInterrupt()
        for text,stream in [('cancel\n',None),('',None),('light-choice\ninherit\n\n\n\ncancel\n',None),('',Interrupt())]:
            with self.subTest(text=text,stream=type(stream).__name__):
                result,out,err=self.edit(text,stream=stream)
                self.assertEqual((result,err),(0,''));self.assertIn('Cancelled',out)
                self.assertEqual(self.path.read_bytes(),initial)

    def test_stale_revision_preserves_concurrent_actor_bytes(self):
        path=self.path
        captured=[]
        class Concurrent(io.StringIO):
            def readline(self,*args):
                line=super().readline(*args)
                if line.strip()=='save':
                    settings.update(path,task_export_permitted=True)
                    captured.append(path.read_bytes())
                return line
        code,out,err=self.edit(stream=Concurrent('light-choice\ninherit\n\n\n\nsave\n'))
        self.assertEqual(code,2);self.assertIn('settings_conflict',err)
        self.assertIn('Reopen the editor',out);self.assertEqual(self.path.read_bytes(),captured[0])
        self.assertEqual(settings.read(path)['policy']['tiers'],{})

    def test_unset_inherit_main_and_no_change_save(self):
        settings.update(self.path,policy={'top_mode':'Fixed','fixed':{'model':'old-top','effort':'high'},
                                        'tiers':{'Light':{'model':'old-light','effort':'low'}}})
        code,out,err=self.edit('unset\n\n\nMain\nsave\n')
        self.assertEqual((code,err),(0,''));current=settings.read(self.path)
        self.assertEqual(current['policy']['tiers'],{});self.assertEqual(current['policy']['top_mode'],'Main')
        self.assertEqual(current['policy']['fixed'],{'model':'old-top','effort':'high'})
        initial=self.path.read_bytes()
        code,out,err=self.edit('\n\n\n\nsave\n')
        self.assertEqual((code,err),(0,''));self.assertIn('Unchanged',out);self.assertEqual(self.path.read_bytes(),initial)
        view=self.run_cli(['settings','view','--path',str(self.path),'--plain'])[1]
        self.assertIn('Main / current main agent',view);self.assertNotIn('old-top',view)
        self.assertIn('Unset / preserve original',view)

    def test_invalid_input_recovers_and_fixed_requires_model(self):
        code,out,err=self.edit('bad name\nlight-choice\nbad effort\ninherit\n\n\nwrong\nFixed\nunset\nfixed-choice\nhigh\nsave\n')
        self.assertEqual((code,err),(0,''));self.assertIn('Fixed needs a model',out)
        self.assertEqual(settings.read(self.path)['policy']['fixed'],{'model':'fixed-choice','effort':'high'})

    def test_invalid_unowned_and_conflicting_sources_refuse_before_store(self):
        unowned=self.root/'unowned/settings.json';unowned.parent.mkdir();unowned.write_bytes(self.path.read_bytes())
        for path in (unowned,self.root/'missing/settings.json'):
            for command in (['settings','edit','--path'],['settings','view','--path'],['stats','--settings']):
                with self.subTest(path=path,command=command):
                    self.assertEqual(self.run_cli([*command,str(path)])[0],2)
                    self.assertFalse((path.parent/'events.sqlite3').exists())
        self.path.write_text('{}')
        self.assertEqual(self.edit()[0],2);self.assertFalse((self.path.parent/'events.sqlite3').exists())
        with self.assertRaises(SystemExit) as raised, patch('sys.stderr',io.StringIO()):
            cli.main(['stats','--settings',str(self.path),'--db',str(self.root/'other.db')])
        self.assertEqual(raised.exception.code,2)

    def test_narrow_color_no_color_and_history_separation(self):
        settings.update(self.path,policy={'top_mode':'Main','tiers':{'Light':{'model':'CURRENT-'+('x'*90)}}})
        stats=Store(self.path.parent/'events.sqlite3').stats(True)
        for width in (24,28,56,120):
            for color in (False,True):
                out=render_stats(stats,width=width,color=color,configuration=settings.read(self.path))
                self.assertTrue(all(cell_width(line)<=width for line in out.splitlines()))
                self.assertEqual('\x1b' in out,color)
                self.assertNotIn('SYNTHETIC DEMO',out)
        class Tty(io.StringIO):
            def isatty(self):return True
        with patch.dict(os.environ,{'NO_COLOR':'1','TERM':'xterm'}):
            out=self.run_cli(['settings','view','--path',str(self.path)],output=Tty())[1]
        self.assertNotIn('\x1b',out)
        out=self.run_cli(['status','--settings',str(self.path),'--details','--plain'])[1]
        self.assertIn('CURRENT CONFIGURATION',out);self.assertIn('ACTUAL MODELS',out)
        with self.assertRaisesRegex(ValueError,'conflicting_policy_sources'):
            render_stats(stats,configuration=settings.read(self.path),demo_policy=demo_policy())


if __name__=='__main__':unittest.main()
