"""Test-suite guard: no test may reach TypeSafe, whatever credential the machine holds.

The classifier transport is always injected in tests. The model-list transport is not injected by menu tests, so it is
disabled here; `fetch` turns the refusal into an ordinary "network" failure and callers fall back to their cache.
"""
import atexit
import os
import shutil
import tempfile

from mrh.adapters.providers import typesafe_models as _models

# Anything a test writes under the state directory (the Jev version cache, reports) goes to a throw-away directory.
_state = tempfile.mkdtemp(prefix="mrh-test-state-")
os.environ[_models.STATE_ENV] = _state
atexit.register(shutil.rmtree, _state, ignore_errors=True)


def _refuse(self, headers, timeout):
    raise OSError("tests must not use the network")


_models.HttpModelsTransport.get = _refuse
