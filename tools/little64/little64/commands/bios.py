"""``little64 bios`` \u2014 build and run the C-BIOS ELF."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

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
    args = parser.parse_args(argv)  # currently takes no options

    root = repo_root()
    tools = compiler_bin(root)
    build = builddir(root)
    obj = build / "c_boot_bios.o"
    elf = build / "c_boot_bios.elf"
    build.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [str(tools / "clang"), "-target", "little64", "-O0", "-gdwarf-4",
         "-fno-omit-frame-pointer", "-funwind-tables", "-fasynchronous-unwind-tables",
         "-fforce-dwarf-frame", "-ffreestanding",
         f"-I{root / 'host' / 'boot'}",
         "-c", str(root / "target" / "c_boot" / "start.c"),
         "-o", str(obj)],
        check=True,
        cwd=root,
    )
    subprocess.run(
        [str(tools / "ld.lld"), str(obj), "-o", str(elf),
         "-T", str(root / "target" / "c_boot" / "linker_bios.ld")],
        check=True,
        cwd=root,
    )

    print(f"[little-64] running BIOS image: {elf}")
    proc = subprocess.run([str(build / "little-64"), str(elf)])
    return proc.returncode
