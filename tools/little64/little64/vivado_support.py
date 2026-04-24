from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from little64 import proc
from little64.proc import CommandError


def vivado_settings_script_from_env() -> Path | None:
    settings_root = os.environ.get('LITEX_ENV_VIVADO')
    if not settings_root:
        return None
    return Path(settings_root) / 'settings64.sh'


def run_command_with_optional_source(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    source_script: Path | None = None,
) -> int:
    return proc.run_with_env_source(
        command,
        cwd=cwd,
        source_script=source_script,
        context='command with optional sourced env',
        check=False,
    )


def run_vivado_batch(
    tcl_path: Path,
    *,
    cwd: Path,
    source_script: Path | None = None,
) -> None:
    import sys

    if sys.platform in ('win32', 'cygwin'):
        command: list[str | Path] = ['cmd', '/c', f'vivado -mode batch -source {tcl_path.name}']
    else:
        command = ['vivado', '-mode', 'batch', '-source', tcl_path.name]

    try:
        proc.run_with_env_source(
            command,
            cwd=cwd,
            source_script=source_script,
            context=f'Vivado batch {tcl_path.name}',
            check=True,
        )
    except CommandError as exc:
        raise SystemExit(str(exc)) from exc
