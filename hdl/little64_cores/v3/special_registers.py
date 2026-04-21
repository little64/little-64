from __future__ import annotations

from amaranth import Const, Elaboratable, Module, Signal

from ..config import Little64CoreConfig
from ..isa import CPU_CONTROL_WRITABLE_MASK, SpecialRegister


class _Little64TrapRegisterBank(Elaboratable):
    def __init__(
        self,
        *,
        trap_cause: Signal,
        trap_fault_addr: Signal,
        trap_access: Signal,
        trap_pc: Signal,
        trap_aux: Signal,
    ) -> None:
        self.read_selector = Signal(16)
        self.read_data = Signal(64)
        self.write_stb = Signal()
        self.write_selector = Signal(16)
        self.write_data = Signal(64)

        self.core_trap_write = Signal()
        self.core_trap_cause_data = Signal(64)
        self.core_trap_fault_addr_data = Signal(64)
        self.core_trap_access_data = Signal(64)
        self.core_trap_pc_data = Signal(64)
        self.core_trap_aux_data = Signal(64)

        self._trap_cause = trap_cause
        self._trap_fault_addr = trap_fault_addr
        self._trap_access = trap_access
        self._trap_pc = trap_pc
        self._trap_aux = trap_aux

    def elaborate(self, platform):
        m = Module()

        write_trap_cause = Signal()
        write_trap_fault_addr = Signal()
        write_trap_access = Signal()
        write_trap_pc = Signal()
        write_trap_aux = Signal()

        m.d.comb += [
            self.read_data.eq(0),
            write_trap_cause.eq(self.write_stb & (self.write_selector == SpecialRegister.TRAP_CAUSE)),
            write_trap_fault_addr.eq(self.write_stb & (self.write_selector == SpecialRegister.TRAP_FAULT_ADDR)),
            write_trap_access.eq(self.write_stb & (self.write_selector == SpecialRegister.TRAP_ACCESS)),
            write_trap_pc.eq(self.write_stb & (self.write_selector == SpecialRegister.TRAP_PC)),
            write_trap_aux.eq(self.write_stb & (self.write_selector == SpecialRegister.TRAP_AUX)),
        ]

        with m.Switch(self.read_selector):
            with m.Case(SpecialRegister.TRAP_CAUSE):
                m.d.comb += self.read_data.eq(self._trap_cause)
            with m.Case(SpecialRegister.TRAP_FAULT_ADDR):
                m.d.comb += self.read_data.eq(self._trap_fault_addr)
            with m.Case(SpecialRegister.TRAP_ACCESS):
                m.d.comb += self.read_data.eq(self._trap_access)
            with m.Case(SpecialRegister.TRAP_PC):
                m.d.comb += self.read_data.eq(self._trap_pc)
            with m.Case(SpecialRegister.TRAP_AUX):
                m.d.comb += self.read_data.eq(self._trap_aux)

        with m.If(self.core_trap_write):
            m.d.sync += [
                self._trap_cause.eq(self.core_trap_cause_data),
                self._trap_fault_addr.eq(self.core_trap_fault_addr_data),
                self._trap_access.eq(self.core_trap_access_data),
                self._trap_pc.eq(self.core_trap_pc_data),
                self._trap_aux.eq(self.core_trap_aux_data),
            ]
        with m.Else():
            with m.If(write_trap_cause):
                m.d.sync += self._trap_cause.eq(self.write_data)
            with m.If(write_trap_fault_addr):
                m.d.sync += self._trap_fault_addr.eq(self.write_data)
            with m.If(write_trap_access):
                m.d.sync += self._trap_access.eq(self.write_data)
            with m.If(write_trap_pc):
                m.d.sync += self._trap_pc.eq(self.write_data)
            with m.If(write_trap_aux):
                m.d.sync += self._trap_aux.eq(self.write_data)

        return m


class Little64V3SpecialRegisterFile(Elaboratable):
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

        self.core_cpu_control_write = Signal()
        self.core_cpu_control_data = Signal(64)
        self.core_interrupt_cpu_control_write = Signal()
        self.core_interrupt_cpu_control_data = Signal(64)
        self.core_interrupt_epc_write = Signal()
        self.core_interrupt_epc_data = Signal(64)
        self.core_interrupt_eflags_write = Signal()
        self.core_interrupt_eflags_data = Signal(64)
        self.core_trap_write = Signal()
        self.core_trap_cause_data = Signal(64)
        self.core_trap_fault_addr_data = Signal(64)
        self.core_trap_access_data = Signal(64)
        self.core_trap_pc_data = Signal(64)
        self.core_trap_aux_data = Signal(64)

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
        self.interrupt_states_high_set = Signal(64)
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
        pending_interrupt_states_high = Signal(64)
        trap_read_data = Signal(64)

        trap_bank = _Little64TrapRegisterBank(
            trap_cause=self.trap_cause,
            trap_fault_addr=self.trap_fault_addr,
            trap_access=self.trap_access,
            trap_pc=self.trap_pc,
            trap_aux=self.trap_aux,
        )
        m.submodules.trap_bank = trap_bank

        m.d.comb += [
            trap_bank.read_selector.eq(read_selector),
            trap_bank.write_stb.eq(self.write_stb & ~self.write_access_fault),
            trap_bank.write_selector.eq(write_selector),
            trap_bank.write_data.eq(self.write_data),
            trap_bank.core_trap_write.eq(self.core_trap_write),
            trap_bank.core_trap_cause_data.eq(self.core_trap_cause_data),
            trap_bank.core_trap_fault_addr_data.eq(self.core_trap_fault_addr_data),
            trap_bank.core_trap_access_data.eq(self.core_trap_access_data),
            trap_bank.core_trap_pc_data.eq(self.core_trap_pc_data),
            trap_bank.core_trap_aux_data.eq(self.core_trap_aux_data),
            trap_read_data.eq(trap_bank.read_data),
            self.read_data.eq(trap_read_data),
            self.read_access_fault.eq(self.user_mode & ~user_selector_allowed),
            self.write_access_fault.eq(self.user_mode & ~user_write_selector_allowed & self.write_stb),
            self.tlb_flush.eq(0),
            pending_interrupt_states_high.eq(self.interrupt_states_high | self.interrupt_states_high_set),
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
            with m.Case(SpecialRegister.THREAD_POINTER):
                m.d.comb += self.read_data.eq(self.thread_pointer)
            with m.Default():
                pass

        with m.If(self.core_cpu_control_write):
            m.d.sync += self.cpu_control.eq(self.core_cpu_control_data & cpu_control_mask)
            m.d.comb += self.tlb_flush.eq(1)
        with m.If(self.core_interrupt_cpu_control_write):
            m.d.sync += self.interrupt_cpu_control.eq(self.core_interrupt_cpu_control_data & cpu_control_mask)
        with m.If(self.core_interrupt_epc_write):
            m.d.sync += self.interrupt_epc.eq(self.core_interrupt_epc_data)
        with m.If(self.core_interrupt_eflags_write):
            m.d.sync += self.interrupt_eflags.eq(self.core_interrupt_eflags_data)

        with m.If(self.write_stb & ~self.write_access_fault):
            with m.Switch(write_selector):
                with m.Case(SpecialRegister.CPU_CONTROL):
                    with m.If(~self.core_cpu_control_write):
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
                    m.d.sync += self.interrupt_states_high.eq(self.write_data | self.interrupt_states_high_set)
                with m.Case(SpecialRegister.INTERRUPT_EPC):
                    m.d.sync += self.interrupt_epc.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_EFLAGS):
                    with m.If(~self.core_interrupt_eflags_write):
                        m.d.sync += self.interrupt_eflags.eq(self.write_data)
                with m.Case(SpecialRegister.INTERRUPT_CPU_CONTROL):
                    with m.If(~self.core_interrupt_cpu_control_write):
                        m.d.sync += self.interrupt_cpu_control.eq(self.write_data & cpu_control_mask)
                with m.Case(SpecialRegister.THREAD_POINTER):
                    m.d.sync += self.thread_pointer.eq(self.write_data)
                with m.Default():
                    pass
        with m.Elif(self.interrupt_states_high_set != 0):
            m.d.sync += self.interrupt_states_high.eq(pending_interrupt_states_high)

        return m
