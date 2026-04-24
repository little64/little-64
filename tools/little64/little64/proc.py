"""Consistent subprocess wrapper for little64 tooling.

Every tool shell-out in the CLI should go through :func:`run` so failures get
user-facing context, verbose mode can echo commands, and dry-run mode is
honored uniformly. Replaces scattered ``subprocess.run(..., check=True)``
call sites and the narrow ``build_support.run_checked`` helper.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


class CommandError(RuntimeError):
    """Raised when a checked subprocess invocation fails.

    Carries the ``context`` string passed in by the caller so upstream handlers
    can report *why* the command was run, not just what exited non-zero.
    """

    def __init__(self, context: str, returncode: int, command: Sequence[str]) -> None:
        self.context = context
        self.returncode = returncode
        self.command = list(command)
        rendered = " ".join(shlex.quote(part) for part in self.command)
        message = f"{context} (rc={returncode}): {rendered}" if context else f"command failed (rc={returncode}): {rendered}"
        super().__init__(message)


def _coerce_argv(command: Sequence[str | Path]) -> list[str]:
    return [str(arg) for arg in command]


def _verbose_enabled() -> bool:
    return os.environ.get("LITTLE64_VERBOSE") == "1"


def _dry_run_enabled() -> bool:
    return os.environ.get("LITTLE64_DRY_RUN") == "1"


def _echo(prefix: str, argv: Sequence[str], cwd: Path | str | None = None) -> None:
    rendered = " ".join(shlex.quote(part) for part in argv)
    location = f" (cwd={cwd})" if cwd else ""
    print(f"{prefix} {rendered}{location}", file=sys.stderr)


def run(
    command: Sequence[str | Path],
    *,
    context: str = "",
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with consistent logging and error reporting.

    Honors ``LITTLE64_VERBOSE=1`` (echo the command) and ``LITTLE64_DRY_RUN=1``
    (echo and skip, returning a zero-return placeholder). When ``check`` is
    true and the process exits non-zero, raises :class:`CommandError` with the
    supplied ``context``.
    """
    argv = _coerce_argv(command)

    if _verbose_enabled() or _dry_run_enabled():
        prefix = "[dry-run]" if _dry_run_enabled() else "[run]"
        _echo(prefix, argv, cwd)

    if _dry_run_enabled():
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    completed = subprocess.run(
        argv,
        cwd=None if cwd is None else str(cwd),
        env=None if env is None else dict(env),
        check=False,
        timeout=timeout,
        capture_output=capture_output,
        text=capture_output,
    )

    if check and completed.returncode != 0:
        raise CommandError(context, completed.returncode, argv)

    return completed


def run_with_env_source(
    command: Sequence[str | Path],
    *,
    cwd: Path | str,
    source_script: Path | None = None,
    context: str = "",
    check: bool = True,
) -> int:
    """Run ``command`` after optionally ``source``-ing a shell script.

    Used for Vivado, which requires a ``settings64.sh`` to be sourced before
    ``vivado`` is on ``PATH``. On Windows (no POSIX ``source``) the script is
    ignored.
    """
    argv = _coerce_argv(command)

    if source_script is not None and sys.platform not in ("win32", "cygwin"):
        shell_cmd = (
            f"source {shlex.quote(str(source_script))} && "
            + " ".join(shlex.quote(part) for part in argv)
        )
        shell_argv = ["bash", "-lc", shell_cmd]
        if _verbose_enabled() or _dry_run_enabled():
            _echo("[dry-run]" if _dry_run_enabled() else "[run]", shell_argv, cwd)
        if _dry_run_enabled():
            return 0
        rc = subprocess.run(shell_argv, cwd=str(cwd), check=False).returncode
    else:
        if _verbose_enabled() or _dry_run_enabled():
            _echo("[dry-run]" if _dry_run_enabled() else "[run]", argv, cwd)
        if _dry_run_enabled():
            return 0
        rc = subprocess.run(argv, cwd=str(cwd), check=False).returncode

    if check and rc != 0:
        raise CommandError(context, rc, argv)
    return rc


def capture_stdout(
    command: Sequence[str | Path],
    *,
    context: str = "",
    cwd: Path | str | None = None,
) -> str:
    """Run ``command`` and return its decoded stdout; fails fast on non-zero exit."""
    completed = run(command, context=context, cwd=cwd, capture_output=True, check=True)
    return completed.stdout


def which_or_none(name: str) -> Path | None:
    """Thin wrapper so call-sites don't have to ``import shutil`` themselves."""
    resolved = shutil.which(name)
    return Path(resolved) if resolved else None
