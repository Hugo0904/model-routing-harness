"""Short numbered model selection over the owned registry and existing writer."""
import copy
import os
import select as io_select
import textwrap
from datetime import datetime, timezone

from . import catalog, settings
from .bindings import BindingError, Registry
from .catalog import Catalog, CatalogError
from .settings_schema import SettingsError
from .terminal import policy_rows, render_configuration, render_policy_review, render_choices, sanitize_text


class Cancelled(Exception):
    pass


class Back(Exception):
    pass


def select(root, tier, *, stdin, stdout, width, color, bind=False, associate=None,
           provider=None, discovery=None, describe=None):
    if not getattr(stdin, 'isatty', lambda: False)():
        stdout.write('Model selection needs an interactive terminal. No changes saved.\n')
        return 2
    provider = provider or catalog.CodexCatalog()
    discovery = discovery or catalog.discover
    describe = describe or catalog.describe_tool
    registry = Registry(root)
    width = max(24, min(140, width))

    def note(text):
        stdout.write(textwrap.fill(sanitize_text(text), width=width-4,
                                  initial_indent='  ', subsequent_indent='  ')+'\n')

    def ask(prompt):
        note(prompt+' [back / cancel]');stdout.write('  > ');stdout.flush()
        raw = stdin.readline(1026)
        stdout.write('\n')
        if not raw or raw.strip().lower() == 'cancel':raise Cancelled()
        if len(raw) > 1024:raise BindingError('selection_invalid')
        answer = raw.strip().lower()
        if answer == 'back':raise Back()
        return answer

    def choose(title, items, current=None):
        try:fd = stdin.fileno()
        except (AttributeError, OSError):fd = None
        if fd is not None and os.isatty(fd):
            import termios
            import tty
            focus = next((i for i,(_,v) in enumerate(items) if v == current), 0)
            before = termios.tcgetattr(fd)
            def draw(replace=False):
                rows = [('> ' if i == focus else '  ')+f'{i+1}. {label}'+
                        (' [current]' if value == current else '') for i,(label,value) in enumerate(items)]
                frame = render_choices(title, rows, width=width, color=color)
                if replace:stdout.write('\x1b['+str(len(frame.splitlines()))+'A')
                stdout.write(frame);stdout.write('  > ');stdout.flush()
            note('Up/Down: select. Enter: confirm. Left: back. Esc: cancel. Numbers are optional.')
            try:
                tty.setcbreak(fd);draw();digits = ''
                while True:
                    key = os.read(fd, 1)
                    if not key or key == b'\x03':raise Cancelled()
                    if key in (b'\r',b'\n'):
                        if digits:
                            number = int(digits)
                            if not 1 <= number <= len(items):digits = '';continue
                            focus = number-1
                        return items[focus][1]
                    if key.isdigit():digits = (digits+key.decode())[-3:];continue
                    digits = ''
                    if key != b'\x1b':continue
                    if not io_select.select([fd], [], [], .15)[0]:raise Cancelled()
                    second = os.read(fd, 1)
                    if second not in (b'[',b'O'):raise Cancelled()
                    if not io_select.select([fd], [], [], .15)[0]:raise Cancelled()
                    code = os.read(fd, 1)
                    if code == b'D':raise Back()
                    if code in (b'A',b'B'):
                        focus = (focus+(-1 if code == b'A' else 1)) % len(items);draw(True)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, before)
                stdout.write('\n')
        # Explicit in-process fixtures can use number/text input. They are not
        # evidence of real keyboard interaction; the PTY walkthrough is.
        rows = [f'{i+1}. {label}'+(' [current]' if value == current else '') for i,(label,value) in enumerate(items)]
        stdout.write(render_choices(title, rows, width=width, color=color))
        while True:
            answer = ask('Choose a number'+(' [Enter keeps current]' if current is not None else ''))
            if not answer and current is not None and any(v == current for _,v in items):return current
            if answer.isdigit() and 1 <= int(answer) <= len(items):return items[int(answer)-1][1]
            if answer and any(v == answer for _,v in items):return answer
            note('Choose one of the listed numbers; model names are not entered here.')

    def refresh(binding):
        try:
            snapshot = provider.refresh(binding)
            if type(snapshot) is not Catalog:raise CatalogError('catalog_invalid')
            registry.record_refresh(binding, snapshot)
            return snapshot
        except CatalogError as exc:
            reason = str(exc) if str(exc).replace('_','').isalnum() else 'catalog_refresh_failed'
            registry.record_refresh(binding, error=reason)
            note('Model list unavailable: '+reason+'. No model is marked retired by this failure.')
            last = next(b for b in registry.read()['bindings'] if b['id'] == binding['id'])['catalog']
            if last is not None:
                old = Catalog.from_dict(last)
                note('Last successful list (display only; cannot select or save): '+
                     datetime.fromtimestamp(old.fetched_at, timezone.utc).isoformat())
                stdout.write(render_choices('LAST SUCCESS  /  DISPLAY ONLY',
                    [m.label+' ('+m.id+')' for m in old.models], width=width, color=color))
            return None

    try:
        value = registry.read()
        if bind or not value['bindings']:
            candidates = discovery()
            if not candidates:
                note('No supported installed tool found. No binding created. Codex public model/list is required; Claude/Gemini catalogs are unsupported.')
                return 2
            while True:
                index = choose('FIRST USE  /  choose an installed tool', [
                    (c['label']+(' (catalog unsupported)' if not c['supported'] else ''), str(i))
                    for i,c in enumerate(candidates)])
                candidate = candidates[int(index)]
                if candidate['supported']:break
                note(candidate['label']+': no implemented reliable non-secret CLI catalog/binding source. No profile created.')
            candidate = describe(candidate)
            note(candidate['label']+' / '+candidate['version'])
            note('This creates an MRH profile, not an account login or working routing. Models are tool-advertised; account access is unconfirmed. No Hook is activated.')
            if associate is not None:
                settings.read(associate)
                note('Associate the explicit existing owned settings file: '+str(associate)+'; values are retained.')
            if choose('CONFIRM MRH PROFILE', [('Bind this MRH profile','bind'),('Cancel; leave unchanged','cancel')]) != 'bind':raise Cancelled()
            binding = registry.associate(candidate, expected_revision=value['revision'], existing=associate)
            note('MRH profile bound. Policy remains unchanged until Save.')
        else:
            bindings = value['bindings']
            if len(bindings) == 1:
                binding = bindings[0];note('Loaded bound tool: '+binding['label'])
            else:
                ident = choose('BOUND TOOLS', [(b['label']+' / '+b['version'], b['id']) for b in bindings])
                binding = next(b for b in bindings if b['id'] == ident)
        registry.verify_profile(binding)
        selected_tier = tier
        while True:
            try:
                if selected_tier is None:
                    selected_tier = choose('TIER', [(t,t) for t in ('Light','Small','Mid','Top')])
                initial = settings.read(binding['settings_path'])
                policy = copy.deepcopy(initial['policy'])
                stdout.write(render_configuration(initial, width=width, color=color))
                model = effort = None
                mode = policy.get('top_mode', 'Main')
                if selected_tier == 'Top':
                    mode = choose('TOP MODE', [('Main (existing main agent; no main model setting)','Main'),
                                               ('Fixed (select a child target)','Fixed')], mode)
                    policy['top_mode'] = mode
                snapshot = refresh(binding)
                if selected_tier != 'Top' or mode == 'Fixed':
                    if snapshot is None:
                        action = choose('LIST UNAVAILABLE', [('Retry refresh','retry'),('Back','back'),('Cancel; keep policy','cancel')])
                        if action == 'cancel':raise Cancelled()
                        if action == 'back':raise Back()
                        continue
                    note('Source: '+snapshot.source+' / '+snapshot.version+' / '+snapshot.assurance)
                    note('Scope: installed tool defaults. Account access and same-call compatibility are unconfirmed.')
                    current = policy.get('fixed') if selected_tier == 'Top' else policy.get('tiers', {}).get(selected_tier)
                    current = current or {}
                    old = next((m for m in snapshot.models if m.id == current.get('model')), None)
                    if current.get('model') and (old is None or old.state != 'available'):
                        state = 'confirmed retired: '+old.retirement_ref if old and old.state == 'retired' else 'unavailable in this list/scope; global retirement is unconfirmed'
                        note('Saved model '+current['model']+' is '+state+'. Old settings/history remain; choose a replacement explicitly.')
                    options = [(m.label+' ('+m.id+')',m.id) for m in snapshot.models if m.state == 'available']
                    if not options:
                        note('No selectable model. Existing policy is preserved; no automatic replacement.')
                        action = choose('NO SELECTABLE MODEL', [('Retry refresh','retry'),('Back','back'),('Cancel; keep policy','cancel')])
                        if action == 'cancel':raise Cancelled()
                        if action == 'back':raise Back()
                        continue
                    model = choose(selected_tier+' MODEL', options, current.get('model') if any(v == current.get('model') for _,v in options) else None)
                    item = snapshot.option(model)
                    efforts = [('inherit (resolved effort remains unconfirmed)','inherit')]+[(e,e) for e in item.efforts]
                    current_effort = current.get('effort', 'inherit') if current.get('model') == model else 'inherit'
                    effort = choose('REASONING EFFORT', efforts, current_effort if any(v == current_effort for _,v in efforts) else 'inherit')
                    mapping = {'model': model}
                    if effort != 'inherit':mapping['effort'] = effort
                    if selected_tier == 'Top':policy['fixed'] = mapping
                    else:policy.setdefault('tiers', {})[selected_tier] = mapping
                before, after = dict(policy_rows(initial['policy'])), dict(policy_rows(policy))
                changes = [f'{t}: {before[t]} -> {after[t]}' for t in before if before[t] != after[t]]
                stdout.write(render_policy_review(changes, width=width, color=color))
                action = choose('SAVE POLICY?', [('Save this policy','save'),('Back; keep editing','back'),('Cancel; keep policy','cancel')])
                if action == 'cancel':raise Cancelled()
                if action == 'back':raise Back()
                # New successful catalog required for every model/effort save.
                # Top Main sets no model, so it can be saved even while offline.
                if model is not None:
                    checked = refresh(binding)
                    if checked is None or checked.option(model, None if effort == 'inherit' else effort) is None:
                        note('Chosen model/effort changed or refresh failed. Nothing saved; return to selection.')
                        continue
                    snapshot = checked
                saved = registry.save(binding, initial, policy, snapshot, model,
                                      None if effort == 'inherit' else effort)
                note('Saved.' if saved != initial else 'Unchanged. No settings rewrite.')
                stdout.write(render_configuration(saved, width=width, color=color))
                return 0
            except Back:
                note('Back. No policy changes saved.');selected_tier = None
    except (Cancelled, KeyboardInterrupt, Back):
        note('Cancelled. No policy changes saved.')
        return 0
    except (BindingError, CatalogError, SettingsError) as exc:
        note('Cannot save: '+str(exc)+'. Existing policy is retained; reopen the selector.')
        return 2
