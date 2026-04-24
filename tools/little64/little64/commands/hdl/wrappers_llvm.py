#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from little64.hdl_bridge import ensure_hdl_path

ensure_hdl_path()

from little64_cores.litex_cpu import ensure_litex_llvm_toolchain_wrappers


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate LiteX-compatible triple-prefixed LLVM tool wrappers for Little64.')
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory that will receive the generated wrapper bin/ tree.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_litex_llvm_toolchain_wrappers(args.output_dir.resolve())
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())