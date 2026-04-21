from __future__ import annotations

from dataclasses import dataclass, replace

from migen import ClockDomain, Signal

from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.gen import LiteXModule
from litex.soc.cores.clock import S7IDELAYCTRL, S7PLL

from litedram import modules as litedram_modules
from litedram.phy import s7ddrphy

from litespi.modules import S25FL128L
from litespi.opcodes import SpiNorFlashOpCodes as Codes

from .litex import Little64LiteXTarget, resolve_litex_target
from .litex_soc import Little64LiteXSoC


ARTY_PMOD_HEADERS = ('pmoda', 'pmodb', 'pmodc', 'pmodd')
ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33 = 'arduino-io30-33'
ARTY_SPI_SDCARD_PRESETS = (ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33,)


@dataclass(frozen=True, slots=True)
class Little64ArtySPISDCardMapping:
    name: str
    description: str
    clk: str
    mosi: str
    miso: str
    cs_n: str


LITTLE64_ARTY_SPI_SDCARD_MAPPINGS = {
    ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33: Little64ArtySPISDCardMapping(
        name=ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33,
        description='Arduino-style header mapping using Arty ck_io30..33',
        clk='R15',
        mosi='R13',
        miso='P15',
        cs_n='R11',
    ),
}


def resolve_arty_spi_sdcard_mapping(
    *,
    connector: str = 'arduino',
    adapter: str = 'digilent',
    clk: str | None = None,
    mosi: str | None = None,
    miso: str | None = None,
    cs_n: str | None = None,
) -> Little64ArtySPISDCardMapping:
    if connector == 'arduino':
        mapping = LITTLE64_ARTY_SPI_SDCARD_MAPPINGS[ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33]
    elif connector in ARTY_PMOD_HEADERS:
        if adapter == 'digilent':
            mapping = Little64ArtySPISDCardMapping(
                name=f'digilent-{connector}',
                description=f'Digilent MicroSD PMOD mapping on {connector}',
                clk=f'{connector}:3',
                mosi=f'{connector}:1',
                miso=f'{connector}:2',
                cs_n=f'{connector}:0',
            )
        elif adapter == 'numato':
            mapping = Little64ArtySPISDCardMapping(
                name=f'numato-{connector}',
                description=f'Numato MicroSD PMOD mapping on {connector}',
                clk=f'{connector}:5',
                mosi=f'{connector}:1',
                miso=f'{connector}:2',
                cs_n=f'{connector}:4',
            )
        else:
            raise ValueError(f'Unsupported Arty SPI SD card adapter: {adapter}')
    else:
        raise ValueError(f'Unsupported Arty SPI SD card connector: {connector}')

    return replace(
        mapping,
        clk=clk or mapping.clk,
        mosi=mosi or mapping.mosi,
        miso=miso or mapping.miso,
        cs_n=cs_n or mapping.cs_n,
    )


def arty_spi_sdcard_extension(mapping: Little64ArtySPISDCardMapping) -> list[tuple]:
    return [
        (
            'spisdcard', 0,
            Subsignal('clk', Pins(mapping.clk), Misc('SLEW=FAST')),
            Subsignal('mosi', Pins(mapping.mosi), Misc('PULLUP True'), Misc('SLEW=FAST')),
            Subsignal('cs_n', Pins(mapping.cs_n), Misc('PULLUP True'), Misc('SLEW=FAST')),
            Subsignal('miso', Pins(mapping.miso), Misc('PULLUP True')),
            IOStandard('LVCMOS33'),
        ),
    ]


def _import_digilent_arty_platform():
    try:
        from litex_boards.platforms import digilent_arty
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            'litex-boards is required for Arty hardware builds; install requirements-hdl.txt or add the package to your environment'
        ) from exc
    return digilent_arty


def create_arty_platform(*, variant: str = 'a7-35', toolchain: str = 'vivado'):
    digilent_arty = _import_digilent_arty_platform()
    return digilent_arty.Platform(variant=variant, toolchain=toolchain)


class Little64LiteXArtyCRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq: int, *, with_dram: bool) -> None:
        self.rst = Signal()
        self.cd_sys = ClockDomain('sys')
        if with_dram:
            self.cd_sys4x = ClockDomain('sys4x')
            self.cd_sys4x_dqs = ClockDomain('sys4x_dqs')
            self.cd_idelay = ClockDomain('idelay')

        clk100 = platform.request('clk100')
        rst_n = platform.request('cpu_reset_n')

        self.pll = pll = S7PLL(speedgrade=-1)
        self.comb += pll.reset.eq(~rst_n | self.rst)
        pll.register_clkin(clk100, 100e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)
        if with_dram:
            pll.create_clkout(self.cd_sys4x, 4 * sys_clk_freq)
            pll.create_clkout(self.cd_sys4x_dqs, 4 * sys_clk_freq, phase=90)
            pll.create_clkout(self.cd_idelay, 200e6)
            self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin)


class Little64LiteXArtySoC(Little64LiteXSoC):
    def __init__(
        self,
        *,
        sys_clk_freq: int = int(100e6),
        integrated_rom_size: int = 0,
        integrated_rom_init: list[int] | None = None,
        integrated_sram_size: int = 0x4000,
        integrated_main_ram_size: int = 0,
        main_ram_size: int | None = None,
        with_sdram: bool = True,
        with_spi_flash: bool = False,
        with_sdcard: bool = True,
        sdram_module: str = 'MT41K128M16',
        sdram_data_width: int = 16,
        ident: str | None = None,
        cpu_variant: str = 'standard',
        cpu_reset_address: int | None = None,
        litex_target: str | Little64LiteXTarget = 'arty-a7-35',
        boot_source: str | None = None,
        boot_r1: int = 0,
        boot_stack_address: int | None = None,
        spisdcard_mapping: Little64ArtySPISDCardMapping | None = None,
        board_variant: str = 'a7-35',
        toolchain: str = 'vivado',
        **kwargs,
    ) -> None:
        resolved_target = resolve_litex_target(litex_target)
        if board_variant != 'a7-35':
            raise ValueError('Little64 Arty hardware support currently targets only the A7-35T board variant')
        if not with_sdram and resolved_target.with_sdram:
            resolved_target = replace(resolved_target, with_sdram=False)
        if not with_sdcard and resolved_target.with_sdcard:
            resolved_target = replace(resolved_target, with_sdcard=False)
        if not with_spi_flash and resolved_target.with_spi_flash:
            resolved_target = replace(resolved_target, with_spi_flash=False)

        effective_with_sdram = with_sdram or resolved_target.with_sdram
        effective_with_sdcard = with_sdcard or resolved_target.with_sdcard

        platform = create_arty_platform(variant=board_variant, toolchain=toolchain)
        if effective_with_sdcard:
            if spisdcard_mapping is None:
                raise ValueError('An SPI SD card mapping is required when the Arty hardware SoC enables SD card support')
            platform.add_extension(arty_spi_sdcard_extension(spisdcard_mapping))

        self.crg = Little64LiteXArtyCRG(
            platform,
            int(sys_clk_freq),
            with_dram=effective_with_sdram and not integrated_main_ram_size,
        )

        super().__init__(
            platform,
            sys_clk_freq=sys_clk_freq,
            uart_name='serial',
            integrated_rom_size=integrated_rom_size,
            integrated_rom_init=integrated_rom_init,
            integrated_sram_size=integrated_sram_size,
            integrated_main_ram_size=integrated_main_ram_size,
            main_ram_size=main_ram_size,
            with_sdram=with_sdram,
            with_spi_flash=with_spi_flash,
            with_sdcard=with_sdcard,
            sdcard_mode='spi',
            sdram_module=sdram_module,
            sdram_data_width=sdram_data_width,
            ident=ident,
            cpu_variant=cpu_variant,
            cpu_reset_address=cpu_reset_address,
            litex_target=resolved_target,
            boot_source=boot_source,
            boot_r1=boot_r1,
            boot_stack_address=boot_stack_address,
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
        if sdram_init:
            raise ValueError('Arty hardware builds do not support preloading SDRAM init contents')
        sdram_module_cls = getattr(litedram_modules, sdram_module)
        sdram_rate = '1:4'
        sdram_module_inst = sdram_module_cls(self.sys_clk_freq, sdram_rate)
        self.ddrphy = s7ddrphy.A7DDRPHY(
            pads=self.platform.request('ddram'),
            memtype=sdram_module_inst.memtype,
            nphases=4,
            sys_clk_freq=self.sys_clk_freq,
        )
        self.add_sdram(
            'sdram',
            phy=self.ddrphy,
            module=sdram_module_inst,
            l2_cache_size=0,
            size=main_ram_size,
        )

    def _configure_spi_flash(
        self,
        *,
        spi_flash_init: list[int] | None,
        spi_flash_image_path: str | None,
    ) -> None:
        if spi_flash_init is not None or spi_flash_image_path is not None:
            raise ValueError('Arty hardware builds expose the on-board SPI flash controller only; preloaded flash images are not supported here')
        self.add_spi_flash(
            mode='4x',
            module=S25FL128L(Codes.READ_1_1_4),
            with_master=True,
        )