#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pathlib
from typing import Optional


DEFAULT_DEFCONFIG_NAME = "little64_defconfig"
DEFAULT_SYMBOL_CACHE_NAME = ".analyze_lockup_flow_addr2line_cache.json"


def linux_port_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def effective_defconfig_name(defconfig_name: Optional[str] = None) -> str:
    if defconfig_name:
        return defconfig_name
    return os.environ.get("LITTLE64_LINUX_DEFCONFIG", DEFAULT_DEFCONFIG_NAME)


def resolve_build_dir(
    defconfig_name: Optional[str] = None,
    *,
    linux_port_root: Optional[pathlib.Path] = None,
    build_dir_override: Optional[str] = None,
) -> pathlib.Path:
    root = linux_port_root or linux_port_dir()
    override = build_dir_override or os.environ.get("LITTLE64_LINUX_BUILD_DIR")
    if override:
        return pathlib.Path(override)

    name = effective_defconfig_name(defconfig_name)
    if name == DEFAULT_DEFCONFIG_NAME:
        return root / "build"
    return root / f"build-{name}"


def kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    unstripped: bool = False,
    linux_port_root: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    filename = "vmlinux.unstripped" if unstripped else "vmlinux"
    return resolve_build_dir(defconfig_name, linux_port_root=linux_port_root) / filename


def existing_kernel_path(
    defconfig_name: Optional[str] = None,
    *,
    linux_port_root: Optional[pathlib.Path] = None,
) -> Optional[pathlib.Path]:
    candidates = [
        kernel_path(defconfig_name, unstripped=True, linux_port_root=linux_port_root),
        kernel_path(defconfig_name, linux_port_root=linux_port_root),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def symbol_cache_path(
    defconfig_name: Optional[str] = None,
    *,
    linux_port_root: Optional[pathlib.Path] = None,
    filename: str = DEFAULT_SYMBOL_CACHE_NAME,
) -> pathlib.Path:
    return resolve_build_dir(defconfig_name, linux_port_root=linux_port_root) / filename


def built_defconfig_name(
    defconfig_name: Optional[str] = None,
    *,
    linux_port_root: Optional[pathlib.Path] = None,
) -> Optional[str]:
    stamp_path = resolve_build_dir(defconfig_name, linux_port_root=linux_port_root) / ".little64_defconfig.name"
    if not stamp_path.is_file():
        return None
    value = stamp_path.read_text(encoding="utf-8").strip()
    return value or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Little64 Linux profile-aware helper paths")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_defconfig_arg(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--defconfig",
            default=None,
            help=(
                "Little64 Linux defconfig name "
                f"(default: LITTLE64_LINUX_DEFCONFIG or {DEFAULT_DEFCONFIG_NAME})"
            ),
        )

    defconfig_parser = subparsers.add_parser("defconfig", help="Print the effective defconfig name")
    add_defconfig_arg(defconfig_parser)

    build_dir_parser = subparsers.add_parser("build-dir", help="Print the selected build directory")
    add_defconfig_arg(build_dir_parser)

    kernel_parser = subparsers.add_parser("kernel", help="Print the selected kernel ELF path")
    add_defconfig_arg(kernel_parser)
    kernel_parser.add_argument("--unstripped", action="store_true", help="Use vmlinux.unstripped")

    existing_kernel_parser = subparsers.add_parser(
        "existing-kernel",
        help="Print the first existing kernel ELF path (prefers vmlinux.unstripped)",
    )
    add_defconfig_arg(existing_kernel_parser)

    symbol_cache_parser = subparsers.add_parser("symbol-cache", help="Print the selected symbol-cache path")
    add_defconfig_arg(symbol_cache_parser)
    symbol_cache_parser.add_argument(
        "--filename",
        default=DEFAULT_SYMBOL_CACHE_NAME,
        help="Cache filename within the selected build directory",
    )

    built_defconfig_parser = subparsers.add_parser(
        "built-defconfig",
        help="Print the defconfig stamp currently recorded in the selected build directory",
    )
    add_defconfig_arg(built_defconfig_parser)

    args = parser.parse_args()

    if args.command == "defconfig":
        print(effective_defconfig_name(args.defconfig))
        return 0
    if args.command == "build-dir":
        print(resolve_build_dir(args.defconfig))
        return 0
    if args.command == "kernel":
        print(kernel_path(args.defconfig, unstripped=args.unstripped))
        return 0
    if args.command == "existing-kernel":
        path = existing_kernel_path(args.defconfig)
        if path is None:
            return 1
        print(path)
        return 0
    if args.command == "symbol-cache":
        print(symbol_cache_path(args.defconfig, filename=args.filename))
        return 0

    built_name = built_defconfig_name(args.defconfig)
    if built_name is None:
        return 1
    print(built_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())