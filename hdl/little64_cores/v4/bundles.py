"""V4 pipeline register bundles.

Each bundle represents the latch between two adjacent pipeline stages. Signals
are plain Amaranth Signal objects (not Elaboratables) so they can be declared
inline in the core and updated via m.d.sync assignments.
"""
from __future__ import annotations

from amaranth import Signal


class V4FetchDecodeReg:
    """Fetch → Decode pipeline latch."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.instruction = Signal(16)
        self.pc = Signal(64)
        self.post_increment_pc = Signal(64)


class V4DecodeExecuteReg:
    """Decode → Execute pipeline latch.

    Includes *predicted_next_pc* — the address the predictor (at decode time)
    believed would follow this instruction.  Execute compares its computed
    actual_next_pc against this value to detect mispredictions.  For a
    static not-taken predictor this equals post_increment_pc; for a
    backward-taken predictor it may be a branch target address.
    """

    def __init__(self) -> None:
        self.valid = Signal()
        self.instruction = Signal(16)
        self.pc = Signal(64)
        self.post_increment_pc = Signal(64)
        self.operand_a = Signal(64)
        self.operand_b = Signal(64)
        self.flags = Signal(3)
        self.predicted_next_pc = Signal(64)


class V4MemoryReg:
    """Execute → Memory pipeline latch (mirrors V3MemoryStageState)."""

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


class V4FaultBundle:
    """Registered snapshot of the priority-encoded fault (mirrors V3FaultBundle)."""

    def __init__(self) -> None:
        self.pending = Signal()
        self.cause = Signal(64)
        self.pc = Signal(64)
        self.fault_addr = Signal(64)
        self.access = Signal(64)
        self.aux = Signal(64)


class V4RetireReg:
    """Memory-final / Execute → Retire pipeline latch (mirrors V3RetireStageState)."""

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
    'V4DecodeExecuteReg',
    'V4FaultBundle',
    'V4FetchDecodeReg',
    'V4MemoryReg',
    'V4RetireReg',
]
