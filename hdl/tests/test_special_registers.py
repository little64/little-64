from __future__ import annotations

from amaranth.sim import Settle, Simulator

from little64.config import Little64CoreConfig
from little64.isa import CPU_CONTROL_WRITABLE_MASK, SpecialRegister
from little64.special_registers import Little64SpecialRegisterFile


def test_optional_platform_register_reads_zero_when_disabled() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig(optional_platform_registers=False))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.read_selector.eq(SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        yield Settle()
        assert (yield dut.read_data) == 0

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        yield dut.write_data.eq(0x1234)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(SpecialRegister.BOOT_INFO_FRAME_PHYSICAL)
        yield Settle()
        assert (yield dut.read_data) == 0

    sim.add_sync_process(process)
    sim.run()


def test_optional_platform_registers_store_when_enabled() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig(optional_platform_registers=True))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.BOOT_SOURCE_PAGE_SIZE)
        yield dut.write_data.eq(0x2000)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(SpecialRegister.BOOT_SOURCE_PAGE_SIZE)
        yield Settle()
        assert (yield dut.read_data) == 0x2000

    sim.add_sync_process(process)
    sim.run()


def test_user_mode_cannot_access_supervisor_bank() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig())
    sim = Simulator(dut)

    def process():
        yield dut.user_mode.eq(1)
        yield dut.read_selector.eq(SpecialRegister.CPU_CONTROL)
        yield Settle()
        assert (yield dut.read_access_fault) == 1

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        yield Settle()
        assert (yield dut.write_access_fault) == 1

    sim.add_process(process)
    sim.run()


def test_reserved_supervisor_selector_reads_zero_and_ignores_writes() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig())
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.read_selector.eq(1)
        yield Settle()
        assert (yield dut.read_data) == 0

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(1)
        yield dut.write_data.eq(0xDEAD_BEEF)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(1)
        yield Settle()
        assert (yield dut.read_data) == 0

    sim.add_sync_process(process)
    sim.run()


def test_user_mode_cannot_access_unassigned_user_bank_selector() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig())
    sim = Simulator(dut)

    def process():
        yield dut.user_mode.eq(1)
        yield dut.read_selector.eq(0x8001)
        yield Settle()
        assert (yield dut.read_access_fault) == 1

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(0x8001)
        yield Settle()
        assert (yield dut.write_access_fault) == 1

    sim.add_process(process)
    sim.run()


def test_cpu_control_masks_reserved_bits() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig())
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.CPU_CONTROL)
        yield dut.write_data.eq(0xFFFF_FFFF_FFFF_FFFF)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(SpecialRegister.CPU_CONTROL)
        yield Settle()
        assert (yield dut.read_data) == CPU_CONTROL_WRITABLE_MASK

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.INTERRUPT_CPU_CONTROL)
        yield dut.write_data.eq(0xFFFF_FFFF_FFFF_FFFF)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(SpecialRegister.INTERRUPT_CPU_CONTROL)
        yield Settle()
        assert (yield dut.read_data) == CPU_CONTROL_WRITABLE_MASK

    sim.add_sync_process(process)
    sim.run()


def test_page_table_root_is_ignored_when_mmu_disabled() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig(enable_mmu=False))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        yield dut.write_data.eq(0x1234_5678_9ABC_DEF0)
        yield

        yield dut.write_stb.eq(0)
        yield dut.read_selector.eq(SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL)
        yield Settle()
        assert (yield dut.read_data) == 0

    sim.add_sync_process(process)
    sim.run()


def test_core_trap_write_updates_isolated_trap_bank() -> None:
    dut = Little64SpecialRegisterFile(Little64CoreConfig())
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.TRAP_CAUSE)
        yield dut.write_data.eq(0x11)
        yield

        yield dut.write_stb.eq(1)
        yield dut.write_selector.eq(SpecialRegister.TRAP_CAUSE)
        yield dut.write_data.eq(0x22)
        yield dut.core_trap_write.eq(1)
        yield dut.core_trap_cause_data.eq(0xAA)
        yield dut.core_trap_fault_addr_data.eq(0xBB)
        yield dut.core_trap_access_data.eq(0xCC)
        yield dut.core_trap_pc_data.eq(0xDD)
        yield dut.core_trap_aux_data.eq(0xEE)
        yield

        yield dut.write_stb.eq(0)
        yield dut.core_trap_write.eq(0)

        yield dut.read_selector.eq(SpecialRegister.TRAP_CAUSE)
        yield Settle()
        assert (yield dut.read_data) == 0xAA

        yield dut.read_selector.eq(SpecialRegister.TRAP_FAULT_ADDR)
        yield Settle()
        assert (yield dut.read_data) == 0xBB

        yield dut.read_selector.eq(SpecialRegister.TRAP_ACCESS)
        yield Settle()
        assert (yield dut.read_data) == 0xCC

        yield dut.read_selector.eq(SpecialRegister.TRAP_PC)
        yield Settle()
        assert (yield dut.read_data) == 0xDD

        yield dut.read_selector.eq(SpecialRegister.TRAP_AUX)
        yield Settle()
        assert (yield dut.read_data) == 0xEE

    sim.add_sync_process(process)
    sim.run()
