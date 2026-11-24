"""scripts/release_check.py：每一種檢查在一個小的假 repo 上「該失敗的會失敗」。

會被檢查當成個人內容的字串（使用者資料夾、email、SSH 位址）都在執行時拼出來，這個檔本身不含任何一筆命中。
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'release_check', Path(__file__).resolve().parents[2] / 'scripts/release_check.py')
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

MAC_HOME = '/' + 'Users' + '/alice'
LINUX_HOME = '/' + 'home' + '/alice'
WINDOWS_HOME = 'C:' + '\\Users' + '\\alice'
EMAIL = 'alice' + '@' + 'corp.io'
SSH = 'git' + '@' + 'github.com:alice/private.git'
HOOKS = {'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': '/bin/sh "${PLUGIN_ROOT}/scripts/mrh-hook" x'}]}]}}


def write(root: Path, name: str, content) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2) + '\n', encoding='utf-8')
    return path


def edit_json(root: Path, name: str, change) -> None:
    data = json.loads((root / name).read_text(encoding='utf-8'))
    change(data)
    write(root, name, data)


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = root = Path(self.temp.name).resolve()
        write(root, 'LICENSE', 'MIT License\n')
        write(root, 'pyproject.toml', '[project]\nname = "x"\nversion = "0.4.0"\n')
        write(root, 'README.md', '[![Version](https://img.shields.io/badge/version-0.4.0-2563eb)](pyproject.toml)\n')
        write(root, rc.FALLBACK_VERSION_FILE, 'try:\n    version = lookup()\nexcept Missing:\n    version = "0.4.0"\n')
        write(root, rc.CLAUDE_MARKETPLACE, {'name': rc.MARKETPLACE_NAME, 'plugins': [
            {'name': 'mrh', 'version': '1.0.0', 'source': './plugins/mrh'}]})
        write(root, rc.CODEX_MARKETPLACE, {'name': rc.MARKETPLACE_NAME, 'plugins': [
            {'name': 'mrh', 'source': {'source': 'local', 'path': './plugins/mrh'}}]})
        write(root, rc.CLAUDE_MANIFEST, {'name': 'mrh', 'version': '1.0.0'})
        write(root, rc.CODEX_MANIFEST, {'name': 'mrh', 'version': '1.0.0', 'hooks': './hooks/codex.json'})
        write(root, 'plugins/mrh/hooks/hooks.json', json.loads(json.dumps(HOOKS).replace('PLUGIN_ROOT', 'CLAUDE_PLUGIN_ROOT')))
        write(root, 'plugins/mrh/hooks/codex.json', HOOKS)
        hook = write(root, 'plugins/mrh/scripts/mrh-hook', '#!/bin/sh\nentry=$HOME/.config/x\n# see ~/.config/x and ${HOME:-}\n')
        hook.chmod(0o755)
        notice = write(root, rc.LICENSE_SNAPSHOT + '/licenses/LICENSE.sqlite.txt', 'public domain\n')
        snapshot = write(root, rc.LICENSE_SNAPSHOT + '/snapshot.json', {
            'schema_version': 1,
            'source': {'provider': 'p', 'release': 'r', 'runtime_sha256': 'a', 'licensing_sha256': 'b'},
            'files': {'licenses/LICENSE.sqlite.txt': {'sha256': rc.sha256_bytes(notice.read_bytes()), 'size': notice.stat().st_size}}})
        write(root, rc.RUNTIME_LOCK, {'provider': 'p', 'release': 'r', 'runtime': {'sha256': 'a'}, 'licensing_source': {'sha256': 'b'},
                                      'licensing_snapshot_sha256': rc.sha256_bytes(snapshot.read_bytes())})
        self.git('init', '-q')
        self.assertEqual(self.run_main('--write-plugin-lock')[0], 0)
        self.stage()

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def stage(self):
        self.git('add', '-A', '-f')
        return rc.tracked(self.root)

    def run_main(self, *argv, tags=(), account=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rc.main(list(argv), root=self.root, tags=list(tags), account=account)
        return code, out.getvalue()

    def test_clean_repo_passes_and_a_missing_release_tag_is_only_a_note(self):
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn('共 0 項。通過。', output)
        self.assertIn('還沒有 v* 發行標籤', output)

    def test_personal_content_is_reported_until_each_hit_is_registered(self):
        write(self.root, 'docs/notes.md', f'cd {MAC_HOME}/x\n{LINUX_HOME}\n{WINDOWS_HOME}\n{SSH}\n{EMAIL}\n'
              'ok: $HOME/x ~/x /tmp/work/home/hooks.json dev@example.com noreply@github.com\n')
        files = self.stage()
        write(self.root, 'docs/blob.bin', f'\0{MAC_HOME}')
        files = self.stage()
        found, unused, skipped = rc.check_personal(self.root, files, [])
        self.assertEqual(len(found), 5, found)
        self.assertEqual(skipped, ['docs/blob.bin'])                  # 二進位檔沒掃，要講出來
        self.assertTrue(all(item.startswith('`docs/notes.md:') for item in found))
        allow = [('docs/notes.md', 'email', rc.sha256_text(EMAIL)), ('docs/notes.md', 'email', rc.sha256_text('gone'))]
        found, unused, _ = rc.check_personal(self.root, files, allow)
        self.assertEqual(len(found), 4)                               # 登記的那一筆不再算
        self.assertEqual(len(unused), 1)                              # 擋不到任何命中的登記要刪
        write(self.root, rc.ALLOW_FILE, {'entries': [{'file': 'docs/notes.md', 'kind': 'email', 'sha256': EMAIL, 'reason': 'x'},
                                                     {'file': 'docs', 'kind': 'folder', 'sha256': 'a' * 64, 'reason': 'x'}]})
        self.assertEqual(len(rc.load_allow(self.root)[1]), 2)         # 抄出原文、整個資料夾的登記都不收
        self.assertEqual(self.run_main()[0], 1)

    def test_plugin_structure_rejects_portable_manifest_remote_source_and_wrong_names(self):
        write(self.root, 'plugin.json', {'name': 'mrh'})
        write(self.root, 'plugins/mrh/plugin.json', {'name': 'mrh'})
        edit_json(self.root, rc.CLAUDE_MARKETPLACE, lambda d: d['plugins'][0].update(source={'source': 'url', 'url': 'https://x.invalid/r.git', 'ref': 'v1'}))
        edit_json(self.root, rc.CODEX_MARKETPLACE, lambda d: d.update(name='other'))
        edit_json(self.root, rc.CODEX_MANIFEST, lambda d: d.update(name='other', hooks='./hooks/missing.json'))
        (self.root / 'plugins/mrh/scripts/mrh-hook').unlink()
        found = '\n'.join(rc.check_structure(self.root, self.stage()))
        for expected in ('`plugin.json`：不得有可攜格式', '`plugins/mrh/plugin.json`：不得有可攜格式', '不得用 url 加 ref',
                         '市集名要是 model-routing-harness', 'name 要是 mrh', 'hooks/missing.json', '`scripts/mrh-hook` 不在外掛資料夾裡'):
            self.assertIn(expected, found)
        (self.root / rc.CODEX_MANIFEST).unlink()
        self.assertIn('沒有進版控', '\n'.join(rc.check_structure(self.root, self.stage())))

    def test_program_and_plugin_versions_are_compared_as_two_groups(self):
        files = self.stage()
        self.assertEqual(rc.check_versions(self.root, files, ['v0.4.0', 'v0.3.9', 'nightly']), ([], []))
        found, notes = rc.check_versions(self.root, files, ['v0.4.0', 'v0.10.0'])
        self.assertEqual((len(found), notes), (1, []))
        self.assertIn('v0.10.0', found[0])                            # 最新的標籤照數字排，不是照字面
        write(self.root, 'README.md', 'https://img.shields.io/badge/version-0.3.0-blue\n')
        write(self.root, rc.FALLBACK_VERSION_FILE, 'version = "0.4.0"\nversion = "0.4.0"\n')
        edit_json(self.root, rc.CODEX_MANIFEST, lambda d: d.update(version='1.0.1'))
        found, notes = rc.check_versions(self.root, files, [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(found), 3, found)
        self.assertIn('README.md 的徽章 是 0.3.0', found[1])
        self.assertIn('備用版本', found[0])                            # 抓不到剛好一處就算違規，不靜默通過
        self.assertIn('外掛版本不一致', found[2])

    @unittest.skipIf(os.name == 'nt', '符號連結需要 POSIX')
    def test_plugin_folder_rejects_hard_coded_homes_account_name_and_symlinks(self):
        self.assertEqual(rc.check_plugin_static(self.root, 'alice'), [])   # $HOME、~/ 與 /bin/sh 不算
        write(self.root, 'plugins/mrh/skills/x/SKILL.md', f'run {MAC_HOME}/bin/mrh\nby Alice\n')
        os.symlink('mrh-hook', self.root / 'plugins/mrh/scripts/alias')
        found = rc.check_plugin_static(self.root, 'alice')
        self.assertEqual(len(found), 4, found)                        # 路徑一筆、帳號名兩筆（路徑裡與署名）、符號連結一筆
        self.assertEqual(len(rc.check_plugin_static(self.root, None)), 2)

    @unittest.skipIf(os.name == 'nt', '可執行位元需要 POSIX')
    def test_any_change_inside_the_plugin_folder_breaks_the_lock(self):
        plugin = self.root / 'plugins/mrh'
        self.assertEqual(rc.check_plugin_lock(self.root, {}), [])
        (plugin / 'empty').mkdir()
        write(self.root, 'plugins/mrh/.DS_Store', 'x')
        (plugin / 'scripts/mrh-hook').chmod(0o644)
        write(self.root, 'plugins/mrh/hooks/codex.json', {'hooks': {}})
        (plugin / 'hooks/hooks.json').unlink()
        found = rc.check_plugin_lock(self.root, {})
        self.assertEqual(len(found), 6, found)
        for expected in ('--write-plugin-lock', '調外掛版本', 'Codex 使用者要重新信任'):
            self.assertIn(expected, found[0])
        self.assertEqual([item.split('：')[1][:3] for item in found[1:]], ['多出來', '多出來', '變了（', '不見了', '變了（'])

        code, output = self.run_main('--write-plugin-lock')
        self.assertEqual(code, 1)                                     # 內容變了、外掛版本沒調：不寫
        self.assertIn('沒有寫入', output)
        self.assertEqual(len(rc.check_plugin_lock(self.root, {})), 6)
        for name in (rc.CLAUDE_MANIFEST, rc.CODEX_MANIFEST):
            edit_json(self.root, name, lambda d: d.update(version='1.0.1'))
        edit_json(self.root, rc.CLAUDE_MARKETPLACE, lambda d: d['plugins'][0].update(version='1.0.1'))
        code, output = self.run_main('--write-plugin-lock')
        self.assertEqual(code, 0, output)
        self.assertIn('Codex 使用者要重新信任', output)
        self.assertEqual(rc.check_plugin_lock(self.root, {}), [])
        self.assertEqual(rc.plugin_versions(self.root)[rc.LOCK_FILE], '1.0.1')

        edit_json(self.root, rc.LOCK_FILE, lambda d: d['entries'].pop())
        self.assertIn('不手改', rc.check_plugin_lock(self.root, {})[0])
        (self.root / rc.LOCK_FILE).unlink()
        self.assertIn('還沒有登記', rc.check_plugin_lock(self.root, {})[0])

    def test_license_and_third_party_snapshot_must_match_their_recorded_hashes(self):
        prefix = rc.LICENSE_SNAPSHOT + '/'
        write(self.root, prefix + 'licenses/LICENSE.sqlite.txt', 'edited\n')
        write(self.root, prefix + 'licenses/LICENSE.extra.txt', 'extra\n')
        (self.root / 'LICENSE').unlink()
        found = '\n'.join(rc.check_licenses(self.root, self.stage()))
        for expected in ('`LICENSE`：沒有進版控', 'LICENSE.sqlite.txt`：大小或雜湊', 'LICENSE.extra.txt`：進了版控，但不在'):
            self.assertIn(expected, found)
        edit_json(self.root, prefix + 'snapshot.json', lambda d: d['files'].clear())
        self.assertIn('licensing_snapshot_sha256 不一致', '\n'.join(rc.check_licenses(self.root, self.stage())))

    def test_files_that_must_not_be_tracked_are_reported(self):
        for name in ('docs/.DS_Store', 'runtime/out.json', 'pkg/dist/a.whl', 'state.db', 'x/cache.sqlite3-wal',
                     'workspace-allowlist.local.json'):
            write(self.root, name, 'x')
        found = rc.check_tracked(self.stage())
        self.assertEqual(len(found), 6, found)                        # 授權快照裡的 LICENSE.sqlite.txt 不是資料庫檔
        self.assertEqual(self.run_main()[0], 1)


if __name__ == '__main__':
    unittest.main()
