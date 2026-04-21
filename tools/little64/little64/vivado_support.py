from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence


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
    if source_script is not None and sys.platform not in ['win32', 'cygwin']:
        shell_cmd = (
            f'source {shlex.quote(str(source_script))} && '
            + ' '.join(shlex.quote(str(arg)) for arg in command)
        )
        return subprocess.run(['bash', '-lc', shell_cmd], cwd=str(cwd), check=False).returncode

    return subprocess.run([str(arg) for arg in command], cwd=str(cwd), check=False).returncode


def run_vivado_batch(
    tcl_path: Path,
    *,
    cwd: Path,
    source_script: Path | None = None,
) -> None:
    command: list[str | Path]
    if sys.platform in ['win32', 'cygwin']:
        command = ['cmd', '/c', f'vivado -mode batch -source {tcl_path.name}']
    else:
        command = ['vivado', '-mode', 'batch', '-source', tcl_path.name]

    rc = run_command_with_optional_source(command, cwd=cwd, source_script=source_script)
    if rc != 0:
        raise SystemExit(f'Vivado command failed (rc={rc}): {tcl_path}')