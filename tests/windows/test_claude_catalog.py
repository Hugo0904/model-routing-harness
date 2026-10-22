"""Windows dispatch and initialize-only framing; no host or provider calls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from mrh.adapters.catalogs import catalog, claude_catalog as claude
from mrh.adapters.catalogs.catalog import CatalogError
from mrh.infrastructure import owned


@unittest.skipUnless(os.name == 'nt', 'Windows catalog dispatch')
class ClaudeWindowsCatalogTests(unittest.TestCase):
    def test_windows_sends_only_initialize_and_preserves_request_model_values(self):
        class Sandbox:
            work = Path('C:/private space/runtime')
            def capture(self, args, **kwargs):
                request = json.loads(kwargs['input'])
                self.request = request; self.args = args
                frame = {'type':'control_response','response':{'request_id':request['request_id'],
                    'subtype':'success','response':{'models':[{'value':'opus','displayName':'Opus',
                    'supportedEffortLevels':['high','xhigh','max']}]}}}
                self.assert_match = kwargs['until']((json.dumps(frame)+'\n').encode())
        sandbox = Sandbox()
        models = claude._windows_models(sandbox)
        self.assertTrue(sandbox.assert_match)
        self.assertEqual(models[0].id,'opus')
        self.assertEqual(sandbox.request['type'],'control_request')
        self.assertEqual(sandbox.request['request'],{'subtype':'initialize','hooks':{},'sdkMcpServers':[],'agents':{},'plugins':[]})
        self.assertIn('--bare',sandbox.args)
        self.assertIn('--strict-mcp-config',sandbox.args)

    def test_windows_rejects_malformed_duplicate_unsolicited_timeout_and_eof(self):
        for mode in ('malformed','duplicate','user','timeout','eof'):
            class Sandbox:
                work = Path('C:/private space/runtime')
                def capture(self, args, **kwargs):
                    if mode == 'timeout': raise subprocess.TimeoutExpired(args,15)
                    if mode == 'eof': return b''
                    data = {'malformed':b'invalid\n','duplicate':b'{"type":"system","type":"system"}\n',
                            'user':b'{"type":"user"}\n'}[mode]
                    kwargs['until'](data)
            with self.subTest(mode=mode), self.assertRaises(CatalogError) as raised:
                claude._windows_models(Sandbox())
            self.assertEqual(str(raised.exception),'claude_catalog_timeout' if mode=='timeout' else
                             'claude_catalog_initialize_failed' if mode=='eof' else 'claude_catalog_protocol_incompatible')

    def test_pinned_discovery_requires_claude_receipt_hash(self):
        exe = 'C:/ProgramData/private/claude.exe'
        for digest, expected in (('a'*64,True),('b'*64,False)):
            state = {'hosts':{'claude':{'cli':{'executable':exe,'sha256':digest}}}}
            with patch.object(owned,'read_regular',return_value=json.dumps(state).encode()), \
                 patch.object(catalog,'executable_hash',return_value='a'*64), patch.object(catalog.shutil,'which',return_value=None):
                found = [x for x in catalog.discover() if x['tool']=='claude' and x['supported']]
            self.assertEqual(bool(found),expected)

    def test_codex_discovery_keeps_its_existing_bundle_receipt_contract(self):
        state={'hosts':{'codex':{'cli':{'executable':'C:/ProgramData/private/codex.exe'}}}}
        with patch.object(owned,'read_regular',return_value=json.dumps(state).encode()), \
             patch.object(catalog,'executable_hash',return_value='a'*64),patch.object(catalog.shutil,'which',return_value=None):
            self.assertEqual([x['tool'] for x in catalog.discover()],['codex'])

    def test_initialize_alone_gets_registry_read_and_version_probe_stays_zero(self):
        from mrh.adapters.platforms import windows_lpac
        binding = {'tool':'claude','id':'claude-test','executable':'C:/private/claude.exe',
                   'executable_sha256':'a'*64,'version':'2.1.303 (Claude Code)'}
        requested = []
        class Sandbox:
            work = Path('C:/private space/runtime')
            def capture(self, args, **kwargs):
                if args == ['--version']: return b'2.1.303 (Claude Code)\n'
                request = json.loads(kwargs['input'])
                frame = {'type':'control_response','response':{'request_id':request['request_id'],
                    'subtype':'success','response':{'models':[{'value':'opus','displayName':'Opus'}]}}}
                kwargs['until']((json.dumps(frame)+'\n').encode())
        @contextmanager
        def isolated(_, **kwargs):
            requested.append(kwargs.get('capabilities', ())); yield Sandbox()
        with patch.object(windows_lpac,'isolated',side_effect=isolated), \
             patch.object(claude,'executable_hash',return_value='a'*64):
            result = claude.ClaudeCatalog().refresh(binding)
        self.assertEqual([m.id for m in result.models],['opus'])
        self.assertEqual(requested,[(),('registryRead',)])

    def test_describe_uses_lpac_and_detects_image_change(self):
        from mrh.adapters.platforms import windows_lpac
        candidate = {'tool':'claude','executable':'C:/private/claude.exe'}
        class Sandbox:
            def capture(self,args,**kwargs): return b'2.1.303 (Claude Code)\n'
        @contextmanager
        def isolated(_): yield Sandbox()
        with patch.object(windows_lpac,'isolated',side_effect=isolated), \
             patch.object(claude,'executable_hash',side_effect=['a'*64,'b'*64]):
            with self.assertRaisesRegex(CatalogError,'tool_changed_rebind_required'):
                claude.ClaudeCatalog().describe(candidate)


if __name__ == '__main__': unittest.main()
