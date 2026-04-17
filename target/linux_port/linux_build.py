#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from profile_paths import build_dir_name_for_defconfig, resolve_build_dir


SCRIPT_FOLDER = Path(__file__).resolve().parent
COMPILER_BIN = (SCRIPT_FOLDER / '../../compilers/bin').resolve()
LINUX_TREE = SCRIPT_FOLDER / 'linux'
DEFAULT_VIRT_DEFCONFIG_NAME = 'little64_defconfig'
DEFAULT_MACHINE = 'litex'
DEFAULT_DEBUG_KCFLAGS = '-O2 -g -fno-omit-frame-pointer -fno-optimize-sibling-calls'
MACHINE_DEFCONFIGS = {
    'virt': DEFAULT_VIRT_DEFCONFIG_NAME,
    'litex': 'little64_litex_sim_defconfig',
}
DEFAULT_DEFCONFIG_NAME = MACHINE_DEFCONFIGS[DEFAULT_MACHINE]


@dataclass(frozen=True, slots=True)
class BuildRequest:
    machine: str | None
    defconfig_name: str
    build_dir: Path
    defconfig_path: Path
    target: str
    make_args: tuple[str, ...]
    debug_kconfig_args: tuple[str, ...]
    debug_cflag_args: tuple[str, ...]


def default_defconfig_for_machine(machine: str) -> str:
    try:
        return MACHINE_DEFCONFIGS[machine]
    except KeyError as exc:
        raise ValueError(f'Unsupported machine profile: {machine}') from exc


def parse_args(argv: Sequence[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description='Build the Little64 Linux kernel with machine-aware defconfig selection.',
    )
    parser.add_argument(
        '--machine',
        choices=sorted(MACHINE_DEFCONFIGS),
        default=None,
        help='Select a known machine profile and its default defconfig.',
    )
    parser.add_argument(
        '--defconfig',
        default=None,
        help='Explicit Little64 defconfig name. Overrides --machine defaults.',
    )
    parser.add_argument(
        '--build-dir',
        type=Path,
        default=None,
        help='Explicit kernel build directory. Overrides the profile-derived location.',
    )
    parser.add_argument(
        'target',
        nargs='?',
        default=None,
        help='Kernel make target to build. Defaults to vmlinux when omitted.',
    )
    args, make_args = parser.parse_known_args(argv)
    return args, make_args


def resolve_defconfig_name(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> str:
    environment = env or os.environ
    if args.defconfig:
        return args.defconfig
    if args.machine:
        return default_defconfig_for_machine(args.machine)
    return environment.get('LITTLE64_LINUX_DEFCONFIG', DEFAULT_DEFCONFIG_NAME)


def _has_parallel_arg(make_args: Sequence[str]) -> bool:
    return any(arg == '-j' or arg.startswith('-j') for arg in make_args)


def _debug_kconfig_args(make_args: Sequence[str]) -> tuple[str, ...]:
    if any(
        arg.startswith('CONFIG_DEBUG_INFO=') or
        arg.startswith('CONFIG_DEBUG_INFO_NONE=') or
        arg.startswith('CONFIG_DEBUG_INFO_DWARF')
        for arg in make_args
    ):
        return ()
    return (
        'CONFIG_DEBUG_INFO=y',
        'CONFIG_DEBUG_INFO_NONE=n',
        'CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT=y',
    )


def _debug_cflag_args(make_args: Sequence[str], env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    environment = env or os.environ
    if any(arg.startswith('KCFLAGS=') or arg.startswith('KBUILD_CFLAGS=') for arg in make_args):
        return ()
    return (f"KCFLAGS={environment.get('LITTLE64_KERNEL_DEBUG_CFLAGS', DEFAULT_DEBUG_KCFLAGS)}",)


def resolve_build_request(
    args: argparse.Namespace,
    make_args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> BuildRequest:
    environment = env or os.environ
    defconfig_name = resolve_defconfig_name(args, environment)
    build_dir_override = str(args.build_dir) if args.build_dir is not None else None
    build_dir = resolve_build_dir(
        defconfig_name,
        linux_port_root=SCRIPT_FOLDER,
        build_dir_override=build_dir_override,
    )
    resolved_make_args = list(make_args)
    if not _has_parallel_arg(resolved_make_args):
        resolved_make_args.insert(0, f'-j{os.cpu_count() or 1}')

    return BuildRequest(
        machine=args.machine,
        defconfig_name=defconfig_name,
        build_dir=build_dir,
        defconfig_path=SCRIPT_FOLDER / 'linux' / 'arch' / 'little64' / 'configs' / defconfig_name,
        target=args.target or 'vmlinux',
        make_args=tuple(resolved_make_args),
        debug_kconfig_args=_debug_kconfig_args(resolved_make_args),
        debug_cflag_args=_debug_cflag_args(resolved_make_args, environment),
    )


def _make_base_command(build_dir: Path, cc_cmd: Path | str) -> list[str]:
    return [
        'nice',
        '-n',
        '19',
        'make',
        '-C',
        str(LINUX_TREE),
        'ARCH=little64',
        'LLVM=1',
        f'CC={cc_cmd}',
        f'LD={COMPILER_BIN / "ld.lld"}',
        f'AR={COMPILER_BIN / "llvm-ar"}',
        f'OBJCOPY={COMPILER_BIN / "llvm-objcopy"}',
        f'O={build_dir}',
        'HOSTCC=gcc',
        'HOSTCXX=g++',
    ]


def _current_defconfig_sha(defconfig_path: Path) -> str:
    return subprocess.check_output(['sha256sum', str(defconfig_path)], text=True).split()[0]


def _read_text_if_exists(path: Path) -> str:
    if not path.is_file():
        return ''
    return path.read_text(encoding='utf-8').strip()


def _needs_defconfig_sync(request: BuildRequest, defconfig_stamp: Path, defconfig_name_stamp: Path) -> bool:
    if request.target in {'clean', 'mrproper'}:
        return False
    if not (request.build_dir / '.config').is_file():
        return True
    return (
        _current_defconfig_sha(request.defconfig_path) != _read_text_if_exists(defconfig_stamp) or
        request.defconfig_name != _read_text_if_exists(defconfig_name_stamp)
    )


def _resolve_cc_command(env: dict[str, str]) -> tuple[Path | str, dict[str, str]]:
    resolved_env = env.copy()
    clang_path = COMPILER_BIN / 'clang'
    if resolved_env.get('LITTLE64_CLANG_GUARD', '0') == '1':
        resolved_env['LITTLE64_REAL_CLANG'] = str(clang_path)
        return SCRIPT_FOLDER / 'clang_guard.sh', resolved_env
    return clang_path, resolved_env


def _print_summary(request: BuildRequest, cc_cmd: Path | str) -> None:
    print('Building Linux kernel for Little64')
    if request.machine:
        print(f'Machine profile: {request.machine}')
    print(f'Defconfig: {request.defconfig_name}')
    print(f'Build directory name: {build_dir_name_for_defconfig(request.defconfig_name)}')
    if str(cc_cmd).endswith('clang_guard.sh'):
        print(f'Using compiler: {cc_cmd} (guarded)')
        print(f'Guard timeout: {os.environ.get("LITTLE64_CLANG_TIMEOUT_SEC", "120")}s')
        print(f'Guard max virtual memory: {os.environ.get("LITTLE64_CLANG_MAX_VMEM_KB", "10485760")} KB')
    else:
        print(f'Using compiler: {cc_cmd}')
    print(f'Target: {request.target}')
    print(f'Build directory: {request.build_dir}')
    if request.debug_cflag_args:
        print(f'Kernel C flags: {request.debug_cflag_args[0].split("=", 1)[1]}')
    else:
        print('Kernel C flags: caller-provided')
    print('-----------------------------------')


def run_build(request: BuildRequest, env: Mapping[str, str] | None = None) -> int:
    if not request.defconfig_path.is_file():
        print(f'error: Little64 defconfig not found: {request.defconfig_path}', file=sys.stderr)
        return 1

    request.build_dir.mkdir(parents=True, exist_ok=True)
    effective_env = dict(env or os.environ)
    cc_cmd, effective_env = _resolve_cc_command(effective_env)
    _print_summary(request, cc_cmd)

    defconfig_stamp = request.build_dir / '.little64_defconfig.sha256'
    defconfig_name_stamp = request.build_dir / '.little64_defconfig.name'
    if _needs_defconfig_sync(request, defconfig_stamp, defconfig_name_stamp):
        print(f'Syncing kernel config from arch/little64/configs/{request.defconfig_name}')
        subprocess.run(
            [*_make_base_command(request.build_dir, cc_cmd), request.defconfig_name],
            check=True,
            env=effective_env,
        )
        defconfig_stamp.write_text(_current_defconfig_sha(request.defconfig_path) + '\n', encoding='utf-8')
        defconfig_name_stamp.write_text(request.defconfig_name + '\n', encoding='utf-8')

    subprocess.run(
        [
            *_make_base_command(request.build_dir, cc_cmd),
            *request.make_args,
            *request.debug_cflag_args,
            *request.debug_kconfig_args,
            request.target,
        ],
        check=True,
        env=effective_env,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args, make_args = parse_args(argv)
    request = resolve_build_request(args, make_args)
    return run_build(request)


if __name__ == '__main__':
    raise SystemExit(main())