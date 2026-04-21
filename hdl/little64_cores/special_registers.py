from __future__ import annotations

from amaranth import Elaboratable, Signal

from .config import Little64CoreConfig
class Little64SpecialRegisterFile(Elaboratable):
    """Definition-only special-register interface.

    Core-local implementations live under basic/, v2/, and v3/.
    """

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
        raise NotImplementedError('Use core-local special-register implementations in basic/v2/v3')
