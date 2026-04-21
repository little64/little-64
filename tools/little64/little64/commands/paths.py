"""``little64 paths`` — resolve Little64 repository paths."""

from __future__ import annotations

import argparse

from little64 import paths


def _add_defconfig(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--defconfig",
        default=None,
        help=(
            "Little64 Linux defconfig name "
            f"(default: LITTLE64_LINUX_DEFCONFIG or {paths.DEFAULT_DEFCONFIG_NAME})"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64 paths",
        description="Resolve Little64 repository paths and Linux build profiles.",
    )
    sub = parser.add_subparsers(dest="op", required=True, metavar="<op>")

    sub.add_parser("repo-root", help="Print the detected repository root.")
    sub.add_parser("compiler-bin", help="Print the Little64 LLVM toolchain bin directory.")
    sub.add_parser("builddir", help="Print the Meson build directory.")
    sub.add_parser("linux-port", help="Print target/linux_port/.")

    defconfig = sub.add_parser("defconfig", help="Print the effective defconfig name.")
    _add_defconfig(defconfig)

    build_dir = sub.add_parser("build-dir", help="Print the selected Linux build directory.")
    _add_defconfig(build_dir)

    kernel = sub.add_parser("kernel", help="Print the selected kernel ELF path.")
    _add_defconfig(kernel)
    kernel.add_argument("--unstripped", action="store_true", help="Use vmlinux.unstripped.")

    existing = sub.add_parser(
        "existing-kernel",
        help="Print the first existing kernel ELF path (prefers vmlinux.unstripped).",
    )
    _add_defconfig(existing)

    symbol_cache = sub.add_parser("symbol-cache", help="Print the selected symbol-cache path.")
    _add_defconfig(symbol_cache)
    symbol_cache.add_argument(
        "--filename",
        default=paths.DEFAULT_SYMBOL_CACHE_NAME,
        help="Cache filename within the selected build directory.",
    )

    built = sub.add_parser(
        "built-defconfig",
        help="Print the defconfig stamp currently recorded in the selected build directory.",
    )
    _add_defconfig(built)

    return parser


def run(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    if args.op == "repo-root":
        print(paths.repo_root())
        return 0
    if args.op == "compiler-bin":
        print(paths.compiler_bin())
        return 0
    if args.op == "builddir":
        print(paths.builddir())
        return 0
    if args.op == "linux-port":
        print(paths.linux_port_dir())
        return 0
    if args.op == "defconfig":
        print(paths.effective_defconfig_name(args.defconfig))
        return 0
    if args.op == "build-dir":
        print(paths.linux_build_dir(args.defconfig))
        return 0
    if args.op == "kernel":
        print(paths.kernel_path(args.defconfig, unstripped=args.unstripped))
        return 0
    if args.op == "existing-kernel":
        path = paths.existing_kernel_path(args.defconfig)
        if path is None:
            return 1
        print(path)
        return 0
    if args.op == "symbol-cache":
        print(paths.symbol_cache_path(args.defconfig, filename=args.filename))
        return 0
    if args.op == "built-defconfig":
        name = paths.built_defconfig_name(args.defconfig)
        if name is None:
            return 1
        print(name)
        return 0

    return 2
