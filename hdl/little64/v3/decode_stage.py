from __future__ import annotations

from amaranth import Elaboratable, Module, Mux, Signal

from .bundles import V3DecodedOperands
from .helpers import instruction_rd, instruction_rs1


class Little64V3DecodeStage(Elaboratable):
    """Decode-stage register read, bypass, and conservative load-use checks."""

    def __init__(self, regs, flags) -> None:
        self._regs = regs
        self._flags = flags

        self.instruction = Signal(16)

        self.execute_valid = Signal()
        self.execute_reg_write = Signal()
        self.execute_reg_index = Signal(4)
        self.execute_reg_value = Signal(64)
        self.execute_flags_write = Signal()
        self.execute_flags_value = Signal(3)

        self.memory_final_valid = Signal()
        self.memory_final_reg_write = Signal()
        self.memory_final_reg_index = Signal(4)
        self.memory_final_reg_value = Signal(64)
        self.memory_final_aux_reg_write = Signal()
        self.memory_final_aux_reg_index = Signal(4)
        self.memory_final_aux_reg_value = Signal(64)
        self.memory_final_flags_write = Signal()
        self.memory_final_flags_value = Signal(3)

        self.retire_valid = Signal()
        self.retire_reg_write = Signal()
        self.retire_reg_index = Signal(4)
        self.retire_reg_value = Signal(64)
        self.retire_aux_reg_write = Signal()
        self.retire_aux_reg_index = Signal(4)
        self.retire_aux_reg_value = Signal(64)
        self.retire_flags_write = Signal()
        self.retire_flags_value = Signal(3)

        self.pending_load_execute_valid = Signal()
        self.pending_load_execute_index = Signal(4)
        self.pending_load_memory_valid = Signal()
        self.pending_load_memory_index = Signal(4)
        self.pending_write_execute_valid = Signal()
        self.pending_write_execute_index = Signal(4)
        self.pending_write_memory_valid = Signal()
        self.pending_write_memory_index = Signal(4)

        self.outputs = V3DecodedOperands()
        self.load_use_hazard = Signal()

    def elaborate(self, platform):
        m = Module()

        decode_rd = instruction_rd(self.instruction)
        decode_rs1 = instruction_rs1(self.instruction)
        execute_hazard = Signal()
        memory_hazard = Signal()
        execute_write_hazard = Signal()
        memory_write_hazard = Signal()

        m.d.comb += [
            self.outputs.operand_a.eq(
                Mux(
                    decode_rd == 0,
                    0,
                    Mux(
                        self.execute_valid & self.execute_reg_write & (self.execute_reg_index == decode_rd),
                        self.execute_reg_value,
                        Mux(
                            self.memory_final_valid & self.memory_final_reg_write & (self.memory_final_reg_index == decode_rd),
                            self.memory_final_reg_value,
                            Mux(
                                self.memory_final_valid & self.memory_final_aux_reg_write & (self.memory_final_aux_reg_index == decode_rd),
                                self.memory_final_aux_reg_value,
                                Mux(
                                    self.retire_valid & self.retire_reg_write & (self.retire_reg_index == decode_rd),
                                    self.retire_reg_value,
                                    Mux(
                                        self.retire_valid & self.retire_aux_reg_write & (self.retire_aux_reg_index == decode_rd),
                                        self.retire_aux_reg_value,
                                        self._regs[decode_rd],
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            ),
            self.outputs.operand_b.eq(
                Mux(
                    decode_rs1 == 0,
                    0,
                    Mux(
                        self.execute_valid & self.execute_reg_write & (self.execute_reg_index == decode_rs1),
                        self.execute_reg_value,
                        Mux(
                            self.memory_final_valid & self.memory_final_reg_write & (self.memory_final_reg_index == decode_rs1),
                            self.memory_final_reg_value,
                            Mux(
                                self.memory_final_valid & self.memory_final_aux_reg_write & (self.memory_final_aux_reg_index == decode_rs1),
                                self.memory_final_aux_reg_value,
                                Mux(
                                    self.retire_valid & self.retire_reg_write & (self.retire_reg_index == decode_rs1),
                                    self.retire_reg_value,
                                    Mux(
                                        self.retire_valid & self.retire_aux_reg_write & (self.retire_aux_reg_index == decode_rs1),
                                        self.retire_aux_reg_value,
                                        self._regs[decode_rs1],
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            ),
            self.outputs.flags.eq(
                Mux(
                    self.execute_valid & self.execute_flags_write,
                    self.execute_flags_value,
                    Mux(
                        self.memory_final_valid & self.memory_final_flags_write,
                        self.memory_final_flags_value,
                        Mux(self.retire_valid & self.retire_flags_write, self.retire_flags_value, self._flags),
                    ),
                )
            ),
            execute_hazard.eq(
                self.pending_load_execute_valid &
                (self.pending_load_execute_index != 0) &
                ((self.pending_load_execute_index == decode_rd) | (self.pending_load_execute_index == decode_rs1))
            ),
            memory_hazard.eq(
                self.pending_load_memory_valid &
                (self.pending_load_memory_index != 0) &
                ((self.pending_load_memory_index == decode_rd) | (self.pending_load_memory_index == decode_rs1))
            ),
            execute_write_hazard.eq(
                self.pending_write_execute_valid &
                (self.pending_write_execute_index != 0) &
                ((self.pending_write_execute_index == decode_rd) | (self.pending_write_execute_index == decode_rs1))
            ),
            memory_write_hazard.eq(
                self.pending_write_memory_valid &
                (self.pending_write_memory_index != 0) &
                ((self.pending_write_memory_index == decode_rd) | (self.pending_write_memory_index == decode_rs1))
            ),
            self.load_use_hazard.eq(execute_hazard | memory_hazard | execute_write_hazard | memory_write_hazard),
        ]

        return m


__all__ = ['Little64V3DecodeStage']