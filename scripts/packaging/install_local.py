#!/usr/bin/env python3
"""Retired shared-app replacement entry. Use the host-aware checkout installer."""
import sys

if __name__ == '__main__':
    print('MRH: install_local.py no longer replaces the shared app/interpreter. '
          'From the checkout run ./setup --host codex (or --host claude); '
          'use ./setup --dry-run --host codex to preview. No files were changed.', file=sys.stderr)
    raise SystemExit(2)
