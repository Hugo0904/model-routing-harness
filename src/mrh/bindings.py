"""MRH-owned bindings/catalog cache; policies stay in the existing settings file."""
import json
from pathlib import Path
import time
import uuid

from . import owned, settings
from .catalog import Catalog, CatalogError, executable_hash
from .types import safe_id, safe_model_id

FILES = {'registry.json'}
META = 'model-profile.json'


class BindingError(ValueError):
    pass


def default_root():
    return Path.home()/'.local/state/model-routing-harness/model-bindings'


def _encode(value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    if len(data) > 1048576:
        raise BindingError('registry_oversized')
    return data


class Registry:
    def __init__(self, root):
        try:self.root = owned.canonical_path(root)
        except (OSError, ValueError):raise BindingError('registry_path_invalid') from None

    def read(self):
        if not self.root.exists():
            return {'revision': 0, 'bindings': []}
        try:
            owned.verify(self.root, 'model-bindings', FILES)
            path = self.root/'registry.json'
            if not path.exists():
                return {'revision': 0, 'bindings': []}
            value = json.loads(owned.read_regular(path, 1048576), object_pairs_hook=owned._unique)
            if set(value) != {'revision', 'bindings'} or type(value['revision']) is not int or value['revision'] < 0 or type(value['bindings']) is not list or len(value['bindings']) > 64:
                raise ValueError()
            ids = set(); paths = set()
            for b in value['bindings']:
                if set(b) != {'id','tool','label','executable','executable_sha256','version','settings_path','catalog','refresh_error'}:
                    raise ValueError()
                if not all(safe_id(b[k], 256) for k in ('id','tool','executable_sha256')) or b['id'] in ids or b['settings_path'] in paths:
                    raise ValueError()
                if b['tool'] not in ('codex','claude','gemini') or not isinstance(b['label'], str) or len(b['label']) > 128 or not isinstance(b['version'], str) or len(b['version']) > 128:
                    raise ValueError()
                owned.canonical_path(b['executable']); owned.canonical_path(b['settings_path'])
                if b['catalog'] is not None:
                    self._check_catalog(b, Catalog.from_dict(b['catalog']))
                if b['refresh_error'] is not None and not safe_id(b['refresh_error']):
                    raise ValueError()
                ids.add(b['id']);paths.add(b['settings_path'])
            return value
        except (OSError, ValueError, TypeError, KeyError):
            raise BindingError('registry_unowned_or_invalid') from None

    def _check_catalog(self, binding, snapshot):
        snapshot.validate()
        if snapshot.assurance == 'account-confirmed':
            # The current public contract supplies no stable account/workspace
            # ID. Never cache an account assertion under an installation hash.
            raise BindingError('account_catalog_identity_unsupported')
        if (snapshot.binding_id, snapshot.tool, snapshot.scope, snapshot.version) != (
                binding['id'], binding['tool'], binding['executable_sha256'], binding['version']):
            raise BindingError('catalog_binding_mismatch')

    def _initialize(self):
        self.root.parent.mkdir(parents=True, exist_ok=True)
        owned.initialize(self.root, 'model-bindings', FILES)

    def associate(self, candidate, *, expected_revision, existing=None):
        """Called only after explicit profile confirmation; never silently adopt."""
        self._initialize()
        with owned.locked(self.root, 'model-bindings', FILES):
            value = self.read()
            if value['revision'] != expected_revision:
                raise BindingError('binding_conflict')
            ident = uuid.uuid4().hex
            path = owned.canonical_path(existing) if existing else self.root.parent/('mrh-profile-'+ident)/'settings.json'
            if any(b['settings_path'] == str(path) for b in value['bindings']):
                raise BindingError('profile_already_bound')
            if existing:
                settings.read(path)
            else:
                settings.init(path)
            meta = path.parent/META
            with owned.locked(path.parent, 'settings', settings.FILES):
                if meta.exists():
                    raise BindingError('profile_already_bound')
                binding = {k: candidate[k] for k in ('tool','label','executable','executable_sha256','version')}
                binding.update(id=ident, settings_path=str(path), catalog=None, refresh_error=None)
                owned.replace_owned(meta, _encode({'registry': str(self.root), 'binding_id': ident}))
                value['bindings'].append(binding);value['revision'] += 1
                owned.replace_owned(self.root/'registry.json', _encode(value))
            return self.read()['bindings'][-1]

    def verify_profile(self, binding):
        path = Path(binding['settings_path'])
        settings.read(path)
        try:
            meta = json.loads(owned.read_regular(path.parent/META), object_pairs_hook=owned._unique)
            if meta != {'registry': str(self.root), 'binding_id': binding['id']}:
                raise ValueError()
        except (OSError, ValueError):
            raise BindingError('profile_binding_mismatch') from None

    def record_refresh(self, binding, snapshot=None, error=None):
        if snapshot is not None:
            self._check_catalog(binding, snapshot)
        if error is not None and not safe_id(error):
            error = 'catalog_refresh_failed'
        with owned.locked(self.root, 'model-bindings', FILES):
            value = self.read()
            current = next((b for b in value['bindings'] if b['id'] == binding['id']), None)
            if current is None or self.identity(current) != self.identity(binding):
                raise BindingError('binding_conflict')
            if snapshot is not None:
                current['catalog'] = snapshot.public()
            current['refresh_error'] = error
            value['revision'] += 1
            owned.replace_owned(self.root/'registry.json', _encode(value))

    @staticmethod
    def identity(binding):
        return {k: v for k,v in binding.items() if k not in ('catalog','refresh_error')}

    def save(self, binding, initial, policy, snapshot, model=None, effort=None):
        """Revalidated snapshot plus binding CAS plus the existing policy writer."""
        if snapshot is not None:
            self._check_catalog(binding, snapshot)
        if model is not None and (snapshot is None or snapshot.option(model, effort) is None):
            raise BindingError('selection_changed')
        with owned.locked(self.root, 'model-bindings', FILES):
            value = self.read()
            current = next((b for b in value['bindings'] if b['id'] == binding['id']), None)
            if current is None or self.identity(current) != self.identity(binding) or (snapshot is not None and (
                    current['refresh_error'] is not None or current['catalog'] != snapshot.public())):
                raise BindingError('binding_or_catalog_conflict')
            self.verify_profile(current)
            if executable_hash(current['executable']) != current['executable_sha256']:
                raise BindingError('tool_changed_rebind_required')
            return settings.update(current['settings_path'], expected_revision=initial['revision'], policy=policy)


def target_veto(settings_path, now=None, *, synthetic=False):
    """Only negative, fresh advertised-scope facts. Never authorize an effect.

    Stale/failed/partial catalogs do not veto. Same-call compatibility remains
    owned by HostSnapshot. Missing metadata is normal for existing profiles.
    """
    try:
        path = Path(settings_path)
        meta = json.loads(owned.read_regular(path.parent/META), object_pairs_hook=owned._unique)
        if set(meta) != {'registry','binding_id'}:
            return {}
        registry = Registry(meta['registry']);value = registry.read()
        b = next((b for b in value['bindings'] if b['id'] == meta['binding_id'] and b['settings_path'] == str(path)), None)
        if b is None or b['tool'] != 'codex' or b['catalog'] is None or b['refresh_error'] is not None:
            return {}
        registry.verify_profile(b)
        c = Catalog.from_dict(b['catalog'])
        if c.assurance == 'synthetic' and not synthetic:
            return {}
        age = (time.time() if now is None else now)-c.fetched_at
        if not 0 <= age <= 300 or executable_hash(b['executable']) != b['executable_sha256']:
            return {}
        policy = settings.read(path)['policy'];result = {}
        mappings = list(policy.get('tiers', {}).values())+[policy.get('fixed', {})]
        for m in mappings:
            model = m.get('model')
            if not safe_model_id(model):continue
            option = next((x for x in c.models if x.id == model), None)
            if (option is None or option.state == 'unavailable') and c.assurance == 'synthetic' and synthetic:
                result[model] = 'catalog_model_unavailable'
            elif option is not None and option.state == 'retired':
                result[model] = 'catalog_model_retired'
            # Missing advertised defaults cannot veto an account-specific
            # model. Current trusted same-call unavailable facts still veto in
            # core. Account-scoped catalog veto needs a public identity seam.
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {}
