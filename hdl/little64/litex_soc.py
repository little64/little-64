from __future__ import annotations

from pathlib import Path
from itertools import count

from migen import Case, ClockDomain, If, Module, Signal
from migen.fhdl import tracer as migen_tracer

from litex.build.generic_platform import Pins, Subsignal
from litex.build.sim import SimPlatform
from litex.soc.integration.common import get_mem_data
from litex.soc.integration.soc import SoCRegion
from litex.soc.interconnect import csr as litex_csr
from litex.soc.interconnect import csr_eventmanager as litex_csr_eventmanager
from litex.soc.interconnect import wishbone
from litex.soc.integration.soc_core import SoCCore

from litedram import modules as litedram_modules
from litedram.phy.model import SDRAMPHYModel, sdram_module_nphases

from litespi.modules import S25FL128L
from litespi.opcodes import SpiNorFlashOpCodes as Codes
from litespi.phy.model import LiteSPIPHYModel

from .litex import (
    LITTLE64_LINUX_BREADCRUMB_UART_BASE,
    LITTLE64_LINUX_RAM_BASE,
    LITTLE64_LINUX_TIMER_BASE,
    LITTLE64_LITEX_MEM_MAP,
)
from .litex_cpu import register_little64_with_litex


_anonymous_csr_names = count()


def _install_litex_csr_name_fallback() -> None:
    original = migen_tracer.get_obj_var_name

    if getattr(litex_csr.get_obj_var_name, '_little64_wrapped', False):
        return

    def fallback(override=None, default=None):
        try:
            name = original(override=override, default=default)
        except Exception:
            name = None
        if name is None:
            base = default or 'csr'
            name = f'{base}_{next(_anonymous_csr_names)}'
        return name

    fallback._little64_wrapped = True
    migen_tracer.get_obj_var_name = fallback
    litex_csr.get_obj_var_name = fallback
    litex_csr_eventmanager.get_obj_var_name = fallback


SIM_IO = [
    ('sys_clk', 0, Pins(1)),
    ('sys_rst', 0, Pins(1)),
    ('breadcrumb', 0,
        Subsignal('data', Pins(8)),
        Subsignal('strobe', Pins(1)),
    ),
    ('serial', 0,
        Subsignal('source_valid', Pins(1)),
        Subsignal('source_ready', Pins(1)),
        Subsignal('source_data', Pins(8)),
        Subsignal('sink_valid', Pins(1)),
        Subsignal('sink_ready', Pins(1)),
        Subsignal('sink_data', Pins(8)),
    ),
    ('spiflash4x', 0,
        Subsignal('cs_n', Pins(1)),
        Subsignal('clk', Pins(1)),
        Subsignal('dq', Pins(4)),
    ),
]


def _load_spi_flash_init(image_path: Path) -> list[int]:
    return get_mem_data(str(image_path), data_width=32, endianness='big')


class Little64LiteXSimPlatform(SimPlatform):
    def __init__(self) -> None:
        super().__init__('SIM', SIM_IO)
        self.output_dir = str(Path('builddir') / 'litex-sim')


class Little64LiteXSimCRG(Module):
    def __init__(self, clk, rst) -> None:
        self.clock_domains.cd_sys = ClockDomain('sys')
        self.comb += [
            self.cd_sys.clk.eq(clk),
            self.cd_sys.rst.eq(rst),
        ]


class Little64BreadcrumbSerial(Module):
    def __init__(self, *, base_address: int = LITTLE64_LINUX_BREADCRUMB_UART_BASE) -> None:
        self.bus = wishbone.Interface(data_width=64, address_width=64, addressing='word')
        self.last_byte = Signal(8)
        self.tx_strobe = Signal()

        word_base = base_address >> 3
        selected_byte = Signal(8)

        self.comb += [
            self.bus.err.eq(0),
            self.bus.dat_r.eq(0x0000600000000000),
            selected_byte.eq(self.bus.dat_w[:8]),
        ]
        self.comb += Case(self.bus.sel, {
            0x01: selected_byte.eq(self.bus.dat_w[:8]),
            0x02: selected_byte.eq(self.bus.dat_w[8:16]),
            0x04: selected_byte.eq(self.bus.dat_w[16:24]),
            0x08: selected_byte.eq(self.bus.dat_w[24:32]),
            0x10: selected_byte.eq(self.bus.dat_w[32:40]),
            0x20: selected_byte.eq(self.bus.dat_w[40:48]),
            0x40: selected_byte.eq(self.bus.dat_w[48:56]),
            'default': selected_byte.eq(self.bus.dat_w[56:64]),
        })

        self.sync += [
            self.bus.ack.eq(0),
            self.tx_strobe.eq(0),
            If(self.bus.cyc & self.bus.stb & ~self.bus.ack,
                self.bus.ack.eq(1),
                If(self.bus.we & (self.bus.adr == word_base) & (self.bus.sel != 0),
                    self.last_byte.eq(selected_byte),
                    self.tx_strobe.eq(1),
                ),
            ),
        ]


class Little64LinuxTimer(Module):
    def __init__(self, *, sys_clk_freq: int, base_address: int = LITTLE64_LINUX_TIMER_BASE) -> None:
        self.bus = wishbone.Interface(data_width=64, address_width=64, addressing='word')
        self.irq = Signal()

        word_base = base_address >> 3
        offset_words = Signal(2)
        cycle_counter = Signal(64)
        ns_counter = Signal(64)
        cycle_interval = Signal(64)
        ns_interval = Signal(64)
        cycle_deadline = Signal(64)
        ns_deadline = Signal(64)
        ns_step = max(1, int(1_000_000_000 // max(1, int(sys_clk_freq))))

        self.comb += [
            self.bus.err.eq(0),
            self.bus.dat_r.eq(0),
            offset_words.eq(self.bus.adr - word_base),
        ]
        self.comb += Case(offset_words, {
            0: self.bus.dat_r.eq(cycle_counter),
            1: self.bus.dat_r.eq(ns_counter),
            2: self.bus.dat_r.eq(cycle_interval),
            'default': self.bus.dat_r.eq(ns_interval),
        })
        self.comb += self.irq.eq(
            ((cycle_interval != 0) & (cycle_counter >= cycle_deadline)) |
            ((ns_interval != 0) & (ns_counter >= ns_deadline))
        )



    def _load_spi_flash_init(image_path: Path) -> list[int]:
        return get_mem_data(str(image_path), data_width=32, endianness='little')
        self.sync += [
            self.bus.ack.eq(0),
            cycle_counter.eq(cycle_counter + 1),
            ns_counter.eq(ns_counter + ns_step),
            If((cycle_interval != 0) & (cycle_counter >= cycle_deadline),
                cycle_deadline.eq(cycle_deadline + cycle_interval),
            ),
            If((ns_interval != 0) & (ns_counter >= ns_deadline),
                ns_deadline.eq(ns_deadline + ns_interval),
            ),
            If(self.bus.cyc & self.bus.stb & ~self.bus.ack,
                self.bus.ack.eq(1),
                If(self.bus.we,
                    Case(offset_words, {
                        2: [
                            cycle_interval.eq(self.bus.dat_w),
                            cycle_deadline.eq(cycle_counter + self.bus.dat_w),
                        ],
                        3: [
                            ns_interval.eq(self.bus.dat_w),
                            ns_deadline.eq(ns_counter + self.bus.dat_w),
                        ],
                    }),
                ),
            ),
            If(cycle_interval == 0,
                cycle_deadline.eq(0),
            ),
            If(ns_interval == 0,
                ns_deadline.eq(0),
            ),
        ]


class Little64LiteXSimSoC(SoCCore):
    def __init__(
        self,
        *,
        sys_clk_freq: int = int(1e6),
        integrated_rom_size: int = 0,
        integrated_sram_size: int = 0x4000,
        integrated_main_ram_size: int = 0,
        with_sdram: bool = False,
        with_spi_flash: bool = False,
        sdram_module: str = 'MT48LC16M16',
        sdram_data_width: int = 64,
        sdram_init: list[int] | None = None,
        spi_flash_init: list[int] | None = None,
        spi_flash_image_path: str | Path | None = None,
        ident: str = 'Little64 LiteX Simulation',
        cpu_variant: str = 'standard',
        cpu_reset_address: int | None = None,
        boot_r1: int = 0,
        boot_stack_address: int | None = None,
        with_timer: bool = False,
        **kwargs,
    ) -> None:
        register_little64_with_litex()
        _install_litex_csr_name_fallback()

        platform = Little64LiteXSimPlatform()
        self.crg = Little64LiteXSimCRG(platform.request('sys_clk'), platform.request('sys_rst'))
        self.sys_clk_freq = int(sys_clk_freq)

        SoCCore.__init__(
            self,
            platform,
            clk_freq=self.sys_clk_freq,
            ident=ident,
            bus_data_width=64,
            bus_address_width=64,
            cpu_type='little64',
            cpu_variant=cpu_variant,
            cpu_reset_address=(
                LITTLE64_LITEX_MEM_MAP['spiflash']
                if cpu_reset_address is None and with_spi_flash and integrated_rom_size == 0
                else LITTLE64_LITEX_MEM_MAP['rom'] if cpu_reset_address is None else cpu_reset_address
            ),
            integrated_rom_size=integrated_rom_size,
            integrated_sram_size=integrated_sram_size,
            integrated_main_ram_size=integrated_main_ram_size,
            with_uart=True,
            uart_name='sim',
            with_timer=False,
            with_ctrl=False,
            **kwargs,
        )

        self.breadcrumb_serial = Little64BreadcrumbSerial()
        self.bus.add_slave(
            name='linux_breadcrumb_uart',
            slave=self.breadcrumb_serial.bus,
            region=SoCRegion(origin=LITTLE64_LINUX_BREADCRUMB_UART_BASE, size=0x100, cached=False),
        )
        breadcrumb_pads = platform.request('breadcrumb')
        self.comb += [
            breadcrumb_pads.data.eq(self.breadcrumb_serial.last_byte),
            breadcrumb_pads.strobe.eq(self.breadcrumb_serial.tx_strobe),
        ]

        if with_timer:
            self.linux_timer = Little64LinuxTimer(sys_clk_freq=self.sys_clk_freq)
            self.bus.add_slave(
                name='little64_timer_regs',
                slave=self.linux_timer.bus,
                region=SoCRegion(origin=LITTLE64_LINUX_TIMER_BASE, size=0x20, cached=False),
            )
            self.irq.add('little64_timer', use_loc_if_exists=True)
            self.comb += self.cpu.interrupt[self.irq.locs['little64_timer']].eq(self.linux_timer.irq)

        if with_sdram and not self.integrated_main_ram_size:
            sdram_init = [] if sdram_init is None else sdram_init
            sdram_module_cls = getattr(litedram_modules, sdram_module)
            sdram_rate = f"1:{sdram_module_nphases[sdram_module_cls.memtype]}"
            sdram_module_inst = sdram_module_cls(int(100e6), sdram_rate)
            self.sdrphy = SDRAMPHYModel(
                module=sdram_module_inst,
                data_width=sdram_data_width,
                clk_freq=int(100e6),
                init=sdram_init,
            )
            self.add_sdram(
                'sdram',
                phy=self.sdrphy,
                module=sdram_module_inst,
                l2_cache_size=0,
            )

        if with_spi_flash:
            if spi_flash_init is None and spi_flash_image_path is not None:
                spi_flash_init = _load_spi_flash_init(spi_flash_image_path)
            spi_flash_init = [] if spi_flash_init is None else spi_flash_init
            spiflash_module = S25FL128L(Codes.READ_1_1_4)
            self.spiflash_phy = LiteSPIPHYModel(spiflash_module, init=spi_flash_init)
            self.add_spi_flash(
                phy=self.spiflash_phy,
                mode='4x',
                module=spiflash_module,
                with_master=True,
            )

        if boot_stack_address is None:
            if 'sram' in self.bus.regions:
                sram_region = self.bus.regions['sram']
                boot_stack_address = sram_region.origin + sram_region.size
            elif 'main_ram' in self.bus.regions:
                boot_stack_address = LITTLE64_LINUX_RAM_BASE - 0x10
            else:
                boot_stack_address = LITTLE64_LITEX_MEM_MAP['rom'] + integrated_rom_size

        self.comb += [
            self.cpu.boot_r1.eq(boot_r1),
            self.cpu.boot_r13.eq(boot_stack_address),
        ]


def _dt_reg(origin: int, size: int) -> str:
    return f'<0x{origin >> 32:08x} 0x{origin & 0xFFFF_FFFF:08x} 0x{size >> 32:08x} 0x{size & 0xFFFF_FFFF:08x}>'


def _dt_irq_vector(soc: Little64LiteXSimSoC, name: str) -> int | None:
    if not hasattr(soc, 'irq'):
        return None
    irq_index = soc.irq.locs.get(name)
    if irq_index is None:
        return None
    return soc.cpu.first_irq_vector + irq_index


def generate_linux_dts(
    soc: Little64LiteXSimSoC,
    *,
    model: str = 'Little64 LiteX Simulation SoC',
    compatible: tuple[str, ...] = ('little64,litex-sim',),
    bootargs: str | None = None,
) -> str:
    if not soc.finalized:
        soc.finalize()

    compatible_text = ', '.join(f'"{entry}"' for entry in compatible)
    memory_region = soc.bus.regions.get('main_ram')
    ctrl_region = soc.csr.regions.get('ctrl')
    uart_region = soc.csr.regions.get('uart')
    spiflash_region = soc.bus.regions.get('spiflash')
    timer_region = soc.bus.regions.get('little64_timer_regs')
    uart_irq = _dt_irq_vector(soc, 'uart')
    timer_irq = _dt_irq_vector(soc, 'little64_timer')

    lines = [
        '/dts-v1/;',
        '',
        '/ {',
        '    #address-cells = <2>;',
        '    #size-cells = <2>;',
        f'    compatible = {compatible_text};',
        f'    model = "{model}";',
        '',
        '    aliases {',
    ]

    if uart_region is not None:
        lines.append('        serial0 = &uart0;')

    lines.extend([
        '    };',
        '',
        '    chosen {',
    ])

    if uart_region is not None:
        lines.append('        stdout-path = "serial0:115200n8";')
    if bootargs:
        lines.append(f'        bootargs = "{bootargs}";')

    lines.extend([
        '    };',
        '',
        '    cpus {',
        '        #address-cells = <1>;',
        '        #size-cells = <0>;',
        '',
        '        cpu@0 {',
        '            compatible = "little64";',
        '            device_type = "cpu";',
        '            reg = <0>;',
        f'            clock-frequency = <{soc.sys_clk_freq}>;',
        '        };',
        '    };',
        '',
        '    intc: interrupt-controller {',
        '        compatible = "little64,intc";',
        '        interrupt-controller;',
        '        #interrupt-cells = <1>;',
        '    };',
    ])

    if memory_region is not None:
        linux_memory_origin = max(memory_region.origin, LITTLE64_LINUX_RAM_BASE)
        linux_memory_size = (memory_region.origin + memory_region.size) - linux_memory_origin
        lines.extend([
            '',
            f'    memory@{linux_memory_origin:x} {{',
            '        device_type = "memory";',
            f'        reg = {_dt_reg(linux_memory_origin, linux_memory_size)};',
            '    };',
        ])

    lines.extend([
        '',
        '    soc {',
        '        compatible = "simple-bus";',
        '        #address-cells = <2>;',
        '        #size-cells = <2>;',
        '        ranges;',
    ])

    if ctrl_region is not None:
        lines.extend([
            '',
            f'        soc_ctrl0: soc-controller@{ctrl_region.origin:x} {{',
            '            compatible = "litex,soc-controller";',
            f'            reg = {_dt_reg(ctrl_region.origin, 0x0c)};',
            '        };',
        ])

    if uart_region is not None:
        lines.extend([
            '',
            f'        uart0: serial@{uart_region.origin:x} {{',
            '            compatible = "litex,liteuart";',
            f'            reg = {_dt_reg(uart_region.origin, 0x100)};',
        ])
        if uart_irq is not None:
            lines.extend([
                '            interrupt-parent = <&intc>;',
                f'            interrupts = <{uart_irq}>;',
            ])
        lines.append('        };')

    if spiflash_region is not None:
        lines.extend([
            '',
            f'        flash0: flash@{spiflash_region.origin:x} {{',
            '            compatible = "jedec-flash";',
            f'            reg = {_dt_reg(spiflash_region.origin, spiflash_region.size)};',
            '            bank-width = <1>;',
            '        };',
        ])

    if timer_region is not None:
        lines.extend([
            '',
            f'        timer0: timer@{timer_region.origin:x} {{',
            '            compatible = "little64,timer";',
            f'            reg = {_dt_reg(timer_region.origin, timer_region.size)};',
        ])
        if timer_irq is not None:
            lines.extend([
                '            interrupt-parent = <&intc>;',
                f'            interrupts = <{timer_irq}>;',
            ])
        lines.append('        };')

    lines.extend([
        '    };',
        '};',
        '',
    ])
    return '\n'.join(lines)