"""Stable command entry; implementation is loaded only when invoked."""
from __future__ import annotations

from typing import Any, Sequence


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    from mrh.presentation.cli import main as command_main
    return command_main(
        argv, stdin=stdin, stdout=stdout, stderr=stderr,
    )
