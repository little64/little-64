"""``little64 kernel pc2line`` — resolve a PC to function/file/line."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional

from little64 import paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="little64 kernel pc2line",
        description="Resolve a program counter to function/file/line in a Linux vmlinux image.",
    )
    parser.add_argument("pc", help="Address to resolve (0xNNN hex or decimal).")
    parser.add_argument("--defconfig", default=None)
    parser.add_argument("--elf", default=None, help="ELF image to inspect.")
    parser.add_argument("--context-bytes", type=int, default=32)
    parser.add_argument("--no-disasm", action="store_true")
    return parser


def _resolve_elf(elf: Optional[str], defconfig: Optional[str]) -> str:
    if elf:
        return elf
    existing = paths.existing_kernel_path(defconfig)
    if existing is not None:
        return str(existing)
    return str(paths.kernel_path(defconfig))


def run(argv: List[str]) -> int:
    args = _build_parser().parse_args(argv)

    try:
        pc_dec = int(args.pc, 0)
    except ValueError:
        print(f"error: invalid PC: {args.pc!r}", file=sys.stderr)
        return 1
    if args.context_bytes < 0:
        print("error: --context-bytes must be non-negative", file=sys.stderr)
        return 1

    elf_path = _resolve_elf(args.elf, args.defconfig)
    if not os.path.isfile(elf_path):
        print(f"error: ELF not found: {elf_path}", file=sys.stderr)
        tail = f" --defconfig {args.defconfig}" if args.defconfig else ""
        print(
            f"hint: build the selected kernel first with: little64 kernel build{tail} vmlinux",
            file=sys.stderr,
        )
        return 1

    llvm = paths.compiler_bin()
    symbolizer = llvm / "llvm-symbolizer"
    addr2line = llvm / "llvm-addr2line"
    objdump = llvm / "llvm-objdump"

    if not (symbolizer.is_file() and os.access(symbolizer, os.X_OK)):
        print(f"error: missing tool: {symbolizer}", file=sys.stderr)
        print("hint: build LLVM tools first with: compilers/build.sh llvm", file=sys.stderr)
        return 1

    pc_hex = f"0x{pc_dec:x}"

    print("[little64] pc-to-line")
    print(f"  elf: {elf_path}")
    print(f"  pc : {pc_hex}")
    print()

    print("== symbolizer ==")
    subprocess.run([str(symbolizer), f"--obj={elf_path}", "--inlining", pc_hex], check=False)
    print()

    if addr2line.is_file() and os.access(addr2line, os.X_OK):
        print("== addr2line ==")
        subprocess.run([str(addr2line), "-e", elf_path, "-f", "-C", pc_hex], check=False)
        print()

    if not args.no_disasm:
        if objdump.is_file() and os.access(objdump, os.X_OK):
            start_dec = max(0, pc_dec - args.context_bytes)
            stop_dec = pc_dec + args.context_bytes
            print("== disassembly context ==")
            subprocess.run(
                [
                    str(objdump),
                    "--disassemble",
                    "--demangle",
                    "--line-numbers",
                    "--print-imm-hex",
                    f"--start-address=0x{start_dec:x}",
                    f"--stop-address=0x{stop_dec:x}",
                    elf_path,
                ],
                check=False,
            )
        else:
            print(f"warning: {objdump} not found, skipping disassembly context", file=sys.stderr)

    return 0
