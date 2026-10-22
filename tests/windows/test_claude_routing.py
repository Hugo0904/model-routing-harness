"""Claude Hook routing through a Windows profile; synthetic classifier only."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()
