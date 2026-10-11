"""Short numbered model selection over the owned registry and existing writer."""
import copy
import os
import select as io_select
import textwrap
from datetime import datetime, timezone

from mrh.adapters.catalogs import catalog; from mrh.infrastructure import settings
from mrh.infrastructure.bindings import BindingError, Registry
from mrh.adapters.catalogs.catalog import Catalog, CatalogError
from mrh.infrastructure.settings_schema import SettingsError
from mrh.presentation.terminal import policy_rows, render_configuration, render_policy_review, render_choices, sanitize_text


class Cancelled(Exception):
    pass


class Back(Exception):
    pass


def select(root, tier, *, stdin, stdout, width, color, bind=False, associate=None,
           provider=None, discovery=None, describe=None):
    if not getattr(stdin, 'isatty', lambda: False)():
        stdout.write('Model selection needs an interactive terminal. No changes saved.\n')
        return 2
    provider = provider or catalog.ToolCatalog()
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
        items = list(items)
        if not any(value == 'cancel' for _,value in items):
            items.append(('Cancel; keep policy and exit','cancel'))

        def accept(value):
            if value == 'cancel':raise Cancelled()
            return value

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
                if replace:stdout.write('\r\x1b['+str(frame.count('\n'))+'A')
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
                        return accept(items[focus][1])
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
            if not answer and current is not None and any(v == current for _,v in items):return accept(current)
            if answer.isdigit() and 1 <= int(answer) <= len(items):return accept(items[int(answer)-1][1])
            if answer and any(v == answer for _,v in items):return accept(answer)
            note('Choose one of the listed numbers; model names are not entered here.')

    refresh_revision = None

    def refresh(binding):
        nonlocal refresh_revision
        expected_revision = registry.read()['revision']
        try:
            snapshot = provider.refresh(binding)
            if type(snapshot) is not Catalog:raise CatalogError('catalog_invalid')
            refresh_revision = registry.record_refresh(binding, snapshot, expected_revision=expected_revision)
            return snapshot
        except CatalogError as exc:
            reason = str(exc) if str(exc).replace('_','').isalnum() else 'catalog_refresh_failed'
            refresh_revision = registry.record_refresh(binding, error=reason, expected_revision=expected_revision)
            note('Model list unavailable: '+reason+'. No model is marked retired by this failure.')
            last = next(b for b in registry.read()['bindings'] if b['id'] == binding['id'])['catalog']
            if last is not None:
                old = Catalog.from_dict(last)
                note('Last successful list (display only; cannot select or save): '+
                     datetime.fromtimestamp(old.fetched_at, timezone.utc).isoformat())
                stdout.write(render_choices('LAST SUCCESS  /  DISPLAY ONLY',
                    [m.label+' ('+m.id+')' for m in old.models], width=width, color=color))
            return None

    drafts = {}
    binding_update_accepted = False
    resume_snapshot = None
    rebind_review = None

    def draft_for(binding):
        draft = drafts.get(binding['id'])
        if draft is None:
            initial = settings.read(binding['settings_path'])
            draft = {'initial': initial, 'policy': copy.deepcopy(initial['policy']), 'last_tier': None}
            drafts[binding['id']] = draft
        return draft

    def write_mapping(draft, selected_tier, model, effort):
        mapping = {'model': model}
        if effort != 'inherit':mapping['effort'] = effort
        if selected_tier == 'Top':draft['policy']['fixed'] = mapping
        else:draft['policy'].setdefault('tiers', {})[selected_tier] = mapping

    try:
        value = registry.read()
        candidate_mode = bind or not value['bindings']
        profile_picker_initial = not candidate_mode and len(value['bindings']) > 1
        candidates = None
        candidate_index = None
        candidate = None
        binding = None
        draft = None
        selected_tier = tier
        working = {'snapshot': None, 'model': None, 'effort': 'inherit', 'configuration_shown': False}
        if candidate_mode:
            step = 'candidate'
        elif profile_picker_initial:
            step = 'profiles'
        else:
            binding = value['bindings'][0]
            note('Loaded bound tool: '+binding['label'])
            registry.verify_profile(binding)
            draft = draft_for(binding)
            step = ('top_mode' if selected_tier == 'Top' else 'model') if selected_tier is not None else 'tier'

        while True:
            if step == 'candidate':
                if candidates is None:candidates = discovery()
                if not candidates:
                    note('No supported installed tool found. No binding created. Codex model/list and tested Claude/Gemini CLI metadata are supported; install a supported CLI in a recognized location.')
                    return 2
                try:
                    index = choose('FIRST USE  /  choose an installed tool', [
                        (c['label']+(' (catalog unsupported)' if not c['supported'] else ''), str(i))
                        for i,c in enumerate(candidates)], str(candidate_index) if candidate_index is not None else None)
                except Back:
                    raise Cancelled()
                candidate_index = int(index)
                candidate = candidates[candidate_index]
                if not candidate['supported']:
                    note(candidate['label']+': no implemented reliable non-secret CLI catalog/binding source. No profile created.')
                    continue
                candidate = describe(candidate)
                note(candidate['label']+' / '+candidate['version'])
                note('This creates an MRH profile, not an account login or working routing. Models are tool-advertised; account access is unconfirmed. No Hook is activated.')
                if associate is not None:
                    settings.read(associate)
                    note('Associate the explicit existing owned settings file: '+str(associate)+'; values are retained.')
                step = 'confirm'
                continue

            if step == 'confirm':
                try:
                    action = choose('CONFIRM MRH PROFILE', [('Bind this MRH profile','bind'),('Cancel; leave unchanged','cancel')])
                except Back:
                    step = 'candidate'
                    continue
                if action != 'bind':raise Cancelled()
                binding = registry.associate(candidate, expected_revision=value['revision'], existing=associate)
                note('MRH profile bound. Policy remains unchanged until Save.')
                value = registry.read()
                registry.verify_profile(binding)
                draft = draft_for(binding)
                selected_tier = tier
                working = {'snapshot': None, 'model': None, 'effort': 'inherit', 'configuration_shown': False}
                step = ('top_mode' if selected_tier == 'Top' else 'model') if selected_tier is not None else 'tier'
                continue

            if step == 'profiles':
                bindings = value['bindings']
                try:
                    ident = choose('BOUND TOOLS', [(b['label']+' / '+b['version'], b['id']) for b in bindings],
                                   binding['id'] if binding is not None else None)
                except Back:
                    raise Cancelled()
                binding = next(b for b in bindings if b['id'] == ident)
                registry.verify_profile(binding)
                draft = draft_for(binding)
                working = {'snapshot': None, 'model': None, 'effort': 'inherit', 'configuration_shown': False}
                if profile_picker_initial:
                    selected_tier = tier if tier is not None else draft['last_tier']
                    step = ('top_mode' if selected_tier == 'Top' else 'model') if selected_tier is not None else 'tier'
                    profile_picker_initial = False
                else:
                    selected_tier = draft['last_tier']
                    step = 'tier'
                note('Loaded bound tool: '+binding['label'])
                continue

            if step == 'tier':
                try:
                    selected_tier = choose('TIER', [(t,t) for t in ('Light','Small','Mid','Top')],
                                           selected_tier if selected_tier is not None else draft['last_tier'])
                except Back:
                    step = 'profiles'
                    continue
                draft['last_tier'] = selected_tier
                working = {'snapshot': None, 'model': None, 'effort': 'inherit', 'configuration_shown': True}
                stdout.write(render_configuration(draft['initial'], width=width, color=color))
                step = 'top_mode' if selected_tier == 'Top' else 'model'
                continue

            if step == 'top_mode':
                mode = draft['policy'].get('top_mode', 'Main')
                try:
                    mode = choose('TOP MODE', [('Main (existing main agent; no main model setting)','Main'),
                                               ('Fixed (select a child target)','Fixed')], mode)
                except Back:
                    step = 'tier'
                    continue
                draft['policy']['top_mode'] = mode
                if mode == 'Main':
                    working = {'snapshot': refresh(binding), 'model': None, 'effort': 'inherit',
                               'configuration_shown': working['configuration_shown']}
                    step = 'save'
                else:
                    working = {'snapshot': None, 'model': None, 'effort': 'inherit',
                               'configuration_shown': working['configuration_shown']}
                    step = 'model'
                continue

            if step == 'model':
                if not working['configuration_shown']:
                    stdout.write(render_configuration(draft['initial'], width=width, color=color))
                    working['configuration_shown'] = True
                snapshot = resume_snapshot or refresh(binding)
                resume_snapshot = None
                if snapshot is None:
                    step = 'unavailable'
                    continue
                note('Source: '+snapshot.source+' / '+snapshot.version+' / '+snapshot.assurance)
                note('Scope: installed tool defaults. Account access and same-call compatibility are unconfirmed.')
                policy = draft['policy']
                current = policy.get('fixed') if selected_tier == 'Top' else policy.get('tiers', {}).get(selected_tier)
                current = current or {}
                old = next((m for m in snapshot.models if m.id == current.get('model')), None)
                if current.get('model') and (old is None or old.state != 'available'):
                    unavailable_state = 'confirmed retired: '+old.retirement_ref if old and old.state == 'retired' else 'unavailable in this list/scope; global retirement is unconfirmed'
                    note('Saved model '+current['model']+' is '+unavailable_state+'. Old settings/history remain; choose a replacement explicitly.')
                elif old is not None and current.get('effort') and current['effort'] not in old.efforts:
                    note('Draft/saved reasoning effort '+current['effort']+' is unavailable in the new list. Choose a model and effort explicitly, or cancel; nothing is automatically saved.')
                options = [(m.label+' ('+m.id+')'+
                            (' [resolved: '+m.resolved_model+']' if m.resolved_model and m.resolved_model != m.id else ''),m.id)
                           for m in snapshot.models if m.state == 'available']
                if not options:
                    note('No selectable model. Existing policy is preserved; no automatic replacement.')
                    step = 'no_model'
                    continue
                try:
                    model = choose(selected_tier+' MODEL', options,
                                   current.get('model') if any(v == current.get('model') for _,v in options) else None)
                except Back:
                    step = 'top_mode' if selected_tier == 'Top' else 'tier'
                    continue
                item = snapshot.option(model)
                old_effort = current.get('effort', 'inherit')
                current_effort = old_effort if old_effort == 'inherit' or old_effort in item.efforts else 'inherit'
                write_mapping(draft, selected_tier, model, current_effort)
                working = {'snapshot': snapshot, 'model': model, 'effort': current_effort,
                           'configuration_shown': working['configuration_shown']}
                step = 'effort'
                continue

            if step == 'unavailable' or step == 'no_model':
                title = 'LIST UNAVAILABLE' if step == 'unavailable' else 'NO SELECTABLE MODEL'
                try:
                    items = [('Retry refresh','retry'),('Back','back')]
                    if step == 'unavailable':items.append(('Inspect updated installed CLI','inspect'))
                    items.append(('Cancel; keep policy','cancel'))
                    action = choose(title, items)
                except Back:
                    action = 'back'
                if action == 'back':
                    note('Back. Draft retained; nothing has been saved.')
                    step = 'top_mode' if selected_tier == 'Top' else 'tier'
                elif action == 'inspect':
                    step = 'rebind_candidate'
                else:
                    step = 'model'
                continue

            if step == 'rebind_candidate':
                baseline = registry.read()
                found = [c for c in discovery() if c['tool'] == binding['tool'] and c['supported']]
                if not found:
                    note('No supported installed '+binding['tool']+' CLI found. Original binding and policy retained.')
                    step = 'unavailable'
                    continue
                try:
                    index = choose('INSPECT UPDATED CLI', [(c['label']+' / '+c['executable'], str(i))
                                   for i,c in enumerate(found)],
                                   next((str(i) for i,c in enumerate(found) if c['executable'] == binding['executable']), None))
                    updated = describe(found[int(index)])
                    proposed = registry.candidate_binding(binding, updated)
                    snapshot = provider.refresh(proposed)
                    if type(snapshot) is not Catalog:raise CatalogError('catalog_invalid')
                    registry._check_catalog(proposed, snapshot)
                except Back:
                    step = 'unavailable'
                    continue
                except (CatalogError, BindingError) as exc:
                    note('CLI update cannot be confirmed: '+str(exc)+'. Original binding, policy and history retained. Unsupported versions require a supported CLI; Retry cannot make them supported.')
                    step = 'unavailable'
                    continue
                rebind_review = (baseline['revision'], updated, snapshot)
                step = 'rebind_review'
                continue

            if step == 'rebind_review':
                expected_revision, updated, snapshot = rebind_review
                note('Old CLI: '+binding['label']+' / '+binding['version']+' / '+binding['executable'])
                note('Old identity: '+binding['executable_sha256'])
                note('New CLI: '+updated['label']+' / '+updated['version']+' / '+updated['executable'])
                note('New identity: '+updated['executable_sha256'])
                note('Fresh catalog: '+snapshot.source+' / '+str(len(snapshot.models))+' models. Tool defaults only; account access is unconfirmed.')
                note('Confirm updates only this binding and catalog. Same profile, policy and history remain. Model edits still need Save; cancelling them later keeps this confirmed CLI update. Stored stops are not cleared.')
                try:
                    choose('CONFIRM CLI UPDATE', [('Confirm CLI update; policy still needs Save','confirm'),
                                                ('Cancel; keep old binding and policy','cancel')])
                except Back:
                    step = 'rebind_candidate'
                    continue
                binding = registry.rebind(binding, updated, snapshot, expected_revision=expected_revision)
                refresh_revision = expected_revision+1
                binding_update_accepted = True
                resume_snapshot = snapshot
                working['snapshot'] = None
                note('CLI update confirmed. Same profile and draft retained; no policy changes saved. Existing stops remain.')
                step = ('top_mode' if selected_tier == 'Top' and draft['policy'].get('top_mode', 'Main') == 'Main'
                        else 'model')
                continue

            if step == 'effort':
                snapshot = working['snapshot']
                item = snapshot.option(working['model']) if snapshot is not None else None
                if item is None:
                    note('Chosen model is no longer in this catalog. Reopen the scoped model list.')
                    step = 'model'
                    continue
                efforts = [('inherit (resolved effort remains unconfirmed)','inherit')]+[(e,e) for e in item.efforts]
                current_effort = working['effort'] if any(v == working['effort'] for _,v in efforts) else 'inherit'
                try:
                    effort = choose('REASONING EFFORT', efforts, current_effort)
                except Back:
                    note('Back. Draft retained; nothing has been saved.')
                    step = 'model'
                    continue
                working['effort'] = effort
                write_mapping(draft, selected_tier, working['model'], effort)
                step = 'save'
                continue

            if step == 'save':
                initial = draft['initial']
                policy = draft['policy']
                before, after = dict(policy_rows(initial['policy'])), dict(policy_rows(policy))
                changes = [f'{t}: {before[t]} -> {after[t]}' for t in before if before[t] != after[t]]
                stdout.write(render_policy_review(changes, width=width, color=color))
                try:
                    action = choose('SAVE POLICY?', [('Save this policy','save'),('Back; keep editing','back'),('Cancel; keep policy','cancel')])
                except Back:
                    action = 'back'
                if action == 'back':
                    note('Back. Draft retained; nothing has been saved.')
                    step = 'top_mode' if selected_tier == 'Top' and policy.get('top_mode', 'Main') == 'Main' else 'effort'
                    continue
                snapshot = working['snapshot']
                model = working['model']
                effort = working['effort']
                changed_mappings = []
                original_policy = initial['policy']
                for target in ('Light','Small','Mid','Top'):
                    before_mapping = (original_policy.get('fixed', {}) if target == 'Top' else
                                      original_policy.get('tiers', {}).get(target, {})) or {}
                    after_mapping = (policy.get('fixed', {}) if target == 'Top' else
                                     policy.get('tiers', {}).get(target, {})) or {}
                    target_model = after_mapping.get('model')
                    if after_mapping != before_mapping and target_model:
                        changed_mappings.append((target, target_model, after_mapping.get('effort')))
                if model is not None and not any(target == selected_tier for target, _, _ in changed_mappings):
                    changed_mappings.append((selected_tier, model,
                                             None if effort == 'inherit' else effort))
                # Verify every changed model choice against one new successful
                # catalog. Unchanged mappings remain untouched; Top Main with
                # no model changes can still be saved while the catalog is down.
                if changed_mappings:
                    checked = refresh(binding)
                    invalid = next((target for target, target_model, target_effort in changed_mappings
                                    if checked is None or checked.option(target_model, target_effort) is None), None)
                    if invalid is not None:
                        note('Draft model/effort for '+invalid+' changed or refresh failed. Nothing saved; return to selection.')
                        selected_tier = invalid
                        draft['last_tier'] = invalid
                        working = {'snapshot': None, 'model': None, 'effort': 'inherit',
                                   'configuration_shown': working['configuration_shown']}
                        step = ('unavailable' if checked is None else
                                'top_mode' if invalid == 'Top' and policy.get('top_mode', 'Main') == 'Main' else 'model')
                        continue
                    snapshot = checked
                try:
                    saved = registry.save(binding, initial, copy.deepcopy(policy), snapshot, model,
                                          None if effort == 'inherit' else effort, expected_revision=refresh_revision)
                except (BindingError, CatalogError) as exc:
                    if str(exc) != 'tool_changed_rebind_required':raise
                    refresh(binding)
                    step = 'unavailable'
                    continue
                note('Saved.' if saved != initial else 'Unchanged. No settings rewrite.')
                stdout.write(render_configuration(saved, width=width, color=color))
                return 0
    except (Cancelled, KeyboardInterrupt, Back):
        note('Cancelled model edits. Confirmed CLI update retained; no policy changes saved.' if binding_update_accepted
             else 'Cancelled. No policy changes saved.')
        return 0
    except (BindingError, CatalogError, SettingsError) as exc:
        note('Cannot save: '+str(exc)+'. Existing policy is retained; reopen the selector.')
        return 2
