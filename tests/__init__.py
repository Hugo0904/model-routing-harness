"""Test-suite guard: no test may reach TypeSafe, whatever credential the machine holds.

The classifier transport is always injected in tests. The model-list transport is not injected by menu tests, so it is
disabled here; `fetch` turns the refusal into an ordinary "network" failure and callers fall back to their cache.
"""
import atexit
import os
import shutil
import tempfile

from mrh.adapters.providers import typesafe_models as _models

# MRH refuses paths that go through a symlink, and the default macOS temporary directory does (/var is a link to
# /private/var). Give the whole run one private, link-free directory so tests pass whatever TMPDIR is set to.
_root = os.path.realpath(tempfile.mkdtemp(prefix="mrh-tests-"))
os.environ["TMPDIR"] = _root
tempfile.tempdir = _root
atexit.register(shutil.rmtree, _root, ignore_errors=True)

# Anything a test writes under the state directory (the Jev version cache, reports) goes to a throw-away directory.
_state = tempfile.mkdtemp(prefix="mrh-test-state-")
os.environ[_models.STATE_ENV] = _state
os.environ['MRH_PROJECT_ROOT'] = _state
os.environ['HOME'] = _state
os.environ['USERPROFILE'] = _state
os.environ['CODEX_HOME'] = os.path.join(_state, 'codex-home')
os.environ.pop('TYPESAFE_API_KEY', None)


def _refuse(self, headers, timeout):
    raise OSError("tests must not use the network")


_models.HttpModelsTransport.get = _refuse
