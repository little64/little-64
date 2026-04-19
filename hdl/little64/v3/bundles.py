from __future__ import annotations

from amaranth import Signal


class V3DecodedOperands:
    """Decode-stage outputs after register read and bypass selection."""

    def __init__(self) -> None:
        self.operand_a = Signal(64)
        self.operand_b = Signal(64)
        self.flags = Signal(3)


class V3ExecuteOutputs:
    """Combinational execute-stage results for the current instruction."""

    def __init__(self) -> None:
        self.reg_write = Signal()
        self.reg_index = Signal(4)
        self.reg_value = Signal(64)
        self.flags_write = Signal()
        self.flags_value = Signal(3)
        self.cpu_control_write = Signal()
        self.cpu_control_value = Signal(64)
        self.next_pc = Signal(64)
        self.halt = Signal()
        self.lockup = Signal()
        self.trap = Signal()
        self.trap_cause = Signal(64)
        self.clear_reservation = Signal()
        self.memory_start = Signal()
        self.memory_addr = Signal(64)
        self.memory_width_bytes = Signal(4)
        self.memory_write = Signal()
        self.memory_store_value = Signal(64)
        self.memory_reg_write = Signal()
        self.memory_reg_index = Signal(4)
        self.memory_flags_write = Signal()
        self.memory_flags_value = Signal(3)
        self.memory_set_reservation = Signal()
        self.memory_reservation_addr = Signal(64)
        self.memory_next_pc = Signal(64)
        self.memory_post_reg_write = Signal()
        self.memory_post_reg_index = Signal(4)
        self.memory_post_reg_value = Signal(64)
        self.memory_post_reg_delta = Signal(64)
        self.memory_post_reg_use_load_result = Signal()
        self.memory_chain_store = Signal()
        self.memory_chain_store_addr = Signal(64)
        self.memory_chain_store_use_load_result = Signal()
        self.memory_chain_store_value = Signal(64)


class V3MemoryStageState:
    """State carried by the dedicated LSU-backed memory stage."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.request_started = Signal()
        self.virtual_addr = Signal(64)
        self.addr = Signal(64)
        self.phys_valid = Signal()
        self.width_bytes = Signal(4)
        self.write = Signal()
        self.store_value = Signal(64)
        self.reg_write = Signal()
        self.reg_index = Signal(4)
        self.flags_write = Signal()
        self.flags_value = Signal(3)
        self.set_reservation = Signal()
        self.reservation_addr = Signal(64)
        self.next_pc = Signal(64)
        self.commit_pc = Signal(64)
        self.fault_pc = Signal(64)
        self.post_reg_write = Signal()
        self.post_reg_index = Signal(4)
        self.post_reg_value = Signal(64)
        self.post_reg_delta = Signal(64)
        self.post_reg_use_load_result = Signal()
        self.chain_store = Signal()
        self.chain_store_addr = Signal(64)
        self.chain_store_use_load_result = Signal()
        self.chain_store_value = Signal(64)


class V3FaultBundle:
    """Registered snapshot of the priority-encoded fault from all trap sources.

    Why: collecting fetch/memory/walk/retire fault candidates combinationally
    and then forming trap_cpu_control_value / entry_vector inline produced a
    36-LL cone through trap_bank_n_135 fanout (109) at Arty timing. One cycle
    of registration breaks that cone at a predictable trap-entry-only cost.
    """

    def __init__(self) -> None:
        self.pending = Signal()
        self.cause = Signal(64)
        self.pc = Signal(64)
        self.fault_addr = Signal(64)
        self.access = Signal(64)
        self.aux = Signal(64)


class V3RetireStageState:
    """Retire-stage state committed into architected state each cycle."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.reg_write = Signal()
        self.reg_index = Signal(4)
        self.reg_value = Signal(64)
        self.aux_reg_write = Signal()
        self.aux_reg_index = Signal(4)
        self.aux_reg_value = Signal(64)
        self.flags_write = Signal()
        self.flags_value = Signal(3)
        self.cpu_control_write = Signal()
        self.cpu_control_value = Signal(64)
        self.next_pc = Signal(64)
        self.commit = Signal()
        self.commit_pc = Signal(64)
        self.halt = Signal()
        self.lockup = Signal()
        self.trap = Signal()
        self.trap_cause = Signal(64)


__all__ = [
    'V3DecodedOperands',
    'V3ExecuteOutputs',
    'V3FaultBundle',
    'V3MemoryStageState',
    'V3RetireStageState',
]