from __future__ import annotations

import argparse
from pathlib import Path

from little64.hdl_bridge import ensure_hdl_path

ensure_hdl_path()

from little64_cores.config import CACHE_TOPOLOGIES, CORE_VARIANTS, Little64CoreConfig
from little64_cores.litex import emit_litex_cpu_verilog


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
    parser.add_argument(
        '--core-variant',
        choices=CORE_VARIANTS,
        default='v2',
        help='Core variant used for the exported CPU wrapper.',
    )
    parser.add_argument(
        '--cache-topology',
        choices=CACHE_TOPOLOGIES,
        default='none',
        help='Cache topology used for the exported CPU wrapper.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Little64CoreConfig(
        reset_vector=args.reset_address,
        core_variant=args.core_variant,
        cache_topology=args.cache_topology,
    )
    emit_litex_cpu_verilog(args.output, config=config, module_name=args.module_name)
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())