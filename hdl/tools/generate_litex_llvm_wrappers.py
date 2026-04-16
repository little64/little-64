#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from little64.litex_cpu import ensure_litex_llvm_toolchain_wrappers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate LiteX-compatible triple-prefixed LLVM tool wrappers for Little64.')
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory that will receive the generated wrapper bin/ tree.')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_litex_llvm_toolchain_wrappers(args.output_dir.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())