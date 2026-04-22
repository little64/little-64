#!/usr/bin/env python3

from __future__ import annotations

import os
import pathlib
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / 'tools' / 'little64'
VENV_PYTHON = REPO / '.venv' / 'bin' / 'python'


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(PKG), env.get('PYTHONPATH', '')]).strip(os.pathsep)
    return env


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV_PYTHON), '-c', code],
        env=_python_env(),
        capture_output=True,
        text=True,
    )


def main() -> int:
    if not VENV_PYTHON.is_file():
        sys.stderr.write(f'missing test interpreter: {VENV_PYTHON}\n')
        return 1

    result = _run_python(
        'from pathlib import Path\n'
        'from little64.litex_boot_support import resolve_litex_machine_profile\n'
        f'repo = Path({str(REPO)!r})\n'
        'profile = resolve_litex_machine_profile(root=repo, machine="litex", env={})\n'
        'assert profile.machine == "litex"\n'
        'assert profile.cpu_variant == "standard"\n'
        'assert profile.litex_target == "arty-a7-35"\n'
        'assert profile.output_dir == repo / "builddir" / "boot-direct-litex"\n'
        'assert profile.ram_size is None\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = _run_python(
        'from pathlib import Path\n'
        'from little64.litex_boot_support import resolve_litex_machine_profile\n'
        f'repo = Path({str(REPO)!r})\n'
        'env = {\n'
        '    "LITTLE64_LITEX_OUTPUT_DIR": "/tmp/little64-custom-out",\n'
        '    "LITTLE64_LITEX_CPU_VARIANT": "standard-v3",\n'
        '    "LITTLE64_LITEX_TARGET": "sim-bootrom",\n'
        '    "LITTLE64_LITEX_RAM_SIZE": "0x2000000",\n'
        '}\n'
        'profile = resolve_litex_machine_profile(root=repo, machine="litex", env=env)\n'
        'assert profile.cpu_variant == "standard-v3"\n'
        'assert profile.litex_target == "sim-bootrom"\n'
        'assert profile.output_dir == Path("/tmp/little64-custom-out")\n'
        'assert profile.ram_size == "0x2000000"\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = _run_python(
        'from pathlib import Path\n'
        'from little64.commands.sd.artifacts import parse_args\n'
        'args = parse_args(["--machine", "litex", "--output-dir", "/tmp/out"])\n'
        'assert args.machine == "litex"\n'
        'assert args.output_dir == Path("/tmp/out")\n'
        'assert args.kernel_elf is None\n'
        'assert args.dtb is None\n'
        'assert args.sd_output is None\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = _run_python(
        'from pathlib import Path\n'
        'from little64.commands.sd.artifacts import parse_args\n'
        'args = parse_args([\n'
        '    "--kernel-elf", "k.elf",\n'
        '    "--dtb", "sys.dtb",\n'
        '    "--bootrom-output", "bootrom.bin",\n'
        '    "--sd-output", "disk.img",\n'
        '])\n'
        'assert args.machine is None\n'
        'assert args.kernel_elf == Path("k.elf")\n'
        'assert args.dtb == Path("sys.dtb")\n'
        'assert args.bootrom_output == Path("bootrom.bin")\n'
        'assert args.sd_output == Path("disk.img")\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = _run_python(
        'from pathlib import Path\n'
        'import little64.commands.boot.run as boot_run\n'
        'captured = {}\n'
        'boot_run.run_checked = lambda command: captured.setdefault("command", command)\n'
        'artifacts = boot_run._prepare_litex_artifacts(\n'
        '    kernel_elf=Path("/tmp/kernel.elf"),\n'
        '    output_dir=Path("/tmp/little64-boot-run-out"),\n'
        '    cpu_variant="standard-v3",\n'
        '    litex_target="sim-bootrom",\n'
        '    ram_size="0x2000000",\n'
        '    attach_rootfs=False,\n'
        '    rootfs_image=None,\n'
        '    python_bin="/usr/bin/python3",\n'
        ')\n'
        'command = captured["command"]\n'
        'assert command[:5] == ["/usr/bin/python3", "-m", "little64", "sd", "build"]\n'
        'assert "--machine" in command and command[command.index("--machine") + 1] == "litex"\n'
        'assert "--output-dir" in command and command[command.index("--output-dir") + 1] == "/tmp/little64-boot-run-out"\n'
        'assert "--kernel-elf" in command and command[command.index("--kernel-elf") + 1] == "/tmp/kernel.elf"\n'
        'assert "--cpu-variant" in command and command[command.index("--cpu-variant") + 1] == "standard-v3"\n'
        'assert "--litex-target" in command and command[command.index("--litex-target") + 1] == "sim-bootrom"\n'
        'assert "--boot-source" in command and command[command.index("--boot-source") + 1] == "bootrom"\n'
        'assert "--with-sdram" in command\n'
        'assert "--ram-size" in command and command[command.index("--ram-size") + 1] == "0x2000000"\n'
        'assert "--no-rootfs" in command\n'
        'assert "--dtb" not in command\n'
        'assert artifacts["dts"] == Path("/tmp/little64-boot-run-out/little64-litex-sim.dts")\n'
        'assert artifacts["dtb"] == Path("/tmp/little64-boot-run-out/little64-litex-sim.dtb")\n'
        'assert artifacts["bootrom"] == Path("/tmp/little64-boot-run-out/little64-sd-stage0-bootrom.bin")\n'
        'assert artifacts["sd"] == Path("/tmp/little64-boot-run-out/little64-linux-sdcard.img")\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = subprocess.run(
        [str(VENV_PYTHON), '-m', 'little64.cli', 'sd', 'build', '--help'],
        env=_python_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    if '--machine' not in result.stdout or '--output-dir' not in result.stdout:
        sys.stderr.write(result.stdout)
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())