"""``little64 lldb tui`` — connect LLDB TUI to a Little64 RSP server."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from little64 import paths, tools


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64 lldb",
        description="LLDB helpers against a Little64 RSP server.",
    )
    sub = parser.add_subparsers(dest="op", required=True, metavar="<op>")

    tui = sub.add_parser(
        "tui",
        help="Connect LLDB to an RSP server and enter TUI (gui) mode.",
    )
    tui.add_argument("--host", default=DEFAULT_HOST)
    tui.add_argument("--port", type=int, default=DEFAULT_PORT)
    tui.add_argument(
        "--defconfig",
        default=None,
        help="Linux defconfig for profile-aware default kernel ELF.",
    )
    tui.add_argument(
        "--elf",
        default=None,
        help="ELF for symbols (default: selected profile vmlinux.unstripped if present, else vmlinux).",
    )
    tui.add_argument(
        "lldb_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments forwarded to LLDB after ``--``.",
    )

    return parser


def _resolve_elf(elf: Optional[str], defconfig: Optional[str]) -> Optional[str]:
    if elf:
        return elf
    p = paths.existing_kernel_path(defconfig)
    return str(p) if p else None


def _cmd_tui(args: argparse.Namespace) -> int:
    if not (1 <= args.port <= 65535):
        print("error: --port must be in range 1..65535", file=sys.stderr)
        return 1

    try:
        lldb_bin = tools.require_compiler_tool(paths.compiler_bin(), "lldb")
    except tools.MissingToolError as exc:
        return tools.report_and_exit(exc)

    elf_path = _resolve_elf(args.elf, args.defconfig)
    lldb_args: list[str] = []
    if elf_path is not None:
        if not os.path.isfile(elf_path):
            print(f"error: ELF not found: {elf_path}", file=sys.stderr)
            return 1
        lldb_args.append(elf_path)

    lldb_args += [
        "--one-line",
        f"gdb-remote {args.host}:{args.port}",
        "--one-line",
        "gui",
    ]

    extra = list(args.lldb_args or [])
    # argparse.REMAINDER captures the leading ``--`` too; strip it.
    if extra and extra[0] == "--":
        extra = extra[1:]
    lldb_args += extra

    print("[little64] launching LLDB TUI")
    print(f"  lldb: {lldb_bin}")
    print(f"  rsp : {args.host}:{args.port}")
    print(f"  elf : {elf_path if elf_path else '(none, symbols may be unavailable)'}")
    print()

    os.execv(str(lldb_bin), [str(lldb_bin), *lldb_args])
    return 0  # unreachable


def run(argv: List[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.op == "tui":
        return _cmd_tui(args)
    return 2
