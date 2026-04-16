from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from amaranth import Elaboratable, Module, Signal
from amaranth.back import verilog

from .config import Little64CoreConfig
from .core import Little64Core


LITTLE64_LITEX_CPU_VARIANTS = ('standard',)
LITTLE64_LITEX_IO_REGIONS = {
    0x0800_0000: 0x0100_0000,
    0x8000_0000: 0x8000_0000,
}
LITTLE64_LITEX_MEM_MAP = {
    'rom': 0x0000_0000,
    'sram': 0x1000_0000,
    'spiflash': 0x2000_0000,
    'main_ram': 0x0000_0000,
    'csr': 0xF000_0000,
}
LITTLE64_LINUX_RAM_BASE = 0x0010_0000
LITTLE64_LINUX_BREADCRUMB_UART_BASE = 0x0800_0000
LITTLE64_LINUX_TIMER_BASE = 0x0800_1000
LITTLE64_LITEX_FLASH_BOOT_MAGIC = 0x4C3634464C415348
LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET = 0x0000_2000
LITTLE64_LITEX_FLASH_BOOT_ABI_VERSION = 1


@dataclass(frozen=True, slots=True)
class Little64LiteXProfile:
    category: str = 'softcore'
    name: str = 'little64'
    human_name: str = 'Little64'
    family: str = 'little64'
    endianness: str = 'little'
    gcc_triple: str = 'little64-unknown-elf'
    clang_triple: str = 'little64-unknown-elf'
    linker_output_format: str = 'elf64little64'
    nop: str = 'nop'
    data_width: int = 64
    instruction_width: int = 64
    irq_count: int = 63
    first_irq_vector: int = 65
    reset_address: int = 0
    variants: tuple[str, ...] = LITTLE64_LITEX_CPU_VARIANTS
    io_regions: dict[int, int] = field(default_factory=lambda: dict(LITTLE64_LITEX_IO_REGIONS))
    mem_map: dict[str, int] = field(default_factory=lambda: dict(LITTLE64_LITEX_MEM_MAP))


class Little64LiteXShim(Elaboratable):
    def __init__(
        self,
        config: Little64CoreConfig | None = None,
        *,
        profile: Little64LiteXProfile | None = None,
    ) -> None:
        self.config = config or Little64CoreConfig()
        self.profile = profile or Little64LiteXProfile(
            data_width=self.config.data_bus_width,
            instruction_width=self.config.instruction_bus_width,
            irq_count=self.config.irq_input_count,
            reset_address=self.config.reset_vector,
        )
        if self.profile.reset_address != self.config.reset_vector:
            raise ValueError('Little64LiteXProfile reset_address must match Little64CoreConfig reset_vector')

        self.core = Little64Core(self.config)

        self.ibus = self.core.i_bus
        self.dbus = self.core.d_bus
        self.boot_r1 = self.core.boot_r1
        self.boot_r13 = self.core.boot_r13
        self.irq_lines = self.core.irq_lines
        self.halted = self.core.halted
        self.locked_up = self.core.locked_up

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = self.core
        return m


class Little64LiteXTop(Elaboratable):
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.shim = Little64LiteXShim(config)
        self.profile = self.shim.profile
        self.reset_address = self.profile.reset_address

        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)

        self.i_bus_ack = Signal()
        self.i_bus_err = Signal()
        self.i_bus_dat_r = Signal(64)

        self.d_bus_ack = Signal()
        self.d_bus_err = Signal()
        self.d_bus_dat_r = Signal(64)

        self.irq_lines = Signal(self.profile.irq_count)

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

    def ports(self) -> list[Signal]:
        return [
            self.boot_r1,
            self.boot_r13,
            self.i_bus_ack,
            self.i_bus_err,
            self.i_bus_dat_r,
            self.d_bus_ack,
            self.d_bus_err,
            self.d_bus_dat_r,
            self.irq_lines,
            self.i_bus_adr,
            self.i_bus_dat_w,
            self.i_bus_sel,
            self.i_bus_cyc,
            self.i_bus_stb,
            self.i_bus_we,
            self.i_bus_cti,
            self.i_bus_bte,
            self.d_bus_adr,
            self.d_bus_dat_w,
            self.d_bus_sel,
            self.d_bus_cyc,
            self.d_bus_stb,
            self.d_bus_we,
            self.d_bus_cti,
            self.d_bus_bte,
            self.halted,
            self.locked_up,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules.shim = self.shim

        m.d.comb += [
            self.shim.boot_r1.eq(self.boot_r1),
            self.shim.boot_r13.eq(self.boot_r13),
            self.shim.ibus.ack.eq(self.i_bus_ack),
            self.shim.ibus.err.eq(self.i_bus_err),
            self.shim.ibus.dat_r.eq(self.i_bus_dat_r),
            self.shim.dbus.ack.eq(self.d_bus_ack),
            self.shim.dbus.err.eq(self.d_bus_err),
            self.shim.dbus.dat_r.eq(self.d_bus_dat_r),
            self.shim.irq_lines.eq(self.irq_lines),
            self.i_bus_adr.eq(self.shim.ibus.adr),
            self.i_bus_dat_w.eq(self.shim.ibus.dat_w),
            self.i_bus_sel.eq(self.shim.ibus.sel),
            self.i_bus_cyc.eq(self.shim.ibus.cyc),
            self.i_bus_stb.eq(self.shim.ibus.stb),
            self.i_bus_we.eq(self.shim.ibus.we),
            self.i_bus_cti.eq(self.shim.ibus.cti),
            self.i_bus_bte.eq(self.shim.ibus.bte),
            self.d_bus_adr.eq(self.shim.dbus.adr),
            self.d_bus_dat_w.eq(self.shim.dbus.dat_w),
            self.d_bus_sel.eq(self.shim.dbus.sel),
            self.d_bus_cyc.eq(self.shim.dbus.cyc),
            self.d_bus_stb.eq(self.shim.dbus.stb),
            self.d_bus_we.eq(self.shim.dbus.we),
            self.d_bus_cti.eq(self.shim.dbus.cti),
            self.d_bus_bte.eq(self.shim.dbus.bte),
            self.halted.eq(self.shim.halted),
            self.locked_up.eq(self.shim.locked_up),
        ]

        return m


def emit_litex_cpu_verilog(
    output_path: str | Path,
    *,
    config: Little64CoreConfig | None = None,
    module_name: str = 'little64_litex_cpu_top',
) -> Path:
    top = Little64LiteXTop(config)
    verilog_text = verilog.convert(
        top,
        name=module_name,
        ports=top.ports(),
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(verilog_text, encoding='utf-8')
    return output
