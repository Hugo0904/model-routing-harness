"""Gemini public ACP parser/payload binding/CAS, no provider responses mocked."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from mrh.infrastructure import settings
from mrh.infrastructure.bindings import Registry, BindingError
from mrh.adapters.catalogs.catalog import Catalog, CatalogError, Model, ToolCatalog, describe_tool, executable_hash, installation_hash
from mrh.adapters.catalogs.gemini_catalog import GeminiCatalog, installation, parse_initialize, parse_session, _unique


class GeminiCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mrh-gemini-check-', dir='/private/tmp')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name).resolve()
        prefix = self.root / 'prefix'; self.package = prefix / 'lib/node_modules/@google/gemini-cli'
        (self.package / 'bundle').mkdir(parents=True); (prefix / 'bin').mkdir()
        self.entry = self.package / 'bundle/gemini.js'; self.entry.write_text('#!/usr/bin/env node\n// fixture only\n'); self.entry.chmod(0o755)
        self.chunk = self.package / 'bundle/chunk.js'; self.chunk.write_text('// public bundle fixture\n')
        (self.package / 'package.json').write_text(json.dumps({'name': '@google/gemini-cli', 'version': '0.63.0', 'bin': {'gemini': 'bundle/gemini.js'}}))
        shutil.copyfile('/usr/bin/true', prefix / 'bin/node'); (prefix / 'bin/node').chmod(0o755)
        probe = json.loads((Path(__file__).resolve().parents[2] / 'tests/fixtures/e16-acp-probe.json').read_text())
        self.init, self.session = [copy.deepcopy(x) for x in probe['cases'][-1]['received'][:2]]

    def candidate(self):
        return {'tool': 'gemini', 'executable': str(self.entry), 'label': 'Gemini fixture', 'supported': True}

    def test_actual_public_reply_keeps_alias_request_id_and_never_uses_modes_as_effort(self):
        parse_initialize(self.init); models = parse_session(self.session)
        self.assertEqual(models[0].id, 'auto')
        self.assertEqual(models[1].id, 'gemini-3.1-pro-preview-customtools')
        self.assertEqual(models[1].label, 'gemini-3.1-pro-preview')
        self.assertTrue(all(m.efforts == () and m.resolved_model is None for m in models))

    def test_invalid_initialize_version_identity_and_error_fail_closed(self):
        for kind in ('version', 'identity', 'bool', 'error'):
            value = copy.deepcopy(self.init)
            if kind == 'version': value['result']['agentInfo']['version'] = 'unknown-version'
            elif kind == 'identity': value['id'] = 99
            elif kind == 'bool': value['id'] = True
            else: value['error'] = {'message': 'PRIVATE_CANARY'}
            with self.assertRaises(CatalogError) as error: parse_initialize(value)
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_partial_duplicate_unsafe_effort_error_and_unrecognized_fields_refuse(self):
        for kind in ('missing', 'duplicate', 'unsafe', 'effort', 'empty', 'current', 'id', 'error'):
            value = copy.deepcopy(self.session); rows = value['result']['models']['availableModels']
            if kind == 'missing': del value['result']['models']
            elif kind == 'duplicate': rows.append(copy.deepcopy(rows[0]))
            elif kind == 'unsafe': rows[0]['modelId'] = 'sk-PRIVATE_CANARY'
            elif kind == 'effort': rows[0]['approvalMode'] = 'high'
            elif kind == 'empty': rows.clear()
            elif kind == 'current': value['result']['models']['currentModelId'] = 'not-in-list'
            elif kind == 'id': value['id'] = True
            else: value['error'] = {'code': -32000, 'message': 'PRIVATE_CANARY'}
            with self.assertRaises(CatalogError) as error: parse_session(value)
            self.assertNotIn('PRIVATE', str(error.exception))
        with self.assertRaises(ValueError): json.loads('{"id":1,"id":2}', object_pairs_hook=_unique)

    def test_stub_unchanged_chunk_or_node_update_changes_installation_identity(self):
        stub = executable_hash(self.entry); before = installation(self.entry)
        self.chunk.write_text('// updated public payload\n')
        self.assertEqual(executable_hash(self.entry), stub)
        after = installation(self.entry); self.assertNotEqual(after['sha256'], before['sha256'])
        node = after['node']; node.write_bytes(node.read_bytes() + b'node update fixture')
        self.assertNotEqual(installation(self.entry)['sha256'], after['sha256'])

    def test_external_payload_link_and_unknown_version_are_not_adopted(self):
        outside = self.root / 'outside'; outside.write_text('PRIVATE_CANARY')
        (self.package / 'external').symlink_to(outside)
        with self.assertRaises(CatalogError): installation(self.entry)
        (self.package / 'external').unlink()
        p = self.package / 'package.json'; value = json.loads(p.read_text()); value['version'] = 'unknown'; p.write_text(json.dumps(value))
        with self.assertRaises(CatalogError): GeminiCatalog().describe(self.candidate())

    def test_common_dispatch_advertised_scope_and_payload_mismatch_stop_refresh(self):
        candidate = describe_tool(self.candidate()); binding = dict(candidate, id='fixture')
        with patch('mrh.adapters.catalogs.gemini_catalog.acquire', return_value=parse_session(self.session)) as acquire:
            result = ToolCatalog().refresh(binding)
            self.assertEqual(result.assurance, 'tool-advertised'); self.assertEqual(result.scope, binding['executable_sha256'])
            self.assertEqual(acquire.call_count, 1)
            self.chunk.write_text('// changed\n')
            with self.assertRaisesRegex(CatalogError, 'tool_changed_rebind_required'): ToolCatalog().refresh(binding)
            self.assertEqual(acquire.call_count, 1)

    def test_save_revalidates_whole_package_and_cancel_history_policy_stays_equal(self):
        registry = Registry(self.root / 'registry'); candidate = describe_tool(self.candidate())
        binding = registry.associate(candidate, expected_revision=0); path = Path(binding['settings_path'])
        snapshot = Catalog(binding['id'], 'gemini', binding['executable_sha256'], binding['version'],
                           'synthetic:gemini-fixture', time.time(), (Model('auto', 'Auto', ()),), assurance='synthetic')
        registry.record_refresh(binding, snapshot,expected_revision=registry.read()['revision']); current = registry.read()['bindings'][0]
        initial = settings.read(path); before = path.read_bytes(); self.chunk.write_text('// update\n')
        with self.assertRaisesRegex(BindingError, 'tool_changed_rebind_required'):
            registry.save(current, initial, initial['policy'], snapshot, 'auto')
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((path.parent / 'events.sqlite3').exists())
        self.assertNotEqual(installation_hash('gemini', self.entry), current['executable_sha256'])


if __name__ == '__main__': unittest.main()
