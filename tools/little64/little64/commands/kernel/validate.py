"""Kernel configuration validation for Little64 boot paths.

Previously lived in :mod:`little64.litex_boot_support`; moved here so the
``kernel`` command package owns kernel-config semantics and non-kernel
command packages don't have to import from ``litex_boot_support`` just to
validate ``.config`` contents.
"""

from __future__ import annotations

from pathlib import Path

from little64 import env


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


class KernelConfigError(RuntimeError):
    """Raised when a kernel's ``.config`` is missing or lacks required options.

    Carries ``hints`` so the CLI surface can render user-friendly guidance
    without every caller inventing its own error text.
    """

    def __init__(self, message: str, *, hints: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.hints = hints


def kernel_config_path(kernel_path: Path) -> Path | None:
    """Find a ``.config`` adjacent to ``kernel_path`` (or any ancestor)."""
    resolved = kernel_path.resolve()
    for candidate_dir in (resolved.parent, *resolved.parents):
        candidate = candidate_dir / ".config"
        if candidate.is_file():
            return candidate
    return None


def validate_kernel_config(
    kernel_path: Path,
    required_options: tuple[tuple[str, str], ...] = REQUIRED_LITEX_KERNEL_OPTIONS,
    *,
    skip_check: bool | None = None,
) -> None:
    """Validate that the kernel's adjacent ``.config`` enables the right options.

    When ``skip_check`` is ``True`` (or ``LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK=1``
    is set in the environment) this is a no-op.
    """
    if skip_check is None:
        skip_check = env.SKIP_LITEX_KERNEL_CONFIG_CHECK.get_flag()
    if skip_check:
        return

    config_path = kernel_config_path(kernel_path)
    if config_path is None:
        raise KernelConfigError(
            f"unable to verify LiteX kernel support for {kernel_path}",
            hints=(
                "provide a kernel built in a Little64 Linux build directory so the adjacent .config is available",
                f"or set {env.SKIP_LITEX_KERNEL_CONFIG_CHECK.name}=1 to bypass this verification explicitly",
            ),
        )

    lines = set(config_path.read_text(encoding="utf-8").splitlines())
    for option, expected in required_options:
        if f"{option}={expected}" not in lines:
            hints: tuple[str, ...] = ()
            if option == "CONFIG_LITTLE64_KERNEL_PHYS_BASE":
                hints = (
                    "rebuild the LiteX kernel so the early boot code matches the SDRAM-backed bootrom layout",
                    "run 'little64 kernel build --machine litex clean' then 'little64 kernel build --machine litex vmlinuz -j1'",
                )
            raise KernelConfigError(
                f"kernel config {config_path} is missing {option}={expected}",
                hints=hints,
            )
