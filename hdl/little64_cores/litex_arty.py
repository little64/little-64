from __future__ import annotations

import os

from dataclasses import dataclass, replace
from typing import Literal

from migen import ClockDomain, If, Instance, Module, Replicate, Signal

from litex.build.generic_platform import IOStandard, Misc, Pins, Subsignal
from litex.build.io import SDRTristate
from litex.build.xilinx.common import XilinxSDRTristate
from litex.gen import LiteXModule
from litex.soc.interconnect.csr import CSRField, CSRStatus
from litex.soc.cores.clock import S7IDELAYCTRL, S7PLL

from litedram import modules as litedram_modules
from litedram.phy import s7ddrphy

from litespi.modules import S25FL128L
from litespi.opcodes import SpiNorFlashOpCodes as Codes

from .litex import Little64LiteXTarget, resolve_litex_target
from .litex_soc import Little64LiteXSoC


ARTY_PMOD_HEADERS = ('pmoda', 'pmodb', 'pmodc', 'pmodd')
ARTY_SDCARD_MODE_NATIVE = 'native'
ARTY_SDCARD_MODE_SPI = 'spi'
ARTY_SDCARD_MODES = (ARTY_SDCARD_MODE_NATIVE, ARTY_SDCARD_MODE_SPI)
ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33 = 'arduino-io30-33'
ARTY_SPI_SDCARD_PRESETS = (ARTY_SPI_SDCARD_PRESET_ARDUINO_IO30_33,)
ARTY_NATIVE_SDCARD_PRESET_ARDUINO_IO34_40 = 'arduino-io34-40'
ARTY_NATIVE_SDCARD_PRESETS = (ARTY_NATIVE_SDCARD_PRESET_ARDUINO_IO34_40,)
ARTY_USER_LED_COUNT = 4
ARTY_RGB_LED_COUNT = 4
# Hardware validation on the Arty board shows the RGB channels behave as
# active-high in this integration path, so keep the board-local debug LED
# mapping non-inverted.
ARTY_RGB_LED_ACTIVE_LOW = False


@dataclass(frozen=True, slots=True)
class Little64ArtySPISDCardMapping:
    name: str
    description: str
    clk: str
    mosi: str
    miso: str
    cs_n: str


@dataclass(frozen=True, slots=True)
class Little64ArtyNativeSDCardMapping:
    name: str
    description: str
    clk: str
    cmd: str
    data0: str
    data1: str
    data2: str
    data3: str
    det: str | None = None


ArtySDCardMode = Literal['native', 'spi']
Little64ArtySDCardMapping = Little64ArtySPISDCardMapping | Little64ArtyNativeSDCardMapping


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

LITTLE64_ARTY_NATIVE_SDCARD_MAPPINGS = {
    ARTY_NATIVE_SDCARD_PRESET_ARDUINO_IO34_40: Little64ArtyNativeSDCardMapping(
        name=ARTY_NATIVE_SDCARD_PRESET_ARDUINO_IO34_40,
        description='Arduino-style Adafruit SDIO breakout header mapping using Arty ck_io34..40',
        clk='R16',
        cmd='N14',
        data0='N16',
        data1='T18',
        data2='R18',
        data3='U17',
        det='P18',
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


def resolve_arty_native_sdcard_mapping(
    *,
    connector: str = 'arduino',
    adapter: str = 'digilent',
    clk: str | None = None,
    cmd: str | None = None,
    data0: str | None = None,
    data1: str | None = None,
    data2: str | None = None,
    data3: str | None = None,
    det: str | None = None,
) -> Little64ArtyNativeSDCardMapping:
    if connector == 'arduino':
        mapping = LITTLE64_ARTY_NATIVE_SDCARD_MAPPINGS[ARTY_NATIVE_SDCARD_PRESET_ARDUINO_IO34_40]
    elif connector in ARTY_PMOD_HEADERS:
        if adapter == 'digilent':
            mapping = Little64ArtyNativeSDCardMapping(
                name=f'digilent-{connector}',
                description=f'Digilent MicroSD PMOD mapping on {connector}',
                clk=f'{connector}:3',
                cmd=f'{connector}:1',
                data0=f'{connector}:2',
                data1=f'{connector}:4',
                data2=f'{connector}:5',
                data3=f'{connector}:0',
                det=f'{connector}:6',
            )
        elif adapter == 'numato':
            mapping = Little64ArtyNativeSDCardMapping(
                name=f'numato-{connector}',
                description=f'Numato MicroSD PMOD mapping on {connector}',
                clk=f'{connector}:5',
                cmd=f'{connector}:1',
                data0=f'{connector}:2',
                data1=f'{connector}:6',
                data2=f'{connector}:0',
                data3=f'{connector}:4',
                det=None,
            )
        else:
            raise ValueError(f'Unsupported Arty native SD card adapter: {adapter}')
    else:
        raise ValueError(f'Unsupported Arty native SD card connector: {connector}')

    return replace(
        mapping,
        clk=clk or mapping.clk,
        cmd=cmd or mapping.cmd,
        data0=data0 or mapping.data0,
        data1=data1 or mapping.data1,
        data2=data2 or mapping.data2,
        data3=data3 or mapping.data3,
        det=det if det is not None else mapping.det,
    )


def resolve_arty_sdcard_mapping(
    *,
    mode: ArtySDCardMode = ARTY_SDCARD_MODE_NATIVE,
    connector: str = 'arduino',
    adapter: str = 'digilent',
    clk: str | None = None,
    mosi: str | None = None,
    miso: str | None = None,
    cs_n: str | None = None,
    cmd: str | None = None,
    data0: str | None = None,
    data1: str | None = None,
    data2: str | None = None,
    data3: str | None = None,
    det: str | None = None,
) -> Little64ArtySDCardMapping:
    if mode == ARTY_SDCARD_MODE_SPI:
        return resolve_arty_spi_sdcard_mapping(
            connector=connector,
            adapter=adapter,
            clk=clk,
            mosi=mosi,
            miso=miso,
            cs_n=cs_n,
        )
    if mode == ARTY_SDCARD_MODE_NATIVE:
        return resolve_arty_native_sdcard_mapping(
            connector=connector,
            adapter=adapter,
            clk=clk,
            cmd=cmd,
            data0=data0,
            data1=data1,
            data2=data2,
            data3=data3,
            det=det,
        )
    raise ValueError(f'Unsupported Arty SD card mode: {mode}')


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


def arty_native_sdcard_extension(mapping: Little64ArtyNativeSDCardMapping) -> list[tuple]:
    resource = [
        (
            'sdcard', 0,
            Subsignal('data', Pins(f'{mapping.data0} {mapping.data1} {mapping.data2} {mapping.data3}'), Misc('SLEW=FAST'), Misc('PULLUP True')),
            Subsignal('cmd', Pins(mapping.cmd), Misc('SLEW=FAST'), Misc('PULLUP True')),
            Subsignal('clk', Pins(mapping.clk), Misc('SLEW=FAST')),
        )
    ]
    if mapping.det is not None:
        resource[0] += (Subsignal('cd', Pins(mapping.det)),)
    resource[0] += (IOStandard('LVCMOS33'),)
    return resource


def _import_digilent_arty_platform():
    try:
        from litex_boards.platforms import digilent_arty
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            'litex-boards is required for Arty hardware builds; install requirements-hdl.txt or add the package to your environment'
        ) from exc
    return digilent_arty


class _Little64XilinxSDRTristateImpl(Module):
    def __init__(self, io, o, oe, i, clk):
        output_enable_bus = Signal(len(io), name='little64_sd_output_enable_bus')

        self.comb += output_enable_bus.eq(_little64_sd_output_enable_bus(oe, len(io)))

        for bit in range(len(io)):
            data_out = Signal(name=f'little64_sd_data_out_{bit}')
            output_enable = Signal(name=f'little64_sd_output_enable_{bit}')
            tristate_n = Signal(name=f'little64_sd_tristate_n_{bit}')
            data_in = Signal(name=f'little64_sd_data_in_{bit}')

            self.comb += output_enable.eq(output_enable_bus[bit])

            self.specials += Instance(
                'ODDR',
                p_DDR_CLK_EDGE='SAME_EDGE',
                i_C=clk,
                i_CE=1,
                i_S=0,
                i_R=0,
                i_D1=o[bit],
                i_D2=o[bit],
                o_Q=data_out,
            )
            self.specials += Instance(
                'ODDR',
                p_DDR_CLK_EDGE='SAME_EDGE',
                i_C=clk,
                i_CE=1,
                i_S=0,
                i_R=0,
                i_D1=~output_enable,
                i_D2=~output_enable,
                o_Q=tristate_n,
            )
            self.specials += Instance(
                'IDDR',
                p_DDR_CLK_EDGE='SAME_EDGE',
                i_C=clk,
                i_CE=1,
                i_S=0,
                i_R=0,
                i_D=data_in,
                o_Q1=i[bit],
                o_Q2=Signal(),
            )
            self.specials += Instance(
                'IOBUF',
                io_IO=io[bit],
                o_O=data_in,
                i_I=data_out,
                i_T=tristate_n,
            )


class _Little64XilinxSDRTristate:
    @staticmethod
    def lower(dr):
        if len(dr.io) == 1 and os.environ.get('LITTLE64_ARTY_FORCE_CMD_WAVE') == '1':
            return _Little64ForcedCMDWaveTristateImpl(dr.io, dr.i, dr.clk)
        if len(dr.io) == 1:
            return XilinxSDRTristate.lower(dr)
        return _Little64XilinxSDRTristateImpl(dr.io, dr.o, dr.oe, dr.i, dr.clk)


def _little64_sd_output_enable_bus(oe, width: int):
    if len(oe) == width:
        return oe
    if len(oe) == 1:
        return Replicate(oe, width)
    raise ValueError(f'Unsupported SD output-enable width: {len(oe)} for {width} lanes')


class _Little64ForcedCMDWaveTristateImpl(Module):
    def __init__(self, io, i, clk):
        pad_in = Signal()
        counter = Signal(18)
        wave = Signal()

        self.sync += counter.eq(counter + 1)
        self.comb += wave.eq(counter[-1])
        self.specials += SDRInput(pad_in, i, clk)
        self.specials += Instance(
            'IOBUF',
            io_IO=io,
            o_O=pad_in,
            i_I=wave,
            i_T=0,
        )


class _Little64NativeSDDebug(LiteXModule):
    def __init__(self, sdpads):
        self.signals = CSRStatus(fields=[
            CSRField('cmd_i', size=1, offset=0),
            CSRField('cmd_o', size=1, offset=1),
            CSRField('cmd_oe', size=1, offset=2),
            CSRField('data0_i', size=1, offset=3),
            CSRField('data1_i', size=1, offset=4),
            CSRField('data2_i', size=1, offset=5),
            CSRField('data3_i', size=1, offset=6),
            CSRField('data0_o', size=1, offset=7),
            CSRField('data_oe', size=1, offset=8),
            CSRField('clk', size=1, offset=9),
        ])
        self.cmd_i_transitions = CSRStatus(32)
        self.cmd_o_transitions = CSRStatus(32)
        self.cmd_oe_transitions = CSRStatus(32)
        self.data0_i_transitions = CSRStatus(32)
        self.data1_i_transitions = CSRStatus(32)
        self.data2_i_transitions = CSRStatus(32)
        self.data3_i_transitions = CSRStatus(32)
        self.clk_transitions = CSRStatus(32)
        self.cmd_i_released_transitions = CSRStatus(32)

        cmd_i_prev = Signal()
        cmd_o_prev = Signal()
        cmd_oe_prev = Signal()
        data0_i_prev = Signal()
        data1_i_prev = Signal()
        data2_i_prev = Signal()
        data3_i_prev = Signal()
        clk_prev = Signal()
        cmd_i_count = Signal(32)
        cmd_o_count = Signal(32)
        cmd_oe_count = Signal(32)
        data0_i_count = Signal(32)
        data1_i_count = Signal(32)
        data2_i_count = Signal(32)
        data3_i_count = Signal(32)
        clk_count = Signal(32)
        cmd_i_released_count = Signal(32)

        self.comb += [
            self.signals.fields.cmd_i.eq(sdpads.cmd.i),
            self.signals.fields.cmd_o.eq(sdpads.cmd.o),
            self.signals.fields.cmd_oe.eq(sdpads.cmd.oe),
            self.signals.fields.data0_i.eq(sdpads.data.i[0]),
            self.signals.fields.data1_i.eq(sdpads.data.i[1]),
            self.signals.fields.data2_i.eq(sdpads.data.i[2]),
            self.signals.fields.data3_i.eq(sdpads.data.i[3]),
            self.signals.fields.data0_o.eq(sdpads.data.o[0]),
            self.signals.fields.data_oe.eq(sdpads.data.oe),
            self.signals.fields.clk.eq(sdpads.clk),
            self.cmd_i_transitions.status.eq(cmd_i_count),
            self.cmd_o_transitions.status.eq(cmd_o_count),
            self.cmd_oe_transitions.status.eq(cmd_oe_count),
            self.data0_i_transitions.status.eq(data0_i_count),
            self.data1_i_transitions.status.eq(data1_i_count),
            self.data2_i_transitions.status.eq(data2_i_count),
            self.data3_i_transitions.status.eq(data3_i_count),
            self.clk_transitions.status.eq(clk_count),
            self.cmd_i_released_transitions.status.eq(cmd_i_released_count),
        ]

        self.sync += [
            If(cmd_i_prev != sdpads.cmd.i,
                cmd_i_count.eq(cmd_i_count + 1),
            ),
            If(cmd_o_prev != sdpads.cmd.o,
                cmd_o_count.eq(cmd_o_count + 1),
            ),
            If(cmd_oe_prev != sdpads.cmd.oe,
                cmd_oe_count.eq(cmd_oe_count + 1),
            ),
            If(data0_i_prev != sdpads.data.i[0],
                data0_i_count.eq(data0_i_count + 1),
            ),
            If(data1_i_prev != sdpads.data.i[1],
                data1_i_count.eq(data1_i_count + 1),
            ),
            If(data2_i_prev != sdpads.data.i[2],
                data2_i_count.eq(data2_i_count + 1),
            ),
            If(data3_i_prev != sdpads.data.i[3],
                data3_i_count.eq(data3_i_count + 1),
            ),
            If(clk_prev != sdpads.clk,
                clk_count.eq(clk_count + 1),
            ),
            If((cmd_i_prev != sdpads.cmd.i) & ~sdpads.cmd.oe,
                cmd_i_released_count.eq(cmd_i_released_count + 1),
            ),
            cmd_i_prev.eq(sdpads.cmd.i),
            cmd_o_prev.eq(sdpads.cmd.o),
            cmd_oe_prev.eq(sdpads.cmd.oe),
            data0_i_prev.eq(sdpads.data.i[0]),
            data1_i_prev.eq(sdpads.data.i[1]),
            data2_i_prev.eq(sdpads.data.i[2]),
            data3_i_prev.eq(sdpads.data.i[3]),
            clk_prev.eq(sdpads.clk),
        ]


def _little64_arty_platform_class(base_platform):
    class Little64ArtyPlatform(base_platform):
        def get_verilog(self, *args, special_overrides=dict(), **kwargs):
            so = {SDRTristate: _Little64XilinxSDRTristate}
            so.update(special_overrides)
            return super().get_verilog(*args, special_overrides=so, **kwargs)

    return Little64ArtyPlatform


def create_arty_platform(*, variant: str = 'a7-35', toolchain: str = 'vivado'):
    digilent_arty = _import_digilent_arty_platform()
    platform_cls = _little64_arty_platform_class(digilent_arty.Platform)
    return platform_cls(variant=variant, toolchain=toolchain)


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
        sdcard_mode: ArtySDCardMode = ARTY_SDCARD_MODE_NATIVE,
        sdcard_mapping: Little64ArtySDCardMapping | None = None,
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
            if sdcard_mapping is None:
                raise ValueError('An SD card mapping is required when the Arty hardware SoC enables SD card support')
            if sdcard_mode == ARTY_SDCARD_MODE_SPI:
                if not isinstance(sdcard_mapping, Little64ArtySPISDCardMapping):
                    raise ValueError('SPI Arty SD mode requires an SPI SD card mapping')
                platform.add_extension(arty_spi_sdcard_extension(sdcard_mapping))
            elif sdcard_mode == ARTY_SDCARD_MODE_NATIVE:
                if not isinstance(sdcard_mapping, Little64ArtyNativeSDCardMapping):
                    raise ValueError('Native Arty SD mode requires a native SD card mapping')
                platform.add_extension(arty_native_sdcard_extension(sdcard_mapping))
            else:
                raise ValueError(f'Unsupported Arty SD card mode: {sdcard_mode}')

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
            sdcard_mode=sdcard_mode,
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
        self._configure_debug_leds()

    def _configure_sdcard(self, *, mode: str, sdcard_image_path: str | Path | None) -> None:
        if mode == ARTY_SDCARD_MODE_NATIVE:
            if sdcard_image_path is not None:
                raise ValueError('sdcard_image_path is only supported for simulation-backed native LiteSDCard mode')
            self.add_sdcard('sdcard', use_emulator=False)
            if hasattr(self, 'sdcard_phy') and hasattr(self.sdcard_phy, 'sdpads'):
                self.add_module(name='sdcard_debug', module=_Little64NativeSDDebug(self.sdcard_phy.sdpads))
            return
        super()._configure_sdcard(mode=mode, sdcard_image_path=sdcard_image_path)

    def _configure_debug_leds(self) -> None:
        pulse_cycles = max(1, int(self.sys_clk_freq // 8))
        pulse_counter_max = pulse_cycles + 1
        heartbeat_half_period = max(1, int(self.sys_clk_freq // 2))

        self.arty_user_led_pads = [
            self.platform.request('user_led', index)
            for index in range(ARTY_USER_LED_COUNT)
        ]
        self.arty_rgb_led_pads = [
            self.platform.request('rgb_led', index)
            for index in range(ARTY_RGB_LED_COUNT)
        ]

        self.arty_led_halted = Signal(name='arty_led_halted')
        self.arty_led_locked_up = Signal(name='arty_led_locked_up')
        self.arty_led_i_bus_activity = Signal(name='arty_led_i_bus_activity')
        self.arty_led_d_bus_activity = Signal(name='arty_led_d_bus_activity')
        self.arty_led_store_activity = Signal(name='arty_led_store_activity')
        self.arty_led_running_heartbeat = Signal(name='arty_led_running_heartbeat')
        self.arty_led_irq_pending = Signal(name='arty_led_irq_pending')
        self.arty_led_sd_cmd_output_activity = Signal(name='arty_led_sd_cmd_output_activity')
        self.arty_led_sd_cmd_output_enable_activity = Signal(name='arty_led_sd_cmd_output_enable_activity')
        self.arty_led_sd_cmd_released_input_activity = Signal(name='arty_led_sd_cmd_released_input_activity')

        def _make_stretched_level(source: Signal, *, name: str) -> Signal:
            counter = Signal(max=pulse_counter_max, name=f'{name}_stretch_counter')
            level = Signal(name=f'{name}_stretch_level')
            self.sync += If(source,
                counter.eq(pulse_cycles),
            ).Elif(counter != 0,
                counter.eq(counter - 1),
            )
            self.comb += level.eq(source | (counter != 0))
            return level

        def _make_stretched_transition(source: Signal, *, name: str, gate: Signal | None = None) -> Signal:
            counter = Signal(max=pulse_counter_max, name=f'{name}_transition_counter')
            previous = Signal(name=f'{name}_previous')
            pulse = Signal(name=f'{name}_transition_level')
            gate_enabled = Signal(name=f'{name}_gate_enabled')

            if gate is None:
                self.comb += gate_enabled.eq(1)
            else:
                self.comb += gate_enabled.eq(gate)

            self.sync += [
                If((previous != source) & gate_enabled,
                    counter.eq(pulse_cycles),
                ).Elif(counter != 0,
                    counter.eq(counter - 1),
                ),
                previous.eq(source),
            ]
            self.comb += pulse.eq(counter != 0)
            return pulse

        i_bus_request = Signal(name='arty_i_bus_request')
        d_bus_request = Signal(name='arty_d_bus_request')
        store_request = Signal(name='arty_store_request')
        irq_pending = Signal(name='arty_irq_pending')
        sd_cmd_i = Signal(name='arty_sd_cmd_i')
        sd_cmd_o = Signal(name='arty_sd_cmd_o')
        sd_cmd_oe = Signal(name='arty_sd_cmd_oe')
        heartbeat_counter = Signal(max=max(2, heartbeat_half_period), name='arty_heartbeat_counter')
        heartbeat_toggle = Signal(name='arty_heartbeat_toggle')

        if hasattr(self, 'sdcard_phy') and hasattr(self.sdcard_phy, 'sdpads'):
            self.comb += [
                sd_cmd_i.eq(self.sdcard_phy.sdpads.cmd.i),
                sd_cmd_o.eq(self.sdcard_phy.sdpads.cmd.o),
                sd_cmd_oe.eq(self.sdcard_phy.sdpads.cmd.oe),
            ]
        else:
            self.comb += [
                sd_cmd_i.eq(0),
                sd_cmd_o.eq(0),
                sd_cmd_oe.eq(0),
            ]

        self.comb += [
            i_bus_request.eq(self.cpu.ibus.cyc & self.cpu.ibus.stb),
            d_bus_request.eq(self.cpu.dbus.cyc & self.cpu.dbus.stb),
            store_request.eq(self.cpu.dbus.cyc & self.cpu.dbus.stb & self.cpu.dbus.we),
            irq_pending.eq(self.cpu.interrupt != 0),
            self.arty_led_halted.eq(self.cpu.halted),
            self.arty_led_locked_up.eq(self.cpu.locked_up),
            self.arty_led_i_bus_activity.eq(_make_stretched_level(i_bus_request, name='arty_i_bus_activity')),
            self.arty_led_d_bus_activity.eq(_make_stretched_level(d_bus_request, name='arty_d_bus_activity')),
            self.arty_led_store_activity.eq(_make_stretched_level(store_request, name='arty_store_activity')),
            self.arty_led_irq_pending.eq(_make_stretched_level(irq_pending, name='arty_irq_pending')),
            self.arty_led_running_heartbeat.eq(heartbeat_toggle & ~self.cpu.halted & ~self.cpu.locked_up),
            self.arty_led_sd_cmd_output_activity.eq(_make_stretched_transition(sd_cmd_o, name='arty_sd_cmd_output')),
            self.arty_led_sd_cmd_output_enable_activity.eq(_make_stretched_transition(sd_cmd_oe, name='arty_sd_cmd_output_enable')),
            self.arty_led_sd_cmd_released_input_activity.eq(_make_stretched_transition(sd_cmd_i, name='arty_sd_cmd_released_input', gate=~sd_cmd_oe)),
        ]

        self.sync += If(heartbeat_counter == (heartbeat_half_period - 1),
            heartbeat_counter.eq(0),
            heartbeat_toggle.eq(~heartbeat_toggle),
        ).Else(
            heartbeat_counter.eq(heartbeat_counter + 1),
        )

        self.comb += [
            self.arty_user_led_pads[0].eq(self.arty_led_halted),
            self.arty_user_led_pads[1].eq(self.arty_led_locked_up),
            self.arty_user_led_pads[2].eq(self.arty_led_i_bus_activity),
            self.arty_user_led_pads[3].eq(self.arty_led_d_bus_activity),
        ]

        rgb_led0 = self.arty_rgb_led_pads[0]
        self.comb += [
            rgb_led0.r.eq(~self.arty_led_store_activity if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_store_activity),
            rgb_led0.g.eq(~self.arty_led_running_heartbeat if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_running_heartbeat),
            rgb_led0.b.eq(~self.arty_led_irq_pending if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_irq_pending),
        ]

        rgb_led1 = self.arty_rgb_led_pads[1]
        self.comb += [
            rgb_led1.r.eq(~self.arty_led_sd_cmd_output_activity if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_sd_cmd_output_activity),
            rgb_led1.g.eq(~self.arty_led_sd_cmd_output_enable_activity if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_sd_cmd_output_enable_activity),
            rgb_led1.b.eq(~self.arty_led_sd_cmd_released_input_activity if ARTY_RGB_LED_ACTIVE_LOW else self.arty_led_sd_cmd_released_input_activity),
        ]

        for rgb_led in self.arty_rgb_led_pads[2:]:
            self.comb += [
                rgb_led.r.eq(1 if ARTY_RGB_LED_ACTIVE_LOW else 0),
                rgb_led.g.eq(1 if ARTY_RGB_LED_ACTIVE_LOW else 0),
                rgb_led.b.eq(1 if ARTY_RGB_LED_ACTIVE_LOW else 0),
            ]

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