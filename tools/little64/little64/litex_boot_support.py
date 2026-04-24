"""LiteX-specific machine profile resolution and boot helpers.

Historical dumping-ground for LiteX-flavored logic. After the Phase 3
cleanup, this module is focused on:

* Resolving the :class:`LitexMachineProfile` from env vars / defaults.
* Exception-raising validators that callers can handle uniformly.

Kernel-config validation moved to :mod:`little64.commands.kernel.validate`.
Defconfig/machine metadata lives in :mod:`little64.config`.
Library functions here no longer call :func:`sys.exit`; they raise
:class:`LitexBootError`. The CLI entry point handles formatting.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from little64 import config, env, paths
from little64.commands.kernel.validate import (
    REQUIRED_LITEX_KERNEL_OPTIONS,
    KernelConfigError,
    kernel_config_path,
    validate_kernel_config,
)
from little64.errors import LitexBootError
from little64.tooling_support import python_has_module


_LITEX_PROFILE = config.get_machine_profile('litex')

DEFAULT_LITEX_MACHINE = _LITEX_PROFILE.name
DEFAULT_LITEX_CPU_VARIANT = _LITEX_PROFILE.cpu_variant
DEFAULT_LITEX_TARGET = _LITEX_PROFILE.litex_target
DEFAULT_LITEX_OUTPUT_DIRNAME = _LITEX_PROFILE.output_dirname


__all__ = [
    'DEFAULT_LITEX_MACHINE',
    'DEFAULT_LITEX_CPU_VARIANT',
    'DEFAULT_LITEX_TARGET',
    'DEFAULT_LITEX_OUTPUT_DIRNAME',
    'REQUIRED_LITEX_KERNEL_OPTIONS',
    'LitexBootError',
    'LitexMachineProfile',
    'default_defconfig_for_machine',
    'default_kernel_for_machine',
    'ensure_default_machine_kernel_matches_defconfig',
    'ensure_litex_kernel_support',
    'ensure_litex_python_env',
    'kernel_config_path',
    'recorded_defconfig_for_machine',
    'resolve_litex_machine_profile',
]


def default_defconfig_for_machine(machine: str) -> str:
    return config.default_defconfig_for_machine(machine)


@dataclass(frozen=True, slots=True)
class LitexMachineProfile:
    machine: str
    cpu_variant: str
    litex_target: str
    output_dir: Path
    ram_size: str | None


def ensure_litex_python_env(python_bin: str) -> None:
    if not python_bin or (not shutil.which(python_bin) and not os.path.isfile(python_bin)):
        raise LitexBootError(
            "Python interpreter not found for LiteX artifact generation",
            hints=(
                f"set {env.PYTHON.name} or create <repo>/.venv",
            ),
        )
    if not python_has_module(python_bin, 'litex'):
        raise LitexBootError(
            "selected Python environment does not provide the LiteX package",
            hints=(
                f"activate the repo virtualenv or set {env.PYTHON.name} "
                "to an environment with LiteX installed",
            ),
        )


def default_kernel_for_machine(machine: str) -> Path:
    defconfig = default_defconfig_for_machine(machine)
    existing = paths.existing_boot_kernel_path(defconfig)
    if existing is not None:
        return existing

    path = paths.boot_kernel_path(defconfig)
    raise LitexBootError(
        f"kernel ELF not found at {path}",
        hints=(
            f"build it first with: little64 kernel build --machine {machine} vmlinux -j1",
        ),
    )


def recorded_defconfig_for_machine(machine: str) -> str | None:
    defconfig = default_defconfig_for_machine(machine)
    try:
        return paths.built_defconfig_name(defconfig)
    except Exception:
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
    output_dir = (
        Path(output_dir_text).expanduser()
        if output_dir_text
        else paths.builddir(repo) / DEFAULT_LITEX_OUTPUT_DIRNAME
    )
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
        raise LitexBootError(
            f"default kernel path {kernel_elf} currently points to a {active_defconfig} build",
            hints=(
                f"rebuild the LiteX kernel with: little64 kernel build --machine {machine} vmlinux -j1",
                "LiteX kernels now live under target/linux_port/build-litex/ by default",
                "or pass an explicit kernel path that matches the selected machine profile",
            ),
        )


def ensure_litex_kernel_support(kernel_path: Path) -> None:
    """Validate the kernel's ``.config`` for LiteX boot requirements.

    Raises :class:`LitexBootError` on failure (wrapping the underlying
    :class:`KernelConfigError` so callers don't need to know about the
    ``kernel.validate`` module's exception types).
    """
    try:
        validate_kernel_config(kernel_path)
    except KernelConfigError as exc:
        raise LitexBootError(str(exc), hints=exc.hints) from exc
