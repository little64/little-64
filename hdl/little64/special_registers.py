from __future__ import annotations

from amaranth import Const, Elaboratable, Module, Signal

from .config import Little64CoreConfig
from .isa import CPU_CONTROL_WRITABLE_MASK, SpecialRegister


class Little64SpecialRegisterFile(Elaboratable):
    def __init__(self, config: Little64CoreConfig) -> None:
        self.config = config

        self.user_mode = Signal()
        self.read_selector = Signal(16)
        self.read_data = Signal(64)
        self.read_access_fault = Signal()

        self.write_stb = Signal()
        self.write_selector = Signal(16)
        self.write_data = Signal(64)
        self.write_access_fault = Signal()
        self.tlb_flush = Signal()

        self.cpu_control = Signal(64)
        self.page_table_root_physical = Signal(64)
        self.boot_info_frame_physical = Signal(64)
        self.boot_source_page_size = Signal(64)
        self.boot_source_page_count = Signal(64)
        self.hypercall_caps = Signal(64)
        self.interrupt_table_base = Signal(64)
        self.interrupt_mask = Signal(64)
        self.interrupt_mask_high = Signal(64)
        self.interrupt_states = Signal(64)
        self.interrupt_states_high = Signal(64)
        self.interrupt_epc = Signal(64)
        self.interrupt_eflags = Signal(64)
        self.interrupt_cpu_control = Signal(64)
        self.trap_cause = Signal(64)
        self.trap_fault_addr = Signal(64)
        self.trap_access = Signal(64)
        self.trap_pc = Signal(64)
        self.trap_aux = Signal(64)
        self.thread_pointer = Signal(64)

    def elaborate(self, platform):
        m = Module()

        platform_regs_enabled = self.config.optional_platform_registers
        mmu_enabled = self.config.enable_mmu
        read_selector = self.read_selector[:16]
        write_selector = self.write_selector[:16]
        cpu_control_mask = Const(CPU_CONTROL_WRITABLE_MASK, 64)
        user_selector_allowed = read_selector == SpecialRegister.THREAD_POINTER
        user_write_selector_allowed = write_selector == SpecialRegister.THREAD_POINTER

        m.d.comb += [
            self.read_data.eq(0),
            self.read_access_fault.eq(self.user_mode & ~user_selector_allowed),
            self.write_access_fault.eq(self.user_mode & ~user_write_selector_allowed & self.write_stb),
            self.tlb_flush.eq(0),
        ]

        with m.Switch(read_selector):
            with m.Case(SpecialRegister.CPU_CONTROL):
                m.d.comb += self.read_data.eq(self.cpu_control & cpu_control_mask)
            with m.Case(SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL):
                if mmu_enabled:
                    m.d.comb += self.read_data.eq(self.page_table_root_physical)
            with m.Case(SpecialRegister.BOOT_INFO_FRAME_PHYSICAL):
                if platform_regs_enabled:
                    m.d.comb += self.read_data.eq(self.boot_info_frame_physical)
            with m.Case(SpecialRegister.BOOT_SOURCE_PAGE_SIZE):
                if platform_regs_enabled:
                    m.d.comb += self.read_data.eq(self.boot_source_page_size)
            with m.Case(SpecialRegister.BOOT_SOURCE_PAGE_COUNT):
                if platform_regs_enabled:
                    m.d.comb += self.read_data.eq(self.boot_source_page_count)
            with m.Case(SpecialRegister.HYPERCALL_CAPS):
                if platform_regs_enabled:
                    m.d.comb += self.read_data.eq(self.hypercall_caps)
            with m.Case(SpecialRegister.INTERRUPT_TABLE_BASE):
                m.d.comb += self.read_data.eq(self.interrupt_table_base)
            with m.Case(SpecialRegister.INTERRUPT_MASK):
                m.d.comb += self.read_data.eq(self.interrupt_mask)
            with m.Case(SpecialRegister.INTERRUPT_MASK_HIGH):
                m.d.comb += self.read_data.eq(self.interrupt_mask_high)
            with m.Case(SpecialRegister.INTERRUPT_STATES):
                m.d.comb += self.read_data.eq(self.interrupt_states)
            with m.Case(SpecialRegister.INTERRUPT_STATES_HIGH):
                m.d.comb += self.read_data.eq(self.interrupt_states_high)
            with m.Case(SpecialRegister.INTERRUPT_EPC):
                m.d.comb += self.read_data.eq(self.interrupt_epc)
            with m.Case(SpecialRegister.INTERRUPT_EFLAGS):
                m.d.comb += self.read_data.eq(self.interrupt_eflags)
            with m.Case(SpecialRegister.INTERRUPT_CPU_CONTROL):
                m.d.comb += self.read_data.eq(self.interrupt_cpu_control & cpu_control_mask)
            with m.Case(SpecialRegister.TRAP_CAUSE):
                m.d.comb += self.read_data.eq(self.trap_cause)
            with m.Case(SpecialRegister.TRAP_FAULT_ADDR):
                m.d.comb += self.read_data.eq(self.trap_fault_addr)
            with m.Case(SpecialRegister.TRAP_ACCESS):
                m.d.comb += self.read_data.eq(self.trap_access)
            with m.Case(SpecialRegister.TRAP_PC):
                m.d.comb += self.read_data.eq(self.trap_pc)
            with m.Case(SpecialRegister.TRAP_AUX):
                m.d.comb += self.read_data.eq(self.trap_aux)
            with m.Case(SpecialRegister.THREAD_POINTER):
                m.d.comb += self.read_data.eq(self.thread_pointer)

        with m.If(self.write_stb & ~self.write_access_fault):
            with m.Switch(write_selector):
                with m.Case(SpecialRegister.CPU_CONTROL):
                    m.d.sync += self.cpu_control.eq(self.write_data & cpu_control_mask)
                    m.d.comb += self.tlb_flush.eq(1)
                with m.Case(SpecialRegister.PAGE_TABLE_ROOT_PHYSICAL):
                    if mmu_enabled:
                        m.d.sync += self.page_table_root_physical.eq(self.write_data)
                        m.d.comb += self.tlb_flush.eq(1)
                with m.Case(SpecialRegister.BOOT_INFO_FRAME_PHYSICAL):
                    if platform_regs_enabled:
                        m.d.sync += self.boot_info_frame_physical.eq(self.write_data)
                with m.Case(SpecialRegister.BOOT_SOURCE_PAGE_SIZE):
                    if platform_regs_enabled:
                        m.d.sync += self.boot_source_page_size.eq(self.write_data)
                with m.Case(SpecialRegister.BOOT_SOURCE_PAGE_COUNT):
                    if platform_regs_enabled:
                        m.d.sync += self.boot_source_page_count.eq(self.write_data)
                with m.Case(SpecialRegister.HYPERCALL_CAPS):
                    if platform_regs_enabled:
                        m.d.sync += self.hypercall_caps.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_TABLE_BASE):
                    m.d.sync += self.interrupt_table_base.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_MASK):
                    m.d.sync += self.interrupt_mask.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_MASK_HIGH):
                    m.d.sync += self.interrupt_mask_high.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_STATES):
                    m.d.sync += self.interrupt_states.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_STATES_HIGH):
                    m.d.sync += self.interrupt_states_high.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_EPC):
                    m.d.sync += self.interrupt_epc.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_EFLAGS):
                    m.d.sync += self.interrupt_eflags.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_CPU_CONTROL):
                    m.d.sync += self.interrupt_cpu_control.eq(self.write_data & cpu_control_mask)
                with m.Case(SpecialRegister.TRAP_CAUSE):
                    m.d.sync += self.trap_cause.eq(self.write_data)
                with m.Case(SpecialRegister.TRAP_FAULT_ADDR):
                    m.d.sync += self.trap_fault_addr.eq(self.write_data)
                with m.Case(SpecialRegister.TRAP_ACCESS):
                    m.d.sync += self.trap_access.eq(self.write_data)
                with m.Case(SpecialRegister.TRAP_PC):
                    m.d.sync += self.trap_pc.eq(self.write_data)
                with m.Case(SpecialRegister.TRAP_AUX):
                    m.d.sync += self.trap_aux.eq(self.write_data)
                with m.Case(SpecialRegister.THREAD_POINTER):
                    m.d.sync += self.thread_pointer.eq(self.write_data)

        return m
