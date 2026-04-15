from __future__ import annotations

import argparse
import sys
from pathlib import Path

from amaranth.back import verilog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from little64.config import Little64CoreConfig
from little64.core import Little64Core


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export the Little-64 HDL core to Verilog for external tooling such as Verilator.')
    parser.add_argument('output', type=Path, help='Output Verilog file path')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dut = Little64Core(Little64CoreConfig())
    verilog_text = verilog.convert(
        dut,
        name='little64_core',
        ports=[
            dut.i_bus.adr,
            dut.i_bus.dat_w,
            dut.i_bus.dat_r,
            dut.i_bus.sel,
            dut.i_bus.cyc,
            dut.i_bus.stb,
            dut.i_bus.we,
            dut.i_bus.ack,
            dut.i_bus.err,
            dut.i_bus.cti,
            dut.i_bus.bte,
            dut.d_bus.adr,
            dut.d_bus.dat_w,
            dut.d_bus.dat_r,
            dut.d_bus.sel,
            dut.d_bus.cyc,
            dut.d_bus.stb,
            dut.d_bus.we,
            dut.d_bus.ack,
            dut.d_bus.err,
            dut.d_bus.cti,
            dut.d_bus.bte,
            dut.irq_lines,
            dut.halted,
            dut.locked_up,
            dut.state,
            dut.current_instruction,
            dut.fetch_pc,
            dut.fetch_phys_addr,
            dut.commit_valid,
            dut.commit_pc,
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(verilog_text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())