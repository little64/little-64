"""Path resolution for the Little64 repository.

This module is the single source of truth for locating repository-rooted
artifacts from tooling code. Machine-profile metadata (defconfig names,
build-dir mappings) lives in :mod:`little64.config`.
"""

from __future__ import annotations

import os
import pathlib
from typing import Optional

from little64 import config


DEFAULT_DEFCONFIG_NAME = config.DEFAULT_DEFCONFIG_NAME
DEFAULT_SYMBOL_CACHE_NAME = ".analyze_lockup_flow_addr2line_cache.json"


def repo_root() -> pathlib.Path:
    """Return the repository root.

    Resolution order:

    1. ``LITTLE64_REPO_ROOT`` environment variable, if set.
    2. Walk upwards from this file looking for a ``meson.build`` next to
       ``CLAUDE.md``.
    """
    env = os.environ.get("LITTLE64_REPO_ROOT")
    if env:
        return pathlib.Path(env).resolve()

    here = pathlib.Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "meson.build").is_file() and (candidate / "CLAUDE.md").is_file():
            return candidate
    return here.parents[3]


def linux_port_dir(root: Optional[pathlib.Path] = None) -> pathlib.Path:
    return (root or repo_root()) / "target" / "linux_port"


def compiler_bin(root: Optional[pathlib.Path] = None) -> pathlib.Path:
    return (root or repo_root()) / "compilers" / "bin"


def builddir(root: Optional[pathlib.Path] = None) -> pathlib.Path:
    override = os.environ.get("LITTLE64_BUILDDIR")
    if override:
        return pathlib.Path(override).resolve()
    return (root or repo_root()) / "builddir"


def build_dir_name_for_defconfig(defconfig_name: str) -> str:
    return config.build_dir_name_for_defconfig(defconfig_name)


def effective_defconfig_name(defconfig_name: Optional[str] = None) -> str:
    return config.resolve_defconfig(defconfig=defconfig_name)


def linux_build_dir(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
    build_dir_override: Optional[str] = None,
) -> pathlib.Path:
    override = build_dir_override or os.environ.get("LITTLE64_LINUX_BUILD_DIR")
    if override:
        return pathlib.Path(override)

    name = effective_defconfig_name(defconfig_name)
    return linux_port_dir(repo) / build_dir_name_for_defconfig(name)


def kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    unstripped: bool = False,
    repo: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    filename = "vmlinux.unstripped" if unstripped else "vmlinux"
    return linux_build_dir(defconfig_name, repo=repo) / filename


def boot_kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    return linux_build_dir(defconfig_name, repo=repo) / "arch" / "little64" / "boot" / "vmlinuz"


def existing_kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
) -> Optional[pathlib.Path]:
    candidates = [
        kernel_path(defconfig_name, unstripped=True, repo=repo),
        kernel_path(defconfig_name, repo=repo),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def existing_boot_kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
) -> Optional[pathlib.Path]:
    candidates = [
        boot_kernel_path(defconfig_name, repo=repo),
        kernel_path(defconfig_name, repo=repo),
    ]
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        return existing[0]
    return max(existing, key=lambda path: path.stat().st_mtime_ns)


def symbol_cache_path(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
    filename: str = DEFAULT_SYMBOL_CACHE_NAME,
) -> pathlib.Path:
    return linux_build_dir(defconfig_name, repo=repo) / filename


def built_defconfig_name(
    defconfig_name: Optional[str] = None,
    *,
    repo: Optional[pathlib.Path] = None,
) -> Optional[str]:
    stamp = linux_build_dir(defconfig_name, repo=repo) / ".little64_defconfig.name"
    if not stamp.is_file():
        return None
    value = stamp.read_text(encoding="utf-8").strip()
    return value or None
