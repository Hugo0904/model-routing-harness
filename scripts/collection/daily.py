"""Local, opt-in Codex dispatch collection. No networking or model calls.

Native hooks cannot inspect encrypted message equality. Preserve that limitation
in every receipt; the parent's pre-dispatch capture is an attestation, not a
host-verified plaintext export. Unknown/missing captures never count.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import time
import uuid

MAX_BYTES = 65536
MAX_STAGES = 64  # Retain originals; refuse more captures rather than delete them.
MAX_METADATA = 256
MAX_CONTEXTS = 64
CONTEXT_TTL = 86400
HOOK_SECONDS = 1.0
SPOOL_OWNER = 'org.model-routing-harness.daily-spool.v1'
TOOLS = {'spawn_agent', 'collaborationspawn_agent', 'collaboration.spawn_agent'}
FIELDS = {'task_name', 'message', 'agent_type', 'model', 'reasoning_effort', 'fork_turns'}
SECRET = re.compile(r'(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[a-z0-9_-]{16,}|\b(?:gh[pousr]_|github_pat_)[a-z0-9_]{16,}|\bAKIA[A-Z0-9]{16}\b|(?:password|passwd|api[_-]?key|access[_-]?token|authorization)\s*[=:]\s*[\"\']?[^\s\"\']{8,}|https?://[^\s]+[?&](?:token|key|secret)=)')
CIPHER = re.compile(r'^gAAAA[A-Za-z0-9_=-]{60,}$')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def private(path, directory=False):
    st = path.lstat()
    if (not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
            or st.st_uid != os.getuid() or st.st_mode & 0o077
            or (not directory and st.st_nlink != 1)):
        raise ValueError('unsafe_owned_path')


def read(path):
    private(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('metadata_too_large')
    with path.open() as stream:
        return json.load(stream)


def write(path, value):
    if path.exists() or path.is_symlink():
        private(path)
    # One bounded recovery slot. A killed writer cannot accumulate temp files.
    temp = path.with_name('.' + path.name + '.collector-next')
    if temp.exists() or temp.is_symlink():
        private(temp)  # abandoned owned scratch only; never promote partial JSON
        temp.unlink()
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            os.unlink(temp)


def publish_request(path, source):
    """Publish complete exact bytes exclusively; never stream into an original."""
    private(path.parent, True)
    temp = path.with_name('.' + path.name + '.collector-next')
    # A kill between exclusive link and scratch removal leaves precisely these
    # two names for one inode. Only that verifiable topology permits cleanup.
    if (path.exists() or path.is_symlink()) and (temp.exists() or temp.is_symlink()):
        a, b = path.lstat(), temp.lstat()
        if (stat.S_ISREG(a.st_mode) and stat.S_ISREG(b.st_mode)
                and a.st_uid == b.st_uid == os.getuid() and not (a.st_mode | b.st_mode) & 0o077
                and a.st_nlink == b.st_nlink == 2 and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)):
            if path.read_bytes() != source:
                raise ValueError('durable_capture_changed')
            temp.unlink()
    if path.exists() or path.is_symlink():
        private(path)
        if path.read_bytes() != source:
            raise ValueError('durable_capture_changed')
        return
    if temp.exists() or temp.is_symlink():
        private(temp)
        temp.unlink()  # owned incomplete scratch, never an original
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path, follow_symlinks=False)  # fails rather than overwriting
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def locked(root, *, blocking=True):
    private(root, True)
    fd = os.open(root / '.collector.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private(root / '.collector.lock')
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


def valid_request(req):
    return (isinstance(req, dict) and not set(req) - FIELDS
            and all(isinstance(req.get(k), str) and req[k].strip() for k in ('task_name', 'message'))
            and all(isinstance(v, str) for v in req.values())
            and len(json.dumps(req).encode()) <= MAX_BYTES
            and not CIPHER.fullmatch(req['message']))


class CollectorExpired(TimeoutError):
    pass


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise CollectorExpired()


def notice(event, text):
    if not isinstance(event, dict) or event.get('hook_event_name') not in ('PreToolUse', 'PostToolUse', 'UserPromptSubmit'):
        return {}
    return {'systemMessage': text, 'hookSpecificOutput': {'hookEventName': event['hook_event_name'], 'additionalContext': text}}


def add_notice(result, event, text):
    prior = result.get('hookSpecificOutput', {}).get('additionalContext')
    output = notice(event, text)
    if prior and output:
        output['hookSpecificOutput']['additionalContext'] = prior + '\n' + text
    result.update(output)
    return result


class Collector:
    def __init__(self, config):
        self.config_path = Path(config)
        self.config = read(self.config_path)
        self.root = Path(self.config['dataset'])
        private(self.root, True)
        self.spool = Path(self.config['spool_root'])
        if self.spool.absolute() != self.spool.resolve():
            raise ValueError('unsafe_spool_path')
        private(self.spool, True)
        if read(self.spool / 'owner.json') != {'owner': SPOOL_OWNER, 'config': str(self.config_path.resolve())}:
            raise ValueError('unowned_spool')

    def index(self):
        value = read(self.root / 'collection.json')
        if len(value['samples']) != value['count']:
            raise ValueError('index_count_mismatch')
        return value

    def active(self, index):
        return self.config.get('enabled') is True and index['count'] < index['target']

    def allowed(self, cwd):
        path = Path(cwd).resolve()
        return any(path == Path(r).resolve() or Path(r).resolve() in path.parents
                   for r in self.config['workspace_roots'])

    def state(self):
        path = self.spool / 'collector-state.json'
        value = read(path) if path.exists() else {'stages': {}, 'bindings': {}, 'events': {}, 'notice_sent': False}
        value.setdefault('contexts', {})
        return value

    def save(self, state):
        for name in ('events', 'bindings'):
            state[name] = dict(list(state[name].items())[-MAX_METADATA:])
        state['last_run_at'] = time.time()
        write(self.spool / 'collector-state.json', state)

    def capture_root(self):
        path = self.spool / 'captures'
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)  # No parents=True, chmod, or followed symlink.
        private(path, True)
        return path

    def context_root(self):
        path = self.spool / 'prompt-contexts'
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        private(path, True)
        return path

    def turn_context(self, event, state):
        turn = event.get('turn_id')
        if not isinstance(turn, str) or not turn:
            return None
        root = self.context_root()
        key = digest(event['session_id'] + '\0' + turn + '\0' + str(Path(event['cwd']).resolve()))
        for old in list(state['contexts']):
            row = state['contexts'][old]
            if time.time() - row['created_at'] > CONTEXT_TTL or (old != key and len(state['contexts']) >= MAX_CONTEXTS):
                path = root / (old + '.json')
                if not re.fullmatch(r'[0-9a-f]{64}', old):
                    raise ValueError('invalid_context_id')
                private(path)
                path.unlink()  # Only recorded ephemeral hook metadata, never capture originals.
                del state['contexts'][old]
        if key not in state['contexts'] and len(list(root.iterdir())) >= MAX_CONTEXTS:
            return None
        value = {'source': event['hook_event_name'], 'session': event['session_id'], 'turn': turn,
                 'cwd': str(Path(event['cwd']).resolve()), 'created_at': time.time()}
        path = root / (key + '.json')
        write(path, value)
        state['contexts'][key] = {**value, 'fingerprint': digest(json.dumps(value, sort_keys=True))}
        return path

    def reminder(self, event, state):
        # Native app_tool_send_message/continuation turns need not run
        # UserPromptSubmit. Use the first ordinary tool as a non-blocking
        # fallback, once per native turn, without retaining that tool's input.
        turn = event.get('turn_id')
        if not isinstance(turn, str) or not turn:
            return {}
        key = digest(event['session_id'] + '\0' + turn + '\0' + str(Path(event['cwd']).resolve()))
        prior = state['contexts'].get(key)
        if prior and time.time() - prior['created_at'] <= CONTEXT_TTL:
            return {}
        context = self.turn_context(event, state)
        if context is None:
            return notice(event, 'MRH 未取得可用的本回合原生 context；本回合不收集，原工作照常。')
        self.save(state)
        return {'hookSpecificOutput': {'hookEventName': event['hook_event_name'],
                                       'additionalContext': self.instructions(context)}}

    def stage_context(self, path, state, session, cwd):
        path = Path(path)
        root = self.context_root()
        if path.parent != root or not re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
            raise ValueError('invalid_prompt_context')
        value = read(path)
        recorded = state['contexts'].get(path.stem)
        if (not recorded or value.get('source') not in ('UserPromptSubmit', 'PreToolUse')
                or digest(json.dumps(value, sort_keys=True)) != recorded['fingerprint']
                or value['session'] != session or value['cwd'] != str(Path(cwd).resolve())
                or time.time() - value['created_at'] > CONTEXT_TTL):
            raise ValueError('prompt_context_mismatch')
        return value

    def capture(self, key, row):
        return self.capture_bytes(key, row)[0]

    def capture_bytes(self, key, row):
        if not re.fullmatch(r'[0-9a-f]{32}', key):
            raise ValueError('invalid_capture_id')
        parent = self.capture_root() / key
        private(parent, True)
        path = parent / 'request.json'
        if str(path) != row['path']:
            raise ValueError('capture_path_changed')
        private(path)
        if path.stat().st_size > 2_000_000:
            raise ValueError('metadata_too_large')
        source = path.read_bytes()
        req = json.loads(source)
        if not valid_request(req) or digest(json.dumps(req, sort_keys=True, ensure_ascii=False)) != row['fingerprint']:
            raise ValueError('capture_changed')
        return req, source

    def durable_target(self, capture, *, create=False):
        if not re.fullmatch(r'[0-9a-f]{32}', capture):
            raise ValueError('invalid_capture_id')
        root = self.root / 'captures'
        target = root / capture
        for path in (root, target):
            if not path.exists() and not path.is_symlink():
                if not create:
                    return None
                path.mkdir(mode=0o700)
            private(path, True)
        return target

    def receipt(self, key, binding, row, stored, source, agent, observed):
        if (key != digest(binding['session'] + '\0' + binding['call'])
                or row['session'] != binding['session'] or row['turn'] != binding['turn']
                or not self.allowed(row['cwd']) or binding['session'] in self.config.get('excluded_threads', [])
                or binding['equality'] not in ('verified_plaintext', 'unobservable_ciphertext')
                or not all(isinstance(binding.get(k), str) and binding[k] for k in ('session', 'call', 'turn'))
                or not isinstance(agent, str) or not agent
                or type(observed) not in (int, float) or not math.isfinite(observed) or observed <= 0):
            raise ValueError('receipt_source_mismatch')
        capture = binding['capture']
        canonical = 'captures/' + capture + '/request.json'
        return {'capture_id': capture, 'source_thread_id': binding['session'], 'source_turn_id': binding['turn'],
            'dispatch_call_id': binding['call'], 'native_agent_reference': agent,
            'task_name': stored['task_name'], 'task_name_sha256': digest(stored['task_name']),
            'message_sha256': digest(stored['message']), 'message_utf8_bytes': len(stored['message'].encode()),
            'saved_before_dispatch': True, 'capture_source': 'parent_pre_dispatch_attestation',
            'native_body_equality': binding['equality'], 'actual_model': None, 'actual_effort': None,
            'requested_profile': {k: stored.get(k) for k in ('agent_type','model','reasoning_effort')},
            'observed_success_time': observed, 'success_time_source': 'local PostToolUse observation',
            'route_adoption_eligible': False, 'counts_as_new_sample': True,
            'request_file_sha256': hashlib.sha256(source).hexdigest(),
            'canonical_message_source': canonical + '#/message', 'canonical_task_name_source': canonical + '#/task_name'}

    def commit_receipt(self, index, state, key, binding, receipt, source):
        matches = [sample for sample in index['samples'] if sample.get('capture_id') == binding['capture']
            or (sample.get('dispatch_call_id') == binding['call'] and sample.get('source_thread_id') == binding['session'])]
        if matches and (len(matches) != 1 or matches[0] != receipt):
            raise ValueError('receipt_index_conflict')
        if not matches and not self.active(index):
            return
        target = self.durable_target(binding['capture'], create=True)
        # The durable success fact precedes any request scratch/publication.
        path = target / 'receipt.json'
        if path.exists() or path.is_symlink():
            if read(path) != receipt:
                raise ValueError('durable_receipt_changed')
        else:
            write(path, receipt)
        publish_request(target / 'request.json', source)
        if not matches:
            index['samples'].append(receipt)
            index['count'] = len(index['samples'])
            index['stopped_at_target'] = index['count'] >= index['target']
            index['status'] = 'ready_for_review' if index['stopped_at_target'] else 'collecting'
            write(self.root / 'collection.json', index)
        state['stages'][binding['capture']]['status'] = 'counted'
        state['events'][key] = {'status': 'counted'}
        self.save(state)

    def recover_receipts(self, index, state, deadline):
        """Only known pending bindings; no directory scan or inferred success."""
        fault = False
        for key, binding in state['bindings'].items():
            row = state['stages'].get(binding.get('capture'))
            if row is None or row['status'] == 'counted' or state['events'].get(key, {}).get('status') == 'not_collected':
                continue
            check_deadline(deadline)
            try:
                target = self.durable_target(binding['capture'])
                if target is None or not ((target / 'receipt.json').exists() or (target / 'receipt.json').is_symlink()):
                    continue  # native success not persisted: unknown, never count
                receipt = read(target / 'receipt.json')
                stored, source = self.capture_bytes(binding['capture'], row)
                expected = self.receipt(key, binding, row, stored, source,
                    receipt.get('native_agent_reference'), receipt.get('observed_success_time'))
                if receipt != expected:
                    raise ValueError('durable_receipt_mismatch')
                self.commit_receipt(index, state, key, binding, receipt, source)
            except (ValueError, OSError, KeyError, TypeError):
                fault = True  # preserve conflicting originals; continue other known units
        return fault

    def stage(self, req, *, session, cwd, natural, safe, context=None):
        if not session or not natural or not safe:
            raise ValueError('native_session_and_natural_safe_attestation_required')
        if not valid_request(req):
            raise ValueError('invalid_request')
        if SECRET.search(json.dumps(req, ensure_ascii=False)):
            raise ValueError('sensitive_input_excluded')
        with locked(self.spool):
            index = self.index()
            if not self.active(index):
                return {'status': 'collection_stopped', 'count': index['count']}
            if not self.allowed(cwd) or session in self.config.get('excluded_threads', []):
                return {'status': 'scope_excluded'}
            state = self.state()
            if context is None:
                raise ValueError('native_prompt_context_required')
            native_context = self.stage_context(context, state, session, cwd)
            fingerprint = digest(json.dumps(req, sort_keys=True, ensure_ascii=False))
            # A failed/retried dispatch reuses its original capture, never another sample.
            for key, row in state['stages'].items():
                if row['session'] == session and row['fingerprint'] == fingerprint:
                    return {'status': 'already_staged', 'capture_id': key, 'request_path': row['path']}
            captures = self.capture_root()
            if len(state['stages']) >= MAX_STAGES or len(list(captures.iterdir())) >= MAX_STAGES:
                return {'status': 'capture_capacity_reached', 'limit': MAX_STAGES,
                        'retention': 'Originals retained; continue the task without collection. No automatic deletion.'}
            key = uuid.uuid4().hex  # capture ID only, never a native identity
            directory = captures / key
            directory.mkdir(mode=0o700)
            target = directory / 'request.json'
            write(target, req)
            os.chmod(target, 0o400)
            state['stages'][key] = {'session': session, 'cwd': str(Path(cwd).resolve()),
                'turn': native_context['turn'], 'prompt_context': str(context),
                'created_at': time.time(), 'fingerprint': fingerprint, 'path': str(target),
                'task_name': req['task_name'], 'status': 'prepared'}
            self.save(state)
            return {'status': 'prepared', 'capture_id': key, 'request_path': str(target)}

    def instructions(self, context):
        command = ' '.join(shlex.quote(x) for x in [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                   '--config', str(self.config_path), 'stage', '--context', str(context), '--natural', '--safe-to-store'])
        return ("MRH 本機跨聊天樣本收集已啟用，只附帶收集原本就需要的真實新委派。"
                "不要為收集建立任務、不要等待湊滿、不要改模型或略過其他保護。"
                "在原本確定要呼叫 collaboration.spawn_agent 前，把即將傳給工具的完整 JSON "
                "(task_name/message 及實際使用的其他參數) 原樣經 stdin 傳給：\n" + command +
                "\n使用安全的 quoted heredoc；依回傳 request_path 的原字串派工，不改寫、不補尾端換行。"
                "原文含憑證或敏感原始資料就跳過收集，不把它傳入 stage，不改寫後冒稱原文。"
                "--natural/--safe-to-store 是派工者對真實必要任務與可保存內容的確認。"
                "收集器本身的開發/測試、合成測試、續作/重試都不算新樣本。"
                "不為收集單獨請求權限；不可寫入或收集失敗就繼續原任務並如實說明。"
                "工具成功後由 Hook 自動計數，不需 A/B/C 窗口轉交；滿額自動停止。"
                "本版只接一般聊天的 root 派工；子代理內再委派可能使用父 session，尚未接入，不猜父 ID。"
                "若 Hook 未觸發，不宣稱樣本已計入；任何外送仍需真人同意。")

    def cheap_context(self, event):
        """Atomic state/context reads only; no dataset lock or capture scan."""
        if (event.get('hook_event_name') != 'PreToolUse' or event.get('tool_name') in TOOLS
                or self.config.get('enabled') is not True or not isinstance(event.get('turn_id'), str)):
            return False
        state = self.state()
        if any(state['events'].get(key, {}).get('status') != 'counted'
               and state['stages'].get(binding.get('capture'), {}).get('status') != 'counted'
               for key, binding in state['bindings'].items()):
            return False  # a previous Post may still need durable index recovery
        key = digest(event['session_id'] + '\0' + event['turn_id'] + '\0' + str(Path(event['cwd']).resolve()))
        row = state['contexts'].get(key)
        if not row or time.time() - row.get('created_at', 0) > CONTEXT_TTL:
            return False
        path = self.spool / 'prompt-contexts' / (key + '.json')
        private(path.parent, True)
        value = read(path)
        return (value.get('source') in ('UserPromptSubmit', 'PreToolUse') and value.get('session') == event['session_id']
                and value.get('turn') == event['turn_id'] and value.get('cwd') == str(Path(event['cwd']).resolve())
                and digest(json.dumps(value, sort_keys=True)) == row.get('fingerprint'))

    def hook(self, event, *, deadline=None):
        deadline = time.monotonic() + HOOK_SECONDS if deadline is None else deadline
        try:
            return self._hook(event, deadline)
        except (BlockingIOError, CollectorExpired):
            return notice(event, 'MRH 本次未收錄：收集器忙碌或時間已到；原工作繼續，請簡短告知使用者，不重試原工具。')

    def _hook(self, event, deadline):
        if not isinstance(event, dict):
            return {}
        phase = event.get('hook_event_name')
        session, cwd = event.get('session_id'), event.get('cwd')
        if not isinstance(session, str) or not isinstance(cwd, str) or not self.allowed(cwd):
            return {}
        if session in self.config.get('excluded_threads', []):
            return {}
        check_deadline(deadline)
        if self.cheap_context(event):
            return {}
        with locked(self.spool, blocking=False), locked(self.root, blocking=False):
            check_deadline(deadline)
            index = self.index()
            state = self.state()
            if self.recover_receipts(index, state, deadline):
                return notice(event, 'MRH 已保存資料不符或暫不可恢復；本次未宣稱收錄，原工作繼續，請簡短告知使用者，不重試原工具。')
            if not self.active(index):
                if index['count'] >= index['target'] and not state['notice_sent']:
                    state['notice_sent'] = True
                    self.save(state)
                    return {'systemMessage': 'MRH 樣本已收齊，收集已停止；請回原收集聊天檢視，尚未外送或呼叫比較服務。'}
                return {}
            if phase == 'UserPromptSubmit':
                result = self.reminder(event, state)
                state['last_prompt_hook_at'] = time.time()
                self.save(state)
                return result
            if phase not in ('PreToolUse', 'PostToolUse'):
                return {}
            call = event.get('tool_use_id')
            req = event.get('tool_input')
            turn = event.get('turn_id')
            if not isinstance(call, str) or not call or not isinstance(turn, str) or not turn or not isinstance(req, dict):
                return {}
            result = self.reminder(event, state) if phase == 'PreToolUse' else {}
            if event.get('tool_name') not in TOOLS:
                return result
            key = digest(session + '\0' + call)
            if key in state['events'] and state['events'][key]['status'] == 'counted':
                return {}
            if phase == 'PreToolUse':
                choices = []
                for capture, row in state['stages'].items():
                    check_deadline(deadline)
                    if (row['status'] != 'prepared' or row['session'] != session
                            or row.get('turn') != turn
                            or row['cwd'] != str(Path(cwd).resolve())
                            or time.time() - row['created_at'] > 86400):
                        continue
                    stored = self.capture(capture, row)
                    if any(stored.get(k) != req.get(k) for k in FIELDS - {'message'}):
                        continue
                    message = req.get('message')
                    if not isinstance(message, str):
                        continue
                    cipher = bool(CIPHER.fullmatch(message))
                    if not cipher and message != stored['message']:
                        continue
                    choices.append((capture, 'unobservable_ciphertext' if cipher else 'verified_plaintext'))
                if len(choices) == 1:
                    capture, equality = choices[0]
                    state['bindings'][key] = {'capture': capture, 'equality': equality,
                         'session': session, 'call': call, 'turn': event.get('turn_id'), 'bound_at': time.time()}
                else:
                    state['events'][key] = {'status': 'not_collected', 'reason': 'missing_or_ambiguous_pre_capture',
                        'pre_capture_status': 'missing' if not state['stages'] else 'unmatched_or_ambiguous',
                        'reminder_timing': 'at_dispatch' if 'hookSpecificOutput' in result else 'before_dispatch_or_unavailable'}
                self.save(state)
                # Never deny or modify a native dispatch.
                if len(choices) != 1:
                    add_notice(result, event, 'MRH 本次委派未收錄：沒有唯一的事前 stage。'
                        '原工作照常；下次自然派工前先 stage，不重試已成功的委派。')
                return result
            binding = state['bindings'].get(key)
            if not binding:
                self.save(state)
                return {}
            if binding['turn'] != turn:
                return {}
            response = event.get('tool_response')
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except ValueError:
                    response = None
            if (not isinstance(response, dict) or response.get('error') or response.get('isError')
                    or response.get('status') in ('failed', 'cancelled', 'error')):
                state['events'][key] = {'status': 'not_collected', 'reason': 'no_success_receipt'}
                self.save(state)
                return {}
            agent = response.get('agent_id') or response.get('task_name')
            if not isinstance(agent, str) or not agent:
                state['events'][key] = {'status': 'not_collected', 'reason': 'no_native_agent_identity'}
                self.save(state)
                return {}
            capture = binding['capture']
            row = state['stages'][capture]
            stored, source_bytes = self.capture_bytes(capture, row)
            if any(stored.get(k) != req.get(k) for k in FIELDS - {'message'}):
                return {}
            if not CIPHER.fullmatch(str(req.get('message', ''))) and req.get('message') != stored['message']:
                return {}
            receipt = self.receipt(key, binding, row, stored, source_bytes, agent, time.time())
            check_deadline(deadline)
            self.commit_receipt(index, state, key, binding, receipt, source_bytes)
            if index['stopped_at_target']:
                state['notice_sent'] = True
            self.save(state)
            suffix = '已收齊並停止收集；尚未外送或啟動比較。' if index['stopped_at_target'] else '原工作照常繼續，無需等待其他窗口。'
            return {'systemMessage': f"MRH 本機樣本已登錄 {index['count']}/{index['target']}；" + suffix}


def main(argv=None):
    started = time.monotonic()
    value = None
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--managed-by-mrh-daily-collector', action='store_true')
    sub = parser.add_subparsers(dest='operation', required=True)
    stage = sub.add_parser('stage')
    stage.add_argument('--natural', action='store_true')
    stage.add_argument('--safe-to-store', action='store_true')
    stage.add_argument('--context', required=True)
    sub.add_parser('hook')
    sub.add_parser('status')
    args = parser.parse_args(argv)
    try:
        collector = Collector(args.config)
        if args.operation == 'status':
            with locked(collector.spool):
                index, state = collector.index(), collector.state()
                result = {'count': index['count'], 'target': index['target'], 'configured_enabled': collector.config.get('enabled') is True,
                          'collection_open': collector.active(index), 'native_hook_trust': 'unverified; review exact definitions via official /hooks',
                          'pending_stages': sum(s['status'] != 'counted' for s in state['stages'].values()),
                          'capture_capacity': MAX_STAGES, 'metadata_limit_per_kind': MAX_METADATA,
                          'last_prompt_hook_at': state.get('last_prompt_hook_at'),
                          'last_run_at': state.get('last_run_at'),
                          'not_collected': sum(e['status'] != 'counted' for e in state['events'].values())}
        else:
            data = sys.stdin.buffer.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('input_too_large')
            value = json.loads(data)
            if args.operation == 'stage':
                result = collector.stage(value, session=os.environ.get('CODEX_THREAD_ID'), cwd=os.getcwd(),
                                         natural=args.natural, safe=args.safe_to_store, context=args.context)
            else:
                result = collector.hook(value, deadline=started + HOOK_SECONDS)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        # No exception messages: parser/OS errors could contain task data or paths.
        if args.operation == 'hook':
            print(json.dumps(notice(value, 'MRH 本機收集暫時失敗，原工作照常繼續；未宣稱收集成功，請簡短告知使用者，不重試原工具。')))
            return 0
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
