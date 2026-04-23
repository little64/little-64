from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from little64 import paths
from little64.commands.kernel.build import default_defconfig_for_machine
from little64.tooling_support import python_has_module


DEFAULT_LITEX_MACHINE = 'litex'
DEFAULT_LITEX_CPU_VARIANT = 'standard'
DEFAULT_LITEX_TARGET = 'arty-a7-35'
DEFAULT_LITEX_OUTPUT_DIRNAME = 'boot-direct-litex'


REQUIRED_LITEX_KERNEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("CONFIG_MMC", "y"),
    ("CONFIG_MMC_BLOCK", "y"),
    ("CONFIG_MMC_LITEX", "y"),
    ("CONFIG_FAT_FS", "y"),
    ("CONFIG_MSDOS_FS", "y"),
    ("CONFIG_VFAT_FS", "y"),
    ("CONFIG_MSDOS_PARTITION", "y"),
    ("CONFIG_EXT4_FS", "y"),
    ("CONFIG_LITTLE64_KERNEL_PHYS_BASE", "0x40000000"),
)


@dataclass(frozen=True, slots=True)
class LitexMachineProfile:
    machine: str
    cpu_variant: str
    litex_target: str
    output_dir: Path
    ram_size: str | None


def ensure_litex_python_env(python_bin: str) -> None:
    if not python_bin or not shutil.which(python_bin) and not os.path.isfile(python_bin):
        print("error: Python interpreter not found for LiteX artifact generation", file=sys.stderr)
        print("hint: set LITTLE64_PYTHON or create <repo>/.venv", file=sys.stderr)
        sys.exit(1)
    if not python_has_module(python_bin, 'litex'):
        print("error: selected Python environment does not provide the LiteX package", file=sys.stderr)
        print("hint: activate the repo virtualenv or set LITTLE64_PYTHON to an environment with LiteX installed", file=sys.stderr)
        sys.exit(1)


def default_kernel_for_machine(machine: str) -> Path:
    defconfig = default_defconfig_for_machine(machine)
    existing = paths.existing_boot_kernel_path(defconfig)
    if existing is not None:
        return existing

    path = paths.boot_kernel_path(defconfig)
    print(f"error: kernel ELF not found at {path}", file=sys.stderr)
    print(f"hint: build it first with: little64 kernel build --machine {machine} vmlinux -j1", file=sys.stderr)
    sys.exit(1)


def recorded_defconfig_for_machine(machine: str) -> str | None:
    defconfig = default_defconfig_for_machine(machine)
    try:
        return paths.built_defconfig_name(defconfig)
    except Exception:
        return None


def kernel_config_path(kernel_path: Path) -> Path | None:
    resolved = kernel_path.resolve()
    for candidate_dir in (resolved.parent, *resolved.parents):
        candidate = candidate_dir / '.config'
        if candidate.is_file():
            return candidate
    return None


def resolve_litex_machine_profile(
    *,
    root: Path | None = None,
    machine: str = DEFAULT_LITEX_MACHINE,
    env: dict[str, str] | None = None,
) -> LitexMachineProfile:
    if machine != DEFAULT_LITEX_MACHINE:
        raise ValueError(f'Unsupported LiteX machine profile: {machine}')

    repo = paths.repo_root() if root is None else root
    environment = os.environ if env is None else env
    output_dir_text = environment.get('LITTLE64_LITEX_OUTPUT_DIR')
    output_dir = Path(output_dir_text).expanduser() if output_dir_text else paths.builddir(repo) / DEFAULT_LITEX_OUTPUT_DIRNAME
    ram_size = environment.get('LITTLE64_LITEX_RAM_SIZE') or None
    return LitexMachineProfile(
        machine=machine,
        cpu_variant=environment.get('LITTLE64_LITEX_CPU_VARIANT', DEFAULT_LITEX_CPU_VARIANT),
        litex_target=environment.get('LITTLE64_LITEX_TARGET', DEFAULT_LITEX_TARGET),
        output_dir=output_dir,
        ram_size=ram_size,
    )


def ensure_default_machine_kernel_matches_defconfig(machine: str, kernel_elf: Path) -> None:
    active_defconfig = recorded_defconfig_for_machine(machine)
    expected = default_defconfig_for_machine(machine)
    if active_defconfig and active_defconfig != expected:
        print(f'error: default kernel path {kernel_elf} currently points to a {active_defconfig} build', file=sys.stderr)
        print(f'hint: rebuild the LiteX kernel with: little64 kernel build --machine {machine} vmlinux -j1', file=sys.stderr)
        print('hint: LiteX kernels now live under target/linux_port/build-litex/ by default', file=sys.stderr)
        print('hint: or pass an explicit kernel path that matches the selected machine profile', file=sys.stderr)
        sys.exit(1)


def ensure_litex_kernel_support(kernel_path: Path) -> None:
    if os.environ.get('LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK') == '1':
        return

    config_path = kernel_config_path(kernel_path)
    if config_path is None:
        print(f"error: unable to verify LiteX kernel support for {kernel_path}", file=sys.stderr)
        print(
            'hint: provide a kernel built in a Little64 Linux build directory so the adjacent .config is available',
            file=sys.stderr,
        )
        print('hint: or set LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK=1 to bypass this verification explicitly', file=sys.stderr)
        sys.exit(1)

    lines = config_path.read_text(encoding='utf-8').splitlines()
    line_set = set(lines)
    for option, expected in REQUIRED_LITEX_KERNEL_OPTIONS:
        if f'{option}={expected}' not in line_set:
            print(f"error: kernel config {config_path} is missing {option}={expected}", file=sys.stderr)
            if option == 'CONFIG_LITTLE64_KERNEL_PHYS_BASE':
                print(
                    'hint: rebuild the LiteX kernel so the early boot code matches the SDRAM-backed bootrom layout',
                    file=sys.stderr,
                )
                print(
                    "hint: run 'little64 kernel build --machine litex clean' then 'little64 kernel build --machine litex vmlinuz -j1'",
                    file=sys.stderr,
                )
            sys.exit(1)