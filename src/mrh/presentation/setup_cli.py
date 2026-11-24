"""`mrh setup` and `mrh update`: the installation commands for a user who has no checkout.

`mrh setup` runs the installer copy kept inside the installed generation. That copy never builds or
downloads: it checks, enables, rolls back and removes what is already there. `mrh update` fetches a
published release with git and runs that release's own `./setup` with the arguments recorded for this
installation, so a new version is always installed by its own installer.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from mrh.infrastructure import owned, temporary
from mrh.infrastructure.execution import GENERATION_ENV

REPOSITORY = 'https://github.com/Hugo0904/model-routing-harness.git'
RELEASE = re.compile(r'^refs/tags/(v(\d+)\.(\d+)\.(\d+))$')


class SetupCommandError(ValueError):
    pass


def generation():
    """The generation this process was started from; the entry point records it before any source is swapped in."""
    value = os.environ.get(GENERATION_ENV)
    if not value:
        raise SetupCommandError('not_an_installed_generation:use_the_checkout_setup')
    root = owned.canonical_path(Path(value))
    if not (root / 'generation.json').is_file():
        raise SetupCommandError('not_an_installed_generation:use_the_checkout_setup')
    return root


def installer(root):
    path = root / 'installer/mrh_setup.py'
    if not path.is_file():
        # Generations built before this command existed, and Windows generations, carry no installer copy.
        raise SetupCommandError('installer_not_in_this_generation:use_the_checkout_setup')
    owned.read_regular(path, 16_000_000)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('mrh_setup', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['mrh_setup'] = module
    spec.loader.exec_module(module)
    return module


def setup(arguments, stderr):
    try:
        root = generation()
        module = installer(root)
    except (SetupCommandError, owned.OwnedError, OSError) as exc:
        stderr.write('mrh: ' + str(exc) + '\n')
        return 2
    arguments = list(arguments)
    if '--prefix' not in arguments:
        # <prefix>/setup-state/generations/<id>: act on the installation this command belongs to.
        arguments = ['--prefix', str(root.parents[2]), *arguments]
    return module.main(arguments, installed=True)


def release_tags(source, run=subprocess.run):
    """Published release tags of `source`, newest last. Only vMAJOR.MINOR.PATCH counts as a release."""
    try:
        listed = run(['git', 'ls-remote', '--tags', '--refs', str(source), 'v*'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise SetupCommandError('git_unavailable') from None
    if listed.returncode:
        raise SetupCommandError('release_list_unavailable')
    found = []
    for line in listed.stdout.splitlines():
        match = RELEASE.match(line.split('\t')[-1].strip())
        if match:
            found.append((tuple(int(match[i]) for i in (2, 3, 4)), match[1]))
    return [tag for _, tag in sorted(found)]


def recorded_arguments(root):
    """The `./setup` arguments that reproduce this installation with a new version."""
    control = root.parents[1]
    state = json.loads(owned.read_regular(control / 'state.json'))
    metadata = json.loads(owned.read_regular(root / 'generation.json'))
    hosts = state['hosts']
    arguments = ['--prefix', str(root.parents[2])]
    for host in hosts:
        arguments += ['--host', host]
    # Each host keeps its recorded registration (marketplace plugin or native) without a flag.
    if hosts.get('codex', {}).get('packets'):
        arguments.append('--codex-packets')
    if metadata.get('dev_source'):
        raise SetupCommandError('development_install:update_the_checkout_and_rerun_its_setup')
    return arguments


def update(args, stdout, stderr, run=subprocess.run):
    try:
        root = generation()
        arguments = recorded_arguments(root)
        source = args.source or REPOSITORY
        tags = release_tags(source, run)
        if args.release:
            if args.release not in tags:
                raise SetupCommandError('release_not_found:' + args.release)
            tag = args.release
        elif tags:
            tag = tags[-1]
        else:
            raise SetupCommandError('no_published_release')
        from importlib import metadata
        try:
            installed = 'v' + metadata.version('model-routing-harness')
        except metadata.PackageNotFoundError:
            installed = None
        report = {'installed': installed, 'release': tag, 'source': str(source), 'setup_arguments': arguments[2:]}
        if args.check or installed == tag:
            report['status'] = 'current' if installed == tag else 'update_available'
            stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            return 0
    except (SetupCommandError, owned.OwnedError, OSError, ValueError, KeyError) as exc:
        stderr.write('mrh: ' + str(exc) + '\n')
        return 2
    scratch = temporary.mkdtemp(prefix='mrh-update-')
    try:
        checkout = Path(scratch) / 'model-routing-harness'
        cloned = run(['git', 'clone', '--quiet', '--depth', '1', '--branch', tag, str(source), str(checkout)],
                     capture_output=True, text=True, timeout=300)
        if cloned.returncode:
            stderr.write('mrh: release_fetch_failed\n')
            return 2
        # Progress goes to stderr: with --json, stdout carries only the new release's own result.
        stderr.write('MRH update: ' + (installed or 'unknown') + ' -> ' + tag + '\n')
        stderr.flush()
        return run([str(checkout / 'setup'), *arguments, *(['--json'] if args.json else [])]).returncode
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
