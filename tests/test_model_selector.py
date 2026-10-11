"""R2 public CLI with explicitly synthetic authoritative catalog dependencies."""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from mrh import cli, settings
from mrh.bindings import Registry, target_veto, BindingError
from mrh.catalog import Catalog, Model, CatalogError, executable_hash
from mrh.core import route, cached_effect_blocker, ScriptedClassifier, Classification
from mrh.simulation import demo_capabilities, demo_policy
from mrh.types import Proposal
from mrh.terminal import cell_width


class Tty(io.StringIO):
    def isatty(self):return True


class Provider:
    def __init__(self, rows=None):
        self.rows = rows or (Model('canonical-small', 'Friendly Small', ('low','high')),
                             Model('canonical-top', 'Friendly Top', ('high',)))
        self.calls = 0;self.effect = None
    def refresh(self, b):
        self.calls += 1
        if self.effect is not None:return self.effect(b, self.calls)
        return self.snapshot(b)
    def snapshot(self, b, rows=None, **changes):
        return Catalog(b['id'], b['tool'], b['executable_sha256'], b['version'],
                       'synthetic:authoritative-catalog', time.time(), tuple(self.rows if rows is None else rows),
                       assurance='synthetic', **changes)


class ModelSelectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()/'registry';self.registry = Registry(self.root)
        self.provider = Provider()
        exe = str(Path('/usr/bin/true').resolve())
        self.candidate = {'tool':'codex','label':'Synthetic Codex fixture','executable':exe,
                          'supported':True,'version':'synthetic-version','executable_sha256':executable_hash(exe)}
        self.dependencies = {'provider': self.provider, 'discovery': lambda:[self.candidate],
                             'describe': lambda c:c}
    def bind(self, label='Synthetic Codex fixture'):
        return self.registry.associate({**self.candidate,'label':label},expected_revision=self.registry.read()['revision'])
    def run_cli(self, tier=None, text='', stream=None, extra=(), width=120):
        out = io.StringIO();err = io.StringIO()
        args = ['model',*([tier] if tier else []),'--root',str(self.root),'--plain','--width',str(width),*extra]
        code = cli.main(args,stdin=stream if stream is not None else Tty(text),stdout=out,stderr=err,
                        model_dependencies=self.dependencies)
        return code,out.getvalue(),err.getvalue()

    def test_first_use_confirmation_cancel_and_noninteractive_are_side_effect_free(self):
        for text in ('cancel\n','1\ncancel\n'):
            self.assertEqual(self.run_cli('light',text)[0],0)
            self.assertFalse(self.root.exists());self.assertEqual(self.provider.calls,0)
        code,out,_=self.run_cli('light',stream=io.StringIO('1\nbind\n1\n1\nsave\n'))
        self.assertEqual(code,2);self.assertIn('interactive terminal',out);self.assertFalse(self.root.exists())
        with patch('mrh.typesafe.environment_credential',side_effect=AssertionError('credential access')):
            code,out,err=self.run_cli('light','1\nbind\n1\n2\nsave\n')
        self.assertEqual((code,err),(0,''));self.assertIn('not an account login',out)
        b=self.registry.read()['bindings'][0];saved=settings.read(b['settings_path'])
        self.assertEqual(saved['policy']['tiers']['Light'],{'model':'canonical-small','effort':'low'})
        self.assertEqual(saved['revision'],1);self.assertFalse(saved['enabled']);self.assertFalse(saved['task_export_permitted'])
        self.assertEqual(saved['allowed_workspaces'],[])

    def test_one_multiple_tier_picker_defaults_back_and_exact_ids(self):
        first=self.bind();second=self.bind('Second bound profile')
        code,out,err=self.run_cli(None,'2\n3\n2\n2\nsave\n',width=56)
        self.assertEqual((code,err),(0,''));self.assertIn('BOUND TOOLS',out)
        self.assertEqual(settings.read(first['settings_path'])['policy']['tiers'],{})
        self.assertEqual(settings.read(second['settings_path'])['policy']['tiers']['Mid'],{'model':'canonical-top','effort':'high'})
        self.assertTrue(all(cell_width(l)<=56 for l in out.splitlines()))
        code,out,_=self.run_cli('small','1\nback\n2\n1\n1\nsave\n')
        self.assertEqual(code,0);self.assertIn('Back.',out)
        self.assertEqual(settings.read(first['settings_path'])['policy']['tiers']['Small'],{'model':'canonical-small'})

    def test_unicode_labels_escape_sanitization_and_narrow_choice_geometry(self):
        self.bind();self.provider.rows=(Model('canonical-long-'+('a'*80),'模型名稱'*12+'\x1b]2;unsafe\x07',('low',)),)
        code,out,_=self.run_cli('small','1\n1\nsave\n',width=28)
        self.assertEqual(code,0)
        self.assertTrue(all(cell_width(l)<=28 for l in out.splitlines()))
        self.assertNotIn('\x1b',out)

    def test_top_main_offline_keeps_fixed_and_fixed_picker_uses_supported_efforts(self):
        b=self.bind();policy={'top_mode':'Fixed','fixed':{'model':'legacy','effort':'high'},'tiers':{},'rates':{}}
        settings.update(b['settings_path'],policy=policy)
        self.provider.effect=lambda *a:(_ for _ in ()).throw(CatalogError('catalog_refresh_failed'))
        code,out,_=self.run_cli('top','1\nsave\n')
        self.assertEqual(code,0);saved=settings.read(b['settings_path'])
        self.assertEqual(saved['policy']['top_mode'],'Main');self.assertEqual(saved['policy']['fixed'],policy['fixed'])
        self.assertIn('No model is marked retired',out)
        self.provider.effect=None
        code,out,_=self.run_cli('top','2\n2\n2\nsave\n')
        self.assertEqual(code,0);self.assertEqual(settings.read(b['settings_path'])['policy']['fixed'],{'model':'canonical-top','effort':'high'})
        self.assertNotIn('low [current]',out)

    def test_model_retired_missing_or_revoked_never_silently_substituted(self):
        b=self.bind();settings.update(b['settings_path'],policy={'tiers':{'Light':{'model':'legacy'}}})
        for rows,phrase in [((Model('legacy','Old',(), 'retired','official:retirement-notice'),*self.provider.rows),'confirmed retired'),
                            (self.provider.rows,'global retirement is unconfirmed'),
                            ((Model('legacy','Old',(), 'unavailable'),*self.provider.rows),'unavailable in this list')]:
            with self.subTest(phrase=phrase):
                self.provider.effect=lambda binding,n,rows=rows:self.provider.snapshot(binding,rows)
                before=Path(b['settings_path']).read_bytes()
                code,out,_=self.run_cli('light','cancel\n')
                self.assertEqual(code,0);self.assertIn(phrase,out);self.assertEqual(Path(b['settings_path']).read_bytes(),before)
                veto=target_veto(b['settings_path'],synthetic=True)
                self.assertIn(veto['legacy'],('catalog_model_unavailable','catalog_model_retired'))
                self.assertEqual(target_veto(b['settings_path']),{}) # synthetic cache never production proof
        self.provider.effect=None
        code,out,_=self.run_cli('light','1\n1\nsave\n')
        self.assertEqual(code,0);self.assertEqual(settings.read(b['settings_path'])['policy']['tiers']['Light'],{'model':'canonical-small'})

    def test_failed_partial_stale_and_scope_change_caches_do_not_authorize_selection(self):
        b=self.bind();settings.update(b['settings_path'],policy={'tiers':{'Light':{'model':'missing'}}})
        snap=self.provider.snapshot(b);self.registry.record_refresh(b,snap)
        saved=Path(b['settings_path']).read_bytes();cached=self.registry.read()['bindings'][0]['catalog']
        for result in ('catalog_refresh_failed','catalog_unauthenticated','partial'):
            self.provider.effect=(lambda b,n:self.provider.snapshot(b,complete=False)) if result=='partial' else (
                lambda b,n,result=result:(_ for _ in ()).throw(CatalogError(result)))
            code,out,_=self.run_cli('light','cancel\n')
            self.assertEqual(code,0);self.assertIn('display only',out)
            self.assertEqual(Path(b['settings_path']).read_bytes(),saved)
            self.assertEqual(self.registry.read()['bindings'][0]['catalog'],cached)
            self.assertEqual(target_veto(b['settings_path'],synthetic=True),{})
        self.registry.record_refresh(b,snap)
        self.assertEqual(target_veto(b['settings_path'],now=snap.fetched_at+301,synthetic=True),{})
        other=self.bind('Other');self.assertIsNone(other['catalog'])
        with self.assertRaises(BindingError):self.registry.record_refresh(other,snap)

    def test_save_rechecks_removed_model_effort_and_concurrent_settings(self):
        b=self.bind();path=Path(b['settings_path']);before=path.read_bytes()
        for mode in ('model','effort'):
            def changing(b,n):
                return self.provider.snapshot(b,() if mode=='model' and n==2 else (
                    (Model('canonical-small','Friendly Small',('high',)),) if mode=='effort' and n==2 else self.provider.rows))
            self.provider.calls=0;self.provider.effect=changing
            code,out,_=self.run_cli('light','1\n2\nsave\ncancel\n')
            self.assertEqual(code,0);self.assertIn('Nothing saved',out);self.assertEqual(path.read_bytes(),before)
        self.provider.effect=None
        class Concurrent(Tty):
            def readline(self,*args):
                line=super().readline(*args)
                if line.strip()=='save':settings.update(path,task_export_permitted=True)
                return line
        code,out,_=self.run_cli('light',stream=Concurrent('1\n1\nsave\n'))
        self.assertEqual(code,2);self.assertIn('settings_conflict',out)
        self.assertEqual(settings.read(path)['policy']['tiers'],{});self.assertTrue(settings.read(path)['task_export_permitted'])

    def test_binding_and_catalog_conflicts_preserve_profile_and_owned_paths(self):
        b=self.bind();initial=settings.read(b['settings_path']);snap=self.provider.snapshot(b)
        self.registry.record_refresh(b,snap)
        self.registry.record_refresh(b,self.provider.snapshot(b))
        with self.assertRaises(BindingError):self.registry.save(b,initial,initial['policy'],snap,'canonical-small')
        unowned=self.root.parent/'unowned';unowned.mkdir();(unowned/'registry.json').write_text('{}')
        with self.assertRaises(BindingError):Registry(unowned).read()
        with self.assertRaises(BindingError):self.registry.associate(self.candidate,expected_revision=0)
        self.assertEqual(settings.read(b['settings_path']),initial)

    def test_known_unavailable_veto_never_promotes_catalog_to_same_call_facts(self):
        p=Proposal('codex','simulation','s','t','c',{'message':'fixture'},True)
        policy=demo_policy();policy['top_mode']='Fixed'
        target=policy['fixed']['model'];policy['_target_veto']={target:'catalog_model_retired'}
        decision=route(p,policy,demo_capabilities(),ScriptedClassifier([Classification('Top',.9)]))
        self.assertEqual(decision.action,'preserve');self.assertEqual(decision.reason,'catalog_model_retired')
        policy.pop('_target_veto')
        caps=demo_capabilities();caps['models']={}
        decision=route(p,policy,caps,ScriptedClassifier([Classification('Top',.9)]))
        self.assertEqual(decision.action,'preserve');self.assertIn(decision.reason,('missing_target_model','classifier_unavailable'))

    def test_veto_only_negative_and_blocks_cached_effect_without_new_classifier_work(self):
        p=Proposal('codex','simulation','s','t','c',{'message':'fixture'},True)
        policy=demo_policy();policy['top_mode']='Fixed';policy['tiers']={}
        classifier=ScriptedClassifier([Classification('Top',.9)])
        accepted=route(p,policy,demo_capabilities(),classifier)
        self.assertEqual(accepted.action,'request_child')
        policy['_target_veto']={policy['fixed']['model']:'catalog_model_unavailable'}
        self.assertEqual(cached_effect_blocker(p,policy,demo_capabilities(),accepted),'catalog_model_unavailable')
        fresh=ScriptedClassifier([Classification('Top',.9)])
        decision=route(p,policy,demo_capabilities(),fresh)
        self.assertEqual(decision.action,'preserve');self.assertEqual(fresh.calls,0)
        b=self.bind();settings.update(b['settings_path'],policy={'tiers':{'Light':{'model':'outside-default-list'}}})
        advertised=self.provider.snapshot(b)
        advertised=Catalog(**{**advertised.__dict__,'assurance':'tool-advertised'})
        self.registry.record_refresh(b,advertised)
        self.assertEqual(target_veto(b['settings_path']),{})

    def test_catalog_ids_efforts_scope_and_explicit_retirement_validation(self):
        b=self.bind()
        for rows in ((Model('bad model','Invalid'),), (Model('ok','Duplicate'),Model('ok','Duplicate')),
                     (Model('ok','Efforts',('high','high')),), (Model('ok','Retired',(), 'retired'),)):
            with self.assertRaises(CatalogError):self.provider.snapshot(b,rows).validate()
        with self.assertRaises(BindingError):
            s=self.provider.snapshot(b)
            self.registry.record_refresh(b,Catalog(**{**s.__dict__,'assurance':'account-confirmed'}))
        with self.assertRaises(SystemExit), patch('sys.stderr',new=io.StringIO()) as err:
            cli.build_parser().parse_args(['model','ligth'])
        self.assertIn('light',err.getvalue());self.assertIn('top',err.getvalue())

    def test_existing_owned_profile_is_only_associated_explicitly_and_values_retained(self):
        path=self.root.parent/'old/settings.json';settings.init(path)
        settings.update(path,policy={'tiers':{'Mid':{'model':'legacy'}}})
        before=path.read_bytes()
        code,out,_=self.run_cli('light','1\nbind\ncancel\n',extra=('--bind','--associate-settings',str(path)))
        self.assertEqual(code,0);self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.registry.read()['bindings'][0]['settings_path'],str(path))
        self.assertIn('values are retained',out)


if __name__ == '__main__':unittest.main()
