from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from migen import Case, Cat, ClockSignal, Constant, If, Instance, Module, ResetSignal, Signal

from litex.soc.cores.cpu import CPU, CPUS
from litex.soc.interconnect import wishbone

from .config import Little64CoreConfig
from .litex import Little64LiteXProfile, emit_litex_cpu_verilog
from .variants import config_for_litex_variant


_LITEX_LLVM_WRAPPER_TARGETS = {
    'gcc': ('clang', '--target=little64-unknown-elf', '-integrated-as'),
    'g++': ('clang++', '--target=little64-unknown-elf', '-integrated-as'),
    'ar': ('llvm-ar',),
    'as': ('clang', '--target=little64-unknown-elf', '-integrated-as'),
    'gcc-ar': ('llvm-ar',),
    'gcc-nm': ('llvm-nm',),
    'ld': ('ld.lld',),
    'nm': ('llvm-nm',),
    'objcopy': ('llvm-objcopy',),
    'ranlib': ('llvm-ranlib',),
    'readelf': ('llvm-readelf',),
    'strip': ('llvm-strip',),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_executable_wrapper(wrapper_path: Path, tool_path: Path, tool_args: tuple[str, ...]) -> None:
    wrapper_path.write_text(
        '#!/bin/sh\n'
        'set -e\n'
        f'exec "{tool_path}"' + ''.join(f' "{arg}"' for arg in tool_args) + ' "$@"\n',
        encoding='utf-8',
    )
    wrapper_path.chmod(0o755)


def ensure_litex_llvm_toolchain_wrappers(output_dir: str | Path | None = None) -> Path:
    repo_root = _repo_root()
    compilers_bin = repo_root / 'compilers' / 'bin'
    wrapper_root = Path(output_dir) if output_dir is not None else repo_root / 'builddir' / 'litex-toolchain'
    wrapper_bin = wrapper_root / 'bin'
    wrapper_bin.mkdir(parents=True, exist_ok=True)

    triple = Little64LiteXProfile().gcc_triple
    for suffix, command in _LITEX_LLVM_WRAPPER_TARGETS.items():
        tool_path = compilers_bin / command[0]
        if not tool_path.exists():
            raise FileNotFoundError(f'Missing LLVM tool for LiteX wrapper generation: {tool_path}')
        _write_executable_wrapper(wrapper_bin / f'{triple}-{suffix}', tool_path, command[1:])

    path_entries = os.environ.get('PATH', '').split(os.pathsep) if os.environ.get('PATH') else []
    wrapper_bin_str = str(wrapper_bin)
    if wrapper_bin_str not in path_entries:
        os.environ['PATH'] = wrapper_bin_str if not path_entries else wrapper_bin_str + os.pathsep + os.environ['PATH']
    return wrapper_bin


def _litex_software_sysroot_flags() -> str:
    sysroot = _repo_root() / 'target' / 'sysroot'
    include_dir = sysroot / 'usr' / 'include'
    lib_dir = sysroot / 'usr' / 'lib'
    return f'--sysroot={sysroot} -I{include_dir} -L{lib_dir}'


class Little64WishboneDataBridge(Module):
    def __init__(self) -> None:
        self.bus = wishbone.Interface(data_width=64, address_width=64, addressing='word')

        self.cpu_adr = Signal(64)
        self.cpu_dat_w = Signal(64)
        self.cpu_dat_r = Signal(64)
        self.cpu_sel = Signal(8)
        self.cpu_cyc = Signal()
        self.cpu_stb = Signal()
        self.cpu_we = Signal()
        self.cpu_ack = Signal()
        self.cpu_err = Signal()
        self.cpu_cti = Signal(3)
        self.cpu_bte = Signal(2)

        state_idle = 0
        state_beat0 = 1
        state_beat1 = 2

        state = Signal(2, reset=state_idle)
        latched_adr = Signal(64)
        latched_dat_w = Signal(64)
        latched_sel = Signal(8)
        latched_we = Signal()
        first_read_data = Signal(64)
        response_valid = Signal()
        response_error = Signal()
        response_data = Signal(64)

        shifted_sel = Signal(16)
        shifted_dat_w = Signal(128)
        split_access = Signal()
        first_bus_adr = Signal(64)
        second_bus_adr = Signal(64)
        first_bus_sel = Signal(8)
        second_bus_sel = Signal(8)
        first_bus_dat_w = Signal(64)
        second_bus_dat_w = Signal(64)
        single_read_data = Signal(64)
        combined_read_data = Signal(64)

        self.comb += [
            first_bus_adr.eq(latched_adr[3:]),
            second_bus_adr.eq(latched_adr[3:] + 1),
            split_access.eq(shifted_sel[8:] != 0),
            first_bus_sel.eq(shifted_sel[:8]),
            second_bus_sel.eq(shifted_sel[8:16]),
            first_bus_dat_w.eq(shifted_dat_w[:64]),
            second_bus_dat_w.eq(shifted_dat_w[64:128]),
        ]

        self.comb += Case(latched_adr[:3], {
            0: [shifted_sel.eq(latched_sel), shifted_dat_w.eq(latched_dat_w)],
            1: [shifted_sel.eq(latched_sel << 1), shifted_dat_w.eq(latched_dat_w << 8)],
            2: [shifted_sel.eq(latched_sel << 2), shifted_dat_w.eq(latched_dat_w << 16)],
            3: [shifted_sel.eq(latched_sel << 3), shifted_dat_w.eq(latched_dat_w << 24)],
            4: [shifted_sel.eq(latched_sel << 4), shifted_dat_w.eq(latched_dat_w << 32)],
            5: [shifted_sel.eq(latched_sel << 5), shifted_dat_w.eq(latched_dat_w << 40)],
            6: [shifted_sel.eq(latched_sel << 6), shifted_dat_w.eq(latched_dat_w << 48)],
            'default': [shifted_sel.eq(latched_sel << 7), shifted_dat_w.eq(latched_dat_w << 56)],
        })

        self.comb += Case(latched_adr[:3], {
            0: single_read_data.eq(self.bus.dat_r),
            1: single_read_data.eq(Cat(self.bus.dat_r[8:64], Constant(0, 8))),
            2: single_read_data.eq(Cat(self.bus.dat_r[16:64], Constant(0, 16))),
            3: single_read_data.eq(Cat(self.bus.dat_r[24:64], Constant(0, 24))),
            4: single_read_data.eq(Cat(self.bus.dat_r[32:64], Constant(0, 32))),
            5: single_read_data.eq(Cat(self.bus.dat_r[40:64], Constant(0, 40))),
            6: single_read_data.eq(Cat(self.bus.dat_r[48:64], Constant(0, 48))),
            'default': single_read_data.eq(Cat(self.bus.dat_r[56:64], Constant(0, 56))),
        })

        self.comb += Case(latched_adr[:3], {
            0: combined_read_data.eq(first_read_data),
            1: combined_read_data.eq(Cat(first_read_data[8:64], self.bus.dat_r[:8])),
            2: combined_read_data.eq(Cat(first_read_data[16:64], self.bus.dat_r[:16])),
            3: combined_read_data.eq(Cat(first_read_data[24:64], self.bus.dat_r[:24])),
            4: combined_read_data.eq(Cat(first_read_data[32:64], self.bus.dat_r[:32])),
            5: combined_read_data.eq(Cat(first_read_data[40:64], self.bus.dat_r[:40])),
            6: combined_read_data.eq(Cat(first_read_data[48:64], self.bus.dat_r[:48])),
            'default': combined_read_data.eq(Cat(first_read_data[56:64], self.bus.dat_r[:56])),
        })

        self.comb += [
            self.bus.adr.eq(0),
            self.bus.dat_w.eq(0),
            self.bus.sel.eq(0),
            self.bus.cyc.eq(0),
            self.bus.stb.eq(0),
            self.bus.we.eq(0),
            self.bus.cti.eq(0),
            self.bus.bte.eq(0),
            self.cpu_dat_r.eq(response_data),
            self.cpu_ack.eq(response_valid & ~response_error),
            self.cpu_err.eq(response_valid & response_error),
        ]

        self.comb += If(state == state_beat0,
            self.bus.adr.eq(first_bus_adr),
            self.bus.dat_w.eq(first_bus_dat_w),
            self.bus.sel.eq(first_bus_sel),
            self.bus.cyc.eq(1),
            self.bus.stb.eq(1),
            self.bus.we.eq(latched_we),
        ).Elif(state == state_beat1,
            self.bus.adr.eq(second_bus_adr),
            self.bus.dat_w.eq(second_bus_dat_w),
            self.bus.sel.eq(second_bus_sel),
            self.bus.cyc.eq(1),
            self.bus.stb.eq(1),
            self.bus.we.eq(latched_we),
        )

        self.sync += If(response_valid,
            response_valid.eq(0),
        ).Elif(state == state_idle,
            If(self.cpu_cyc & self.cpu_stb,
                latched_adr.eq(self.cpu_adr),
                latched_dat_w.eq(self.cpu_dat_w),
                latched_sel.eq(self.cpu_sel),
                latched_we.eq(self.cpu_we),
                state.eq(state_beat0),
            ),
        ).Elif(state == state_beat0,
            If(self.bus.err,
                response_valid.eq(1),
                response_error.eq(1),
                response_data.eq(0),
                state.eq(state_idle),
            ).Elif(self.bus.ack,
                If(split_access,
                    first_read_data.eq(self.bus.dat_r),
                    state.eq(state_beat1),
                ).Else(
                    response_valid.eq(1),
                    response_error.eq(0),
                    response_data.eq(single_read_data),
                    state.eq(state_idle),
                ),
            ),
        ).Elif(state == state_beat1,
            If(self.bus.err,
                response_valid.eq(1),
                response_error.eq(1),
                response_data.eq(0),
                state.eq(state_idle),
            ).Elif(self.bus.ack,
                response_valid.eq(1),
                response_error.eq(0),
                response_data.eq(combined_read_data),
                state.eq(state_idle),
            ),
        )


class Little64(CPU):
    profile = Little64LiteXProfile()

    category = profile.category
    family = profile.family
    name = profile.name
    human_name = profile.human_name
    variants = profile.variants
    data_width = profile.data_width
    endianness = profile.endianness
    linker_output_format = profile.linker_output_format
    nop = profile.nop
    io_regions = profile.io_regions
    mem_map = profile.mem_map
    first_irq_vector = profile.first_irq_vector
    use_rom = True

    @property
    def gcc_flags(self) -> str:
        return _litex_software_sysroot_flags()

    @property
    def gcc_triple(self) -> str:
        ensure_litex_llvm_toolchain_wrappers(getattr(self.platform, 'output_dir', None))
        return self.profile.gcc_triple

    @property
    def clang_flags(self) -> str:
        return _litex_software_sysroot_flags()

    @property
    def clang_triple(self) -> str:
        ensure_litex_llvm_toolchain_wrappers(getattr(self.platform, 'output_dir', None))
        return self.profile.clang_triple

    def __init__(self, platform, variant: str = 'standard'):
        if variant not in self.variants:
            raise ValueError(f'Unsupported Little64 LiteX CPU variant: {variant}')

        self.platform = platform
        self.variant = variant
        platform_mem_map = getattr(platform, 'little64_mem_map', None)
        self.mem_map = dict(platform_mem_map) if platform_mem_map is not None else dict(self.profile.mem_map)
        self.profile = Little64LiteXProfile(mem_map=dict(self.mem_map))
        self.reset = Signal()
        self.interrupt = Signal(self.profile.irq_count)
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)
        self.halted = Signal()
        self.locked_up = Signal()
        self.debug_cpu_ie = Signal()
        self.debug_irq_pending_latched = Signal()
        self.debug_irq_pending_masked = Signal()
        self.debug_trap_cause = Signal(8)
        self.debug_lockup_reason = Signal(8)

        self.ibus = wishbone.Interface(data_width=64, address_width=64, addressing='byte')
        self.dbus_bridge = Little64WishboneDataBridge()
        self.submodules.dbus_bridge = self.dbus_bridge
        self.dbus = self.dbus_bridge.bus
        self.periph_buses = [self.ibus, self.dbus]
        self.memory_buses = []

        self.core_config = config_for_litex_variant(
            variant,
            reset_vector=self.profile.reset_address,
        )

        self.cpu_params = dict(
            i_clk=ClockSignal('sys'),
            i_rst=ResetSignal('sys') | self.reset,
            i_boot_r1=self.boot_r1,
            i_boot_r13=self.boot_r13,
            i_i_bus_ack=self.ibus.ack,
            i_i_bus_err=self.ibus.err,
            i_i_bus_dat_r=self.ibus.dat_r,
            i_d_bus_ack=self.dbus_bridge.cpu_ack,
            i_d_bus_err=self.dbus_bridge.cpu_err,
            i_d_bus_dat_r=self.dbus_bridge.cpu_dat_r,
            i_irq_lines=self.interrupt,
            o_i_bus_adr=self.ibus.adr,
            o_i_bus_dat_w=self.ibus.dat_w,
            o_i_bus_sel=self.ibus.sel,
            o_i_bus_cyc=self.ibus.cyc,
            o_i_bus_stb=self.ibus.stb,
            o_i_bus_we=self.ibus.we,
            o_i_bus_cti=self.ibus.cti,
            o_i_bus_bte=self.ibus.bte,
            o_d_bus_adr=self.dbus_bridge.cpu_adr,
            o_d_bus_dat_w=self.dbus_bridge.cpu_dat_w,
            o_d_bus_sel=self.dbus_bridge.cpu_sel,
            o_d_bus_cyc=self.dbus_bridge.cpu_cyc,
            o_d_bus_stb=self.dbus_bridge.cpu_stb,
            o_d_bus_we=self.dbus_bridge.cpu_we,
            o_d_bus_cti=self.dbus_bridge.cpu_cti,
            o_d_bus_bte=self.dbus_bridge.cpu_bte,
            o_halted=self.halted,
            o_locked_up=self.locked_up,
            o_debug_cpu_ie=self.debug_cpu_ie,
            o_debug_irq_pending_latched=self.debug_irq_pending_latched,
            o_debug_irq_pending_masked=self.debug_irq_pending_masked,
            o_debug_trap_cause=self.debug_trap_cause,
            o_debug_lockup_reason=self.debug_lockup_reason,
        )

    def set_reset_address(self, reset_address: int) -> None:
        self.reset_address = reset_address
        self.core_config = replace(self.core_config, reset_vector=reset_address)

    def do_finalize(self) -> None:
        assert hasattr(self, 'reset_address')
        output_dir = Path(getattr(self.platform, 'output_dir', 'build')) / 'gateware'
        output_dir.mkdir(parents=True, exist_ok=True)
        verilog_path = emit_litex_cpu_verilog(
            output_dir / 'little64_litex_cpu_top.v',
            config=self.core_config,
            module_name='little64_litex_cpu_top',
        )
        self.platform.add_source(str(verilog_path))
        self.specials += Instance('little64_litex_cpu_top', **self.cpu_params)


def register_little64_with_litex(*, force: bool = False) -> type[Little64]:
    existing = CPUS.get(Little64.name)
    if existing is not None and existing is not Little64 and not force:
        raise RuntimeError('LiteX CPU registry already contains a different little64 CPU class')
    CPUS[Little64.name] = Little64
    return Little64