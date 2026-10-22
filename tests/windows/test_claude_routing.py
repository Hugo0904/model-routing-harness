"""Claude Hook routing through a Windows profile; synthetic classifier only."""
import copy
from contextlib import closing
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mrh.application import advisory_runtime
from mrh.infrastructure import settings_v2
from mrh.routing.types import Classification


@unittest.skipUnless(os.name=='nt','native Windows profile semantics')
class ClaudeRoutingTests(unittest.TestCase):
    def test_profile_disabled_and_explicit_choices_preserve_original_call(self):
        with tempfile.TemporaryDirectory(prefix='MRH Claude profile ') as directory:
            path=Path(directory)/'profile/settings.json'
            settings_v2.init(path)
            class Classifier:
                calls=0
                def classify(self,*args,**kwargs):
                    self.calls+=1
                    return Classification('Light',.99)
            classifier=Classifier()
            event={'hook_event_name':'PreToolUse','tool_name':'Agent','session_id':'windows-fixture',
                   'tool_use_id':'first','cwd':directory,
                   'tool_input':{'prompt':'整理合成測試字串','subagent_type':'general-purpose'}}
            def handle(value):
                return advisory_runtime.handle(value,'claude',path,classifier_factory=lambda:classifier)
            self.assertEqual(handle(event),{})
            self.assertEqual(classifier.calls,0)
            self.assertFalse((path.parent/'advice.sqlite3').exists())
            settings_v2.update(path,enabled=True,task_export_permitted=True,allowed_workspaces=['*'],
                policy={'tiers':{'Light':{'claude':[{'model':'haiku','effort':'medium'}]}}})
            advised=handle(event)['hookSpecificOutput']
            self.assertEqual(advised['permissionDecision'],'deny')
            self.assertIn('model=haiku effort=medium',advised['permissionDecisionReason'])
            self.assertEqual(classifier.calls,1)
            chosen=copy.deepcopy(event);chosen['tool_use_id']='second';chosen['tool_input']['model']='sonnet'
            self.assertEqual(handle(chosen),{})
            self.assertEqual(classifier.calls,1)
            completed=copy.deepcopy(chosen);completed['hook_event_name']='PostToolUse'
            completed['tool_response']={'agentId':'synthetic-child','resolvedModel':'sonnet'}
            self.assertEqual(handle(completed),{})
            self.assertEqual(classifier.calls,1)
            with closing(sqlite3.connect(path.parent/'advice.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT requested_model,resolved_model FROM children').fetchall(),[('sonnet','sonnet')])

    def test_database_failure_preserves_both_phases_without_leaking_details(self):
        with tempfile.TemporaryDirectory(prefix='MRH Claude fault ') as directory:
            path=Path(directory)/'profile/settings.json'
            settings_v2.init(path)
            settings_v2.update(path,enabled=True,task_export_permitted=True,allowed_workspaces=['*'])
            for phase in ('PreToolUse','PostToolUse'):
                event={'hook_event_name':phase,'tool_name':'Agent','session_id':'fault-fixture',
                       'tool_use_id':'fault','cwd':directory,'tool_input':{'prompt':'synthetic'},
                       'tool_response':{'agentId':'synthetic-child'}}
                with patch.object(advisory_runtime,'AdviceStore',side_effect=RuntimeError('private-fixture-detail')):
                    out=advisory_runtime.handle(event,'claude',path)
                specific=out['hookSpecificOutput']
                self.assertEqual(specific['hookEventName'],phase)
                self.assertIn('additionalContext',specific)
                self.assertNotIn('permissionDecision',specific)
                self.assertNotIn('updatedInput',specific)
                self.assertNotIn('private-fixture-detail',str(out))
                if phase=='PostToolUse':self.assertIn('do not repeat a successful tool',specific['additionalContext'])

    def test_settings_change_still_prevents_classification(self):
        with tempfile.TemporaryDirectory(prefix='MRH Claude settings ') as directory:
            path=Path(directory)/'profile/settings.json'
            settings_v2.init(path)
            settings_v2.update(path,enabled=True,task_export_permitted=True,allowed_workspaces=['*'])
            first=settings_v2.read(path);second=copy.deepcopy(first);second['enabled']=False
            calls=[]
            event={'hook_event_name':'PreToolUse','tool_name':'Agent','session_id':'settings-fixture',
                   'tool_use_id':'first','cwd':directory,'tool_input':{'prompt':'synthetic'}}
            with patch.object(settings_v2,'read',side_effect=[first,second]):
                out=advisory_runtime.handle(event,'claude',path,classifier_factory=lambda:calls.append(True))
            self.assertIn('additionalContext',out['hookSpecificOutput'])
            self.assertEqual(calls,[])
            self.assertFalse((path.parent/'advice.sqlite3').exists())

    def test_reserved_codex_packets_still_deny_in_disabled_profile(self):
        with tempfile.TemporaryDirectory(prefix='MRH packet marker ') as directory:
            path=Path(directory)/'profile/settings.json'
            settings_v2.init(path)
            for tool in ('spawn_agent','collaborationspawn_agent'):
                for prefix in ('mrh_packet_','mrh_release_'):
                    event={'hook_event_name':'PreToolUse','tool_name':tool,'session_id':'marker-fixture',
                           'turn_id':'turn','tool_use_id':'first','cwd':directory,
                           'tool_input':{'message':'synthetic','task_name':prefix+'malformed'}}
                    out=advisory_runtime.handle(event,'codex',path)
                    self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertFalse((path.parent/'advice.sqlite3').exists())


if __name__=='__main__':unittest.main()
