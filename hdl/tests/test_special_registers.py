from __future__ import annotations

import pytest

from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.isa import CPU_CONTROL_WRITABLE_MASK, SpecialRegister


pytestmark = pytest.mark.core_capabilities('special-register-file')


def _make_config(shared_core_variant: str, **overrides) -> Little64CoreConfig:
    return Little64CoreConfig(core_variant=shared_core_variant, **overrides)


def test_optional_platform_register_reads_zero_when_disabled(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant, optional_platform_registers=False))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.read_selector, SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        assert ctx.get(dut.read_data) == 0

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        ctx.set(dut.write_data, 0x1234)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        assert ctx.get(dut.read_data) == 0

    sim.add_testbench(process)
    sim.run()


def test_optional_platform_registers_store_when_enabled(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant, optional_platform_registers=True))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.BOOT_SOURCE_PAGE_SIZE)
        ctx.set(dut.write_data, 0x2000)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, SpecialRegister.BOOT_SOURCE_PAGE_SIZE)
        assert ctx.get(dut.read_data) == 0x2000

    sim.add_testbench(process)
    sim.run()


def test_user_mode_cannot_access_supervisor_bank(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant))
    sim = Simulator(dut)

    async def process(ctx):
        ctx.set(dut.user_mode, 1)
        ctx.set(dut.read_selector, SpecialRegister.CPU_CONTROL)
        assert ctx.get(dut.read_access_fault) == 1

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        assert ctx.get(dut.write_access_fault) == 1

    sim.add_testbench(process)
    sim.run()


def test_reserved_supervisor_selector_reads_zero_and_ignores_writes(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.read_selector, 1)
        assert ctx.get(dut.read_data) == 0

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, 1)
        ctx.set(dut.write_data, 0xDEAD_BEEF)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, 1)
        assert ctx.get(dut.read_data) == 0

    sim.add_testbench(process)
    sim.run()


def test_user_mode_cannot_access_unassigned_user_bank_selector(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant))
    sim = Simulator(dut)

    async def process(ctx):
        ctx.set(dut.user_mode, 1)
        ctx.set(dut.read_selector, 0x8001)
        assert ctx.get(dut.read_access_fault) == 1

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, 0x8001)
        assert ctx.get(dut.write_access_fault) == 1

    sim.add_testbench(process)
    sim.run()


def test_cpu_control_masks_reserved_bits(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.CPU_CONTROL)
        ctx.set(dut.write_data, 0xFFFF_FFFF_FFFF_FFFF)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, SpecialRegister.CPU_CONTROL)
        assert ctx.get(dut.read_data) == CPU_CONTROL_WRITABLE_MASK

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.INTERRUPT_CPU_CONTROL)
        ctx.set(dut.write_data, 0xFFFF_FFFF_FFFF_FFFF)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, SpecialRegister.INTERRUPT_CPU_CONTROL)
        assert ctx.get(dut.read_data) == CPU_CONTROL_WRITABLE_MASK

    sim.add_testbench(process)
    sim.run()


def test_page_table_root_is_ignored_when_mmu_disabled(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant, enable_mmu=False))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        ctx.set(dut.write_data, 0x1234_5678_9ABC_DEF0)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.read_selector, SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        assert ctx.get(dut.read_data) == 0

    sim.add_testbench(process)
    sim.run()


def test_core_trap_write_updates_isolated_trap_bank(shared_core_variant: str, shared_special_register_file_factory) -> None:
    dut = shared_special_register_file_factory(_make_config(shared_core_variant))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.TRAP_CAUSE)
        ctx.set(dut.write_data, 0x11)
        await ctx.tick()

        ctx.set(dut.write_stb, 1)
        ctx.set(dut.write_selector, SpecialRegister.TRAP_CAUSE)
        ctx.set(dut.write_data, 0x22)
        ctx.set(dut.core_trap_write, 1)
        ctx.set(dut.core_trap_cause_data, 0xAA)
        ctx.set(dut.core_trap_fault_addr_data, 0xBB)
        ctx.set(dut.core_trap_access_data, 0xCC)
        ctx.set(dut.core_trap_pc_data, 0xDD)
        ctx.set(dut.core_trap_aux_data, 0xEE)
        await ctx.tick()

        ctx.set(dut.write_stb, 0)
        ctx.set(dut.core_trap_write, 0)

        ctx.set(dut.read_selector, SpecialRegister.TRAP_CAUSE)
        assert ctx.get(dut.read_data) == 0xAA

        ctx.set(dut.read_selector, SpecialRegister.TRAP_FAULT_ADDR)
        assert ctx.get(dut.read_data) == 0xBB

        ctx.set(dut.read_selector, SpecialRegister.TRAP_ACCESS)
        assert ctx.get(dut.read_data) == 0xCC

        ctx.set(dut.read_selector, SpecialRegister.TRAP_PC)
        assert ctx.get(dut.read_data) == 0xDD

        ctx.set(dut.read_selector, SpecialRegister.TRAP_AUX)
        assert ctx.get(dut.read_data) == 0xEE

    sim.add_testbench(process)
    sim.run()
