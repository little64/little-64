from __future__ import annotations

from pathlib import Path
from itertools import count

from migen import Case, ClockDomain, If, Module, Signal
from migen.fhdl import tracer as migen_tracer

from litex.build.generic_platform import Pins, Subsignal
from litex.build.sim import SimPlatform
from litex.soc.cores.spi import SPIMaster
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
    LITTLE64_LINUX_RAM_BASE,
    LITTLE64_LINUX_TIMER_BASE,
    LITTLE64_LITEX_BOOTROM_SIZE,
    LITTLE64_LITEX_BOOT_SOURCE_BOOTROM,
    LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH,
    litex_mem_map_for_target,
    Little64LiteXTarget,
    normalize_litex_boot_source,
    resolve_litex_target,
)
from .litex_cpu import register_little64_with_litex
from .litex_sdcard import Little64SDCardImageBridge, Little64SDEmulator


_anonymous_csr_names = count()
LITTLE64_SPI_SDCARD_DATA_WIDTH = 32


def _py311_get_var_name(frame) -> str | None:
    """Python 3.11+ compatible replacement for ``migen.fhdl.tracer.get_var_name``.

    Migen's upstream tracer only knows about the pre-3.11 ``CALL_FUNCTION``
    family of opcodes; on Python 3.11+ (where the interpreter emits the
    consolidated ``CALL`` opcode) it returns ``None`` for every CSR
    construction. That causes the anonymous-name fallback below to assign
    numbered ``csr_N`` names to every CSR, which in turn breaks liblitedram
    because it relies on properly named accessors such as
    ``sdram_dfii_pi0_command_write``.

    This helper walks the instruction stream forward from the current CALL,
    skipping common loader/build opcodes used to assemble attribute chains,
    until it reaches a ``STORE_*`` that names the result.
    """
    import dis
    code = frame.f_code
    lasti = frame.f_lasti
    instructions = list(dis.get_instructions(code))
    call_idx = None
    for idx, ins in enumerate(instructions):
        if ins.offset == lasti:
            call_idx = idx
            break
    if call_idx is None:
        return None
    if instructions[call_idx].opname not in ('CALL', 'CALL_KW', 'CALL_FUNCTION_EX'):
        return None
    skip_opnames = {
        'LOAD_GLOBAL', 'LOAD_ATTR', 'LOAD_FAST', 'LOAD_DEREF',
        'LOAD_METHOD', 'LOAD_CONST', 'LOAD_NAME', 'LOAD_CLOSURE',
        'COPY', 'SWAP', 'PUSH_NULL', 'RESUME',
        'BUILD_LIST', 'BUILD_TUPLE', 'BUILD_MAP', 'BUILD_SET',
        'KW_NAMES', 'PRECALL',
    }
    for ins in instructions[call_idx + 1:]:
        if ins.opname in ('STORE_NAME', 'STORE_ATTR', 'STORE_FAST', 'STORE_DEREF', 'STORE_GLOBAL'):
            return ins.argval
        if ins.opname in skip_opnames:
            continue
        return None
    return None


def _install_litex_csr_name_fallback() -> None:
    original = migen_tracer.get_obj_var_name

    if getattr(litex_csr.get_obj_var_name, '_little64_wrapped', False):
        return

    def _remove_underscore(s: str) -> str:
        if len(s) > 2 and s[0] == '_' and s[1] != '_':
            return s[1:]
        return s

    def fallback(override=None, default=None):
        if override:
            return override

        try:
            name = original(override=None, default=None)
        except Exception:
            name = None

        if name is None:
            import inspect
            try:
                frame = inspect.currentframe().f_back
                # Walk up derived-class constructors the same way migen's
                # upstream tracer does, so we end at the actual assignment
                # site (e.g. ``self._command = CSRStorage(...)``).
                if 'self' in frame.f_locals:
                    ourclass = frame.f_locals['self'].__class__
                    while 'self' in frame.f_locals and isinstance(frame.f_locals['self'], ourclass):
                        frame = frame.f_back
                name = _py311_get_var_name(frame)
                if name is not None:
                    name = _remove_underscore(name)
            except Exception:
                name = None

        if name is None:
            name = default
        if name is None:
            name = f'csr_{next(_anonymous_csr_names)}'
        return name

    fallback._little64_wrapped = True
    migen_tracer.get_obj_var_name = fallback
    litex_csr.get_obj_var_name = fallback
    litex_csr_eventmanager.get_obj_var_name = fallback


SIM_IO = [
    ('sys_clk', 0, Pins(1)),
    ('sys_rst', 0, Pins(1)),
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
    ('spisdcard', 0,
        Subsignal('clk', Pins(1)),
        Subsignal('mosi', Pins(1)),
        Subsignal('cs_n', Pins(1)),
        Subsignal('miso', Pins(1)),
    ),
    ('sdcard_img', 0,
        Subsignal('req', Pins(1)),
        Subsignal('byteaddr', Pins(32)),
        Subsignal('write_addr', Pins(7)),
        Subsignal('write_data', Pins(32)),
        Subsignal('write_enable', Pins(1)),
        Subsignal('done', Pins(1)),
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
                If(self.bus.we & (self.bus.sel == 0xFF),
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


class Little64LiteXSoC(SoCCore):
    def __init__(
        self,
        platform,
        *,
        sys_clk_freq: int = int(1e6),
        uart_name: str = 'serial',
        integrated_rom_size: int = 0,
        integrated_rom_init: list[int] | None = None,
        integrated_sram_size: int = 0x4000,
        integrated_main_ram_size: int = 0,
        main_ram_size: int | None = None,
        with_sdram: bool = False,
        with_spi_flash: bool = False,
        with_sdcard: bool = False,
        sdcard_mode: str = 'native',
        sdram_module: str = 'MT48LC16M16',
        sdram_data_width: int = 64,
        sdram_init: list[int] | None = None,
        spi_flash_init: list[int] | None = None,
        spi_flash_image_path: str | Path | None = None,
        sdcard_image_path: str | Path | None = None,
        ident: str | None = None,
        cpu_variant: str = 'standard',
        cpu_reset_address: int | None = None,
        litex_target: str | Little64LiteXTarget = 'sim-flash',
        boot_source: str | None = None,
        boot_r1: int = 0,
        boot_stack_address: int | None = None,
        with_timer: bool = False,
        **kwargs,
    ) -> None:
        register_little64_with_litex()
        _install_litex_csr_name_fallback()

        if not hasattr(self, 'crg'):
            raise ValueError('Little64LiteXSoC subclasses must create self.crg before SoCCore initialization')

        self.litex_target = resolve_litex_target(litex_target)
        requested_boot_source = normalize_litex_boot_source(boot_source or self.litex_target.boot_source)
        implicit_bootrom_fallback = (
            boot_source is None and
            requested_boot_source == LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH and
            not with_spi_flash
        )
        self.boot_source = (
            LITTLE64_LITEX_BOOT_SOURCE_BOOTROM
            if implicit_bootrom_fallback else requested_boot_source
        )
        resolved_integrated_rom_size = integrated_rom_size
        if self.boot_source == LITTLE64_LITEX_BOOT_SOURCE_BOOTROM and not implicit_bootrom_fallback:
            resolved_integrated_rom_size = max(
                resolved_integrated_rom_size,
                self.litex_target.integrated_rom_size,
                LITTLE64_LITEX_BOOTROM_SIZE,
            )

        resolved_with_spi_flash = with_spi_flash or self.litex_target.with_spi_flash
        resolved_with_sdcard = with_sdcard or self.litex_target.with_sdcard
        resolved_with_sdram = with_sdram or self.litex_target.with_sdram
        resolved_sdram_module = (
            self.litex_target.sdram_module
            if sdram_module == 'MT48LC16M16' and self.litex_target.sdram_module != 'MT48LC16M16'
            else sdram_module
        )
        resolved_main_ram_size = (
            self.litex_target.default_ram_size
            if main_ram_size is None and resolved_with_sdram and not integrated_main_ram_size
            else integrated_main_ram_size if main_ram_size is None else main_ram_size
        )

        platform.little64_mem_map = litex_mem_map_for_target(self.litex_target, boot_source=self.boot_source)
        self.sys_clk_freq = int(sys_clk_freq)
        integrated_rom_init = [] if integrated_rom_init is None else integrated_rom_init
        kwargs.setdefault('uart_with_dynamic_baudrate', True)

        SoCCore.__init__(
            self,
            platform,
            clk_freq=self.sys_clk_freq,
            ident=ident or self.litex_target.model,
            bus_data_width=64,
            bus_address_width=64,
            cpu_type='little64',
            cpu_variant=cpu_variant,
            cpu_reset_address=(
                platform.little64_mem_map['spiflash']
                if cpu_reset_address is None and self.boot_source == LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH
                else platform.little64_mem_map['rom'] if cpu_reset_address is None else cpu_reset_address
            ),
            integrated_rom_size=resolved_integrated_rom_size,
            integrated_rom_init=integrated_rom_init,
            integrated_sram_size=integrated_sram_size,
            integrated_main_ram_size=integrated_main_ram_size,
            with_uart=True,
            uart_name=uart_name,
            with_timer=False,
            with_ctrl=False,
            **kwargs,
        )

        if with_timer:
            self.linux_timer = Little64LinuxTimer(sys_clk_freq=self.sys_clk_freq)
            self.bus.add_slave(
                name='little64_timer_regs',
                slave=self.linux_timer.bus,
                region=SoCRegion(origin=LITTLE64_LINUX_TIMER_BASE, size=0x20, cached=False),
            )
            self.irq.add('little64_timer', use_loc_if_exists=True)
            self.comb += self.cpu.interrupt[self.irq.locs['little64_timer']].eq(self.linux_timer.irq)

        if resolved_with_sdram and not self.integrated_main_ram_size:
            self._configure_main_ram(
                sdram_module=resolved_sdram_module,
                sdram_data_width=sdram_data_width,
                sdram_init=sdram_init,
                main_ram_size=resolved_main_ram_size,
            )

        if resolved_with_spi_flash:
            self._configure_spi_flash(
                spi_flash_init=spi_flash_init,
                spi_flash_image_path=spi_flash_image_path,
            )

        if resolved_with_sdcard:
            self._configure_sdcard(mode=sdcard_mode, sdcard_image_path=sdcard_image_path)

        if boot_stack_address is None:
            if 'sram' in self.bus.regions:
                sram_region = self.bus.regions['sram']
                boot_stack_address = sram_region.origin + sram_region.size
            elif 'main_ram' in self.bus.regions:
                boot_stack_address = LITTLE64_LINUX_RAM_BASE - 0x10
            else:
                boot_stack_address = platform.little64_mem_map['rom'] + resolved_integrated_rom_size

        self.comb += [
            self.cpu.boot_r1.eq(boot_r1),
            self.cpu.boot_r13.eq(boot_stack_address),
        ]

    def _configure_main_ram(
        self,
        *,
        sdram_module: str,
        sdram_data_width: int,
        sdram_init: list[int] | None,
        main_ram_size: int,
    ) -> None:
        raise NotImplementedError()

    def _configure_spi_flash(
        self,
        *,
        spi_flash_init: list[int] | None,
        spi_flash_image_path: str | Path | None,
    ) -> None:
        raise NotImplementedError()

    def _add_spi_sdcard(self, name: str = 'spisdcard', *, spi_clk_freq: float = 400e3, data_width: int = LITTLE64_SPI_SDCARD_DATA_WIDTH) -> None:
        spi_sdcard_pads = self.platform.request(name)
        if hasattr(spi_sdcard_pads, 'rst'):
            self.comb += spi_sdcard_pads.rst.eq(0)

        self.check_if_exists(name)
        spisdcard = SPIMaster(
            pads=spi_sdcard_pads,
            data_width=data_width,
            sys_clk_freq=self.sys_clk_freq,
            spi_clk_freq=spi_clk_freq,
        )
        spisdcard.add_clk_divider()
        self.add_module(name=name, module=spisdcard)

    def _configure_sdcard(self, *, mode: str, sdcard_image_path: str | Path | None) -> None:
        if mode == 'native':
            if sdcard_image_path is None:
                self.add_sdcard('sdcard', use_emulator=True)
            else:
                self._add_sdcard_with_image_emulator('sdcard')
            return
        if mode == 'spi':
            if sdcard_image_path is not None:
                raise ValueError('sdcard_image_path is only supported for native LiteSDCard mode')
            self._add_spi_sdcard('spisdcard')
            return
        raise ValueError(f'Unsupported Little64 LiteX SD card mode: {mode}')


class Little64LiteXSimSoC(Little64LiteXSoC):
    def __init__(
        self,
        *,
        sys_clk_freq: int = int(1e6),
        integrated_rom_size: int = 0,
        integrated_rom_init: list[int] | None = None,
        integrated_sram_size: int = 0x4000,
        integrated_main_ram_size: int = 0,
        main_ram_size: int | None = None,
        with_sdram: bool = False,
        with_spi_flash: bool = False,
        with_sdcard: bool = False,
        sdcard_mode: str = 'native',
        sdram_module: str = 'MT48LC16M16',
        sdram_data_width: int = 64,
        sdram_init: list[int] | None = None,
        spi_flash_init: list[int] | None = None,
        spi_flash_image_path: str | Path | None = None,
        sdcard_image_path: str | Path | None = None,
        ident: str | None = None,
        cpu_variant: str = 'standard',
        cpu_reset_address: int | None = None,
        litex_target: str | Little64LiteXTarget = 'sim-flash',
        boot_source: str | None = None,
        boot_r1: int = 0,
        boot_stack_address: int | None = None,
        with_timer: bool = False,
        **kwargs,
    ) -> None:
        platform = Little64LiteXSimPlatform()
        self.crg = Little64LiteXSimCRG(platform.request('sys_clk'), platform.request('sys_rst'))
        super().__init__(
            platform,
            sys_clk_freq=sys_clk_freq,
            uart_name='sim',
            integrated_rom_size=integrated_rom_size,
            integrated_rom_init=integrated_rom_init,
            integrated_sram_size=integrated_sram_size,
            integrated_main_ram_size=integrated_main_ram_size,
            main_ram_size=main_ram_size,
            with_sdram=with_sdram,
            with_spi_flash=with_spi_flash,
            with_sdcard=with_sdcard,
            sdcard_mode=sdcard_mode,
            sdram_module=sdram_module,
            sdram_data_width=sdram_data_width,
            sdram_init=sdram_init,
            spi_flash_init=spi_flash_init,
            spi_flash_image_path=spi_flash_image_path,
            sdcard_image_path=sdcard_image_path,
            ident=ident,
            cpu_variant=cpu_variant,
            cpu_reset_address=cpu_reset_address,
            litex_target=litex_target,
            boot_source=boot_source,
            boot_r1=boot_r1,
            boot_stack_address=boot_stack_address,
            with_timer=with_timer,
            **kwargs,
        )

    def _configure_main_ram(
        self,
        *,
        sdram_module: str,
        sdram_data_width: int,
        sdram_init: list[int] | None,
        main_ram_size: int,
    ) -> None:
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
        if 'main_ram' in self.bus.regions and main_ram_size:
            self.bus.regions['main_ram'].size = main_ram_size

    def _configure_spi_flash(
        self,
        *,
        spi_flash_init: list[int] | None,
        spi_flash_image_path: str | Path | None,
    ) -> None:
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

    def _add_sdcard_with_image_emulator(self, name: str) -> None:
        from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceLevel, EventSourcePulse
        from litex.soc.interconnect import wishbone as litex_wishbone
        from litesdcard.core import SDCore
        from litesdcard.frontend.dma import SDBlock2MemDMA, SDMem2BlockDMA
        from litesdcard.phy import SDPHY

        sdemulator = Little64SDEmulator(self.platform)
        self.submodules += sdemulator
        self.__dict__[f'{name}_sdemulator'] = sdemulator

        image_bridge = Little64SDCardImageBridge(self.platform, sdemulator)
        self.add_module(name=f'{name}_image_bridge', module=image_bridge)

        sdcard_phy = SDPHY(sdemulator.pads, self.platform.device, self.clk_freq, cmd_timeout=10e-1, data_timeout=10e-1)
        sdcard_core = SDCore(sdcard_phy)
        self.add_module(name=f'{name}_phy', module=sdcard_phy)
        self.add_module(name=f'{name}_core', module=sdcard_core)

        block2mem_bus = litex_wishbone.Interface(
            data_width=self.bus.data_width,
            adr_width=self.bus.get_address_width(standard='wishbone'),
            addressing='word',
        )
        sdcard_block2mem = SDBlock2MemDMA(bus=block2mem_bus, endianness=self.cpu.endianness)
        self.add_module(name=f'{name}_block2mem', module=sdcard_block2mem)
        self.comb += sdcard_core.source.connect(sdcard_block2mem.sink)
        dma_bus = getattr(self, 'dma_bus', self.bus)
        dma_bus.add_master(name=f'{name}_block2mem', master=block2mem_bus)

        mem2block_bus = litex_wishbone.Interface(
            data_width=self.bus.data_width,
            adr_width=self.bus.get_address_width(standard='wishbone'),
            addressing='word',
        )
        sdcard_mem2block = SDMem2BlockDMA(bus=mem2block_bus, endianness=self.cpu.endianness)
        self.add_module(name=f'{name}_mem2block', module=sdcard_mem2block)
        self.comb += sdcard_mem2block.source.connect(sdcard_core.sink)
        dma_bus.add_master(name=f'{name}_mem2block', master=mem2block_bus)

        sdcard_irq = EventManager()
        self.add_module(name=f'{name}_irq', module=sdcard_irq)
        sdcard_irq.card_detect = EventSourcePulse(description='SDCard has been ejected/inserted.')
        sdcard_irq.block2mem_dma = EventSourcePulse(description='Block2Mem DMA terminated.')
        sdcard_irq.mem2block_dma = EventSourcePulse(description='Mem2Block DMA terminated.')
        sdcard_irq.cmd_done = EventSourceLevel(description='Command completed.')
        sdcard_irq.finalize()

        self.comb += [
            sdcard_irq.block2mem_dma.trigger.eq(sdcard_block2mem.irq),
            sdcard_irq.mem2block_dma.trigger.eq(sdcard_mem2block.irq),
            sdcard_irq.card_detect.trigger.eq(sdcard_phy.card_detect_irq),
            sdcard_irq.cmd_done.trigger.eq(sdcard_core.cmd_event.fields.done),
        ]
        if self.irq.enabled:
            self.irq.add(f'{name}_irq', use_loc_if_exists=True)


def _dt_reg(origin: int, size: int) -> str:
    return f'<0x{origin >> 32:08x} 0x{origin & 0xFFFF_FFFF:08x} 0x{size >> 32:08x} 0x{size & 0xFFFF_FFFF:08x}>'


def _dt_irq_vector(soc: Little64LiteXSoC, name: str) -> int | None:
    if not hasattr(soc, 'irq'):
        return None
    irq_index = soc.irq.locs.get(name)
    if irq_index is None:
        return None
    return soc.cpu.first_irq_vector + irq_index


def generate_linux_dts(
    soc: Little64LiteXSoC,
    *,
    model: str | None = None,
    compatible: tuple[str, ...] | None = None,
    bootargs: str | None = None,
) -> str:
    if not soc.finalized:
        soc.finalize()

    model_text = model or soc.litex_target.model
    compatible_entries = compatible or soc.litex_target.compatible
    compatible_text = ', '.join(f'"{entry}"' for entry in compatible_entries)
    rom_region = soc.bus.regions.get('rom')
    memory_region = soc.bus.regions.get('main_ram')
    ctrl_region = soc.csr.regions.get('ctrl')
    uart_region = soc.csr.regions.get('uart')
    spiflash_region = soc.bus.regions.get('spiflash')
    sdcard_phy_region = soc.csr.regions.get('sdcard_phy')
    sdcard_core_region = soc.csr.regions.get('sdcard_core')
    sdcard_block2mem_region = soc.csr.regions.get('sdcard_block2mem')
    sdcard_mem2block_region = soc.csr.regions.get('sdcard_mem2block')
    sdcard_irq_region = soc.csr.regions.get('sdcard_irq')
    timer_region = soc.bus.regions.get('little64_timer_regs')
    csr_window_size = 0x100
    uart_irq = _dt_irq_vector(soc, 'uart')
    sdcard_irq = _dt_irq_vector(soc, 'sdcard_irq')
    timer_irq = _dt_irq_vector(soc, 'little64_timer')

    lines = [
        '/dts-v1/;',
        '',
        '/ {',
        '    #address-cells = <2>;',
        '    #size-cells = <2>;',
        f'    compatible = {compatible_text};',
        f'    model = "{model_text}";',
        '',
        '    aliases {',
    ]

    if uart_region is not None:
        lines.append('        serial0 = &uart0;')
    if sdcard_phy_region is not None:
        lines.append('        sdcard0 = &mmc0;')

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

    if sdcard_phy_region is not None:
        lines.extend([
            '',
            '    sys_clk: clock {',
            '        compatible = "fixed-clock";',
            '        #clock-cells = <0>;',
            f'        clock-frequency = <{soc.sys_clk_freq}>;',
            '    };',
            '',
            '    vreg_mmc: vreg_mmc {',
            '        compatible = "regulator-fixed";',
            '        regulator-name = "vreg_mmc";',
            '        regulator-min-microvolt = <3300000>;',
            '        regulator-max-microvolt = <3300000>;',
            '        regulator-always-on;',
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

    if rom_region is not None:
        lines.extend([
            '',
            f'        bootrom0: rom@{rom_region.origin:x} {{',
            '            compatible = "little64,bootrom";',
            f'            reg = {_dt_reg(rom_region.origin, rom_region.size)};',
            '        };',
        ])

    if (
        sdcard_phy_region is not None and
        sdcard_core_region is not None and
        sdcard_block2mem_region is not None and
        sdcard_mem2block_region is not None and
        sdcard_irq_region is not None
    ):
        lines.extend([
            '',
            f'        mmc0: mmc@{sdcard_phy_region.origin:x} {{',
            '            compatible = "litex,mmc";',
            f'            reg = {_dt_reg(sdcard_phy_region.origin, csr_window_size)},',
            f'                  {_dt_reg(sdcard_core_region.origin, csr_window_size)},',
            f'                  {_dt_reg(sdcard_block2mem_region.origin, csr_window_size)},',
            f'                  {_dt_reg(sdcard_mem2block_region.origin, csr_window_size)},',
            f'                  {_dt_reg(sdcard_irq_region.origin, csr_window_size)};',
            '            reg-names = "phy", "core", "reader", "writer", "irq";',
            '            clocks = <&sys_clk>;',
            '            vmmc-supply = <&vreg_mmc>;',
            '            bus-width = <4>;',
        ])
        if sdcard_irq is not None:
            lines.extend([
                '            interrupt-parent = <&intc>;',
                f'            interrupts = <{sdcard_irq}>;',
            ])
        lines.append('        };')

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