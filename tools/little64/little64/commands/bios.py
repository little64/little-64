"""``little64 bios`` — build and run the C-BIOS ELF."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List

from little64 import proc, tools
from little64.paths import builddir, compiler_bin, repo_root


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="little64 bios",
        description="Build and run the Little64 C-BIOS ELF under the emulator.",
    )
    sub = parser.add_subparsers(dest="op", required=True, metavar="<op>")
    sub.add_parser("run", add_help=False, help="Build the BIOS ELF and run it under the emulator.")
    args, rest = parser.parse_known_args(argv)
    if args.op != "run":
        parser.parse_args(argv)
        return 2
    return _run(rest)


def _run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="little64 bios run")
    parser.parse_args(argv)  # currently takes no options

    root = repo_root()
    compiler_dir = compiler_bin(root)
    build = builddir(root)
    obj = build / "c_boot_bios.o"
    elf = build / "c_boot_bios.elf"
    build.mkdir(parents=True, exist_ok=True)

    try:
        clang = tools.require_compiler_tool(compiler_dir, "clang")
        ld_lld = tools.require_compiler_tool(compiler_dir, "ld.lld")
    except tools.MissingToolError as exc:
        return tools.report_and_exit(exc)

    try:
        proc.run(
            [str(clang), "-target", "little64", "-O0", "-gdwarf-4",
             "-fno-omit-frame-pointer", "-funwind-tables", "-fasynchronous-unwind-tables",
             "-fforce-dwarf-frame", "-ffreestanding",
             f"-I{root / 'host' / 'boot'}",
             "-c", str(root / "target" / "c_boot" / "start.c"),
             "-o", str(obj)],
            context="compiling C-BIOS start.c",
            cwd=root,
        )
        proc.run(
            [str(ld_lld), str(obj), "-o", str(elf),
             "-T", str(root / "target" / "c_boot" / "linker_bios.ld")],
            context="linking C-BIOS ELF",
            cwd=root,
        )
    except proc.CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.returncode or 1

    print(f"[little-64] running BIOS image: {elf}")
    completed = subprocess.run([str(build / "little-64"), str(elf)])
    return completed.returncode
