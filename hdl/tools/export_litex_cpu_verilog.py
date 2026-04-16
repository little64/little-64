from __future__ import annotations

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from little64.config import Little64CoreConfig
from little64.litex import emit_litex_cpu_verilog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export the generic Little-64 LiteX CPU wrapper to Verilog.')
    parser.add_argument('output', type=Path, help='Output Verilog file path')
    parser.add_argument(
        '--reset-address',
        type=lambda value: int(value, 0),
        default=0,
        help='Reset vector used for the exported CPU wrapper',
    )
    parser.add_argument(
        '--module-name',
        default='little64_litex_cpu_top',
        help='Top-level Verilog module name',
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = Little64CoreConfig(reset_vector=args.reset_address)
    emit_litex_cpu_verilog(args.output, config=config, module_name=args.module_name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())