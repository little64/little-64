from __future__ import annotations

import argparse
import sys
from pathlib import Path

from amaranth import Elaboratable, Module, Signal
from amaranth.back import verilog

from little64.paths import repo_root

sys.path.insert(0, str(repo_root() / "hdl"))

from little64_cores.config import CACHE_TOPOLOGIES, Little64CoreConfig, SUPPORTED_CORE_VARIANTS
from little64_cores.litex import LITTLE64_LITEX_MEM_MAP
from little64_cores.variants import create_core


FLASH_RESET_BASE = LITTLE64_LITEX_MEM_MAP['spiflash']


class Little64LinuxBootTop(Elaboratable):
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)

        self.i_bus_ack = Signal()
        self.i_bus_err = Signal()
        self.i_bus_dat_r = Signal(64)

        self.d_bus_ack = Signal()
        self.d_bus_err = Signal()
        self.d_bus_dat_r = Signal(64)

        self.irq_lines = Signal(63)

        self.i_bus_adr = Signal(64)
        self.i_bus_dat_w = Signal(64)
        self.i_bus_sel = Signal(8)
        self.i_bus_cyc = Signal()
        self.i_bus_stb = Signal()
        self.i_bus_we = Signal()
        self.i_bus_cti = Signal(3)
        self.i_bus_bte = Signal(2)

        self.d_bus_adr = Signal(64)
        self.d_bus_dat_w = Signal(64)
        self.d_bus_sel = Signal(8)
        self.d_bus_cyc = Signal()
        self.d_bus_stb = Signal()
        self.d_bus_we = Signal()
        self.d_bus_cti = Signal(3)
        self.d_bus_bte = Signal(2)

        self.halted = Signal()
        self.locked_up = Signal()
        self.state = Signal(4)
        self.current_instruction = Signal(16)
        self.fetch_pc = Signal(64)
        self.fetch_phys_addr = Signal(64)
        self.commit_valid = Signal()
        self.commit_pc = Signal(64)

        resolved_config = config or Little64CoreConfig(reset_vector=FLASH_RESET_BASE)
        self.core = create_core(resolved_config)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core

        m.d.comb += [
            self.core.boot_r1.eq(self.boot_r1),
            self.core.boot_r13.eq(self.boot_r13),
            self.core.i_bus.ack.eq(self.i_bus_ack),
            self.core.i_bus.err.eq(self.i_bus_err),
            self.core.i_bus.dat_r.eq(self.i_bus_dat_r),
            self.core.d_bus.ack.eq(self.d_bus_ack),
            self.core.d_bus.err.eq(self.d_bus_err),
            self.core.d_bus.dat_r.eq(self.d_bus_dat_r),
            self.core.irq_lines.eq(self.irq_lines),
            self.i_bus_adr.eq(self.core.i_bus.adr),
            self.i_bus_dat_w.eq(self.core.i_bus.dat_w),
            self.i_bus_sel.eq(self.core.i_bus.sel),
            self.i_bus_cyc.eq(self.core.i_bus.cyc),
            self.i_bus_stb.eq(self.core.i_bus.stb),
            self.i_bus_we.eq(self.core.i_bus.we),
            self.i_bus_cti.eq(self.core.i_bus.cti),
            self.i_bus_bte.eq(self.core.i_bus.bte),
            self.d_bus_adr.eq(self.core.d_bus.adr),
            self.d_bus_dat_w.eq(self.core.d_bus.dat_w),
            self.d_bus_sel.eq(self.core.d_bus.sel),
            self.d_bus_cyc.eq(self.core.d_bus.cyc),
            self.d_bus_stb.eq(self.core.d_bus.stb),
            self.d_bus_we.eq(self.core.d_bus.we),
            self.d_bus_cti.eq(self.core.d_bus.cti),
            self.d_bus_bte.eq(self.core.d_bus.bte),
            self.halted.eq(self.core.halted),
            self.locked_up.eq(self.core.locked_up),
            self.state.eq(self.core.state),
            self.current_instruction.eq(self.core.current_instruction),
            self.fetch_pc.eq(self.core.fetch_pc),
            self.fetch_phys_addr.eq(self.core.fetch_phys_addr),
            self.commit_valid.eq(self.core.commit_valid),
            self.commit_pc.eq(self.core.commit_pc),
        ]

        return m


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Export the Little-64 Linux-boot Verilator wrapper to Verilog.')
    parser.add_argument('output', type=Path, help='Output Verilog file path')
    parser.add_argument(
        '--core-variant',
        choices=SUPPORTED_CORE_VARIANTS,
        default='v2',
        help='Core variant used by the Linux-boot wrapper.',
    )
    parser.add_argument(
        '--cache-topology',
        choices=CACHE_TOPOLOGIES,
        default='none',
        help='Cache topology used by the Linux-boot wrapper.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Little64CoreConfig(
        reset_vector=FLASH_RESET_BASE,
        core_variant=args.core_variant,
        cache_topology=args.cache_topology,
    )
    top = Little64LinuxBootTop(config)
    verilog_text = verilog.convert(
        top,
        name='little64_linux_boot_top',
        ports=[
            top.boot_r1,
            top.boot_r13,
            top.i_bus_ack,
            top.i_bus_err,
            top.i_bus_dat_r,
            top.d_bus_ack,
            top.d_bus_err,
            top.d_bus_dat_r,
            top.irq_lines,
            top.i_bus_adr,
            top.i_bus_dat_w,
            top.i_bus_sel,
            top.i_bus_cyc,
            top.i_bus_stb,
            top.i_bus_we,
            top.i_bus_cti,
            top.i_bus_bte,
            top.d_bus_adr,
            top.d_bus_dat_w,
            top.d_bus_sel,
            top.d_bus_cyc,
            top.d_bus_stb,
            top.d_bus_we,
            top.d_bus_cti,
            top.d_bus_bte,
            top.halted,
            top.locked_up,
            top.state,
            top.current_instruction,
            top.fetch_pc,
            top.fetch_phys_addr,
            top.commit_valid,
            top.commit_pc,
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(verilog_text, encoding='utf-8')
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())