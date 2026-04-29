"""V4 decode stage: register read, bypass forwarding, hazard detection, prediction.

Derived from the V3 decode stage but adds:
  * A branch-predictor submodule (swappable via constructor argument).
  * ``predicted_next_pc`` output — forwarded from the predictor to be stored
    in the DE pipeline register so execute can detect mispredictions.
  * ``predict_redirect`` output — high when the predictor has chosen a target
    other than PC+2, so the core can redirect the fetch PC before the branch
    reaches the execute stage.

The hazard detection and operand bypass paths are identical to V3.
"""
from __future__ import annotations

from amaranth import Elaboratable, Module, Mux, Signal

from ..v3.helpers import instruction_rd, instruction_rs1
from .bundles import V4DecodeExecuteReg
from .predictor import Little64V4StaticBackwardTakenPredictor


class Little64V4DecodeStage(Elaboratable):
    """Decode-stage register read, bypass forwarding, load-use hazard detection,
    and branch prediction for the V4 core."""

    def __init__(self, regs, flags, *, predictor=None) -> None:
        self._regs = regs
        self._flags = flags
        self._predictor = predictor

        # ---- inputs from FD latch ----
        self.instruction = Signal(16)
        self.pc = Signal(64)
        self.post_increment_pc = Signal(64)

        # ---- forwarding inputs (same as V3) ----
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

        # ---- outputs ----
        self.outputs = V4DecodeExecuteReg()   # operands forwarded to DE latch
        self.load_use_hazard = Signal()
        self.predicted_next_pc = Signal(64)   # from predictor, stored in DE latch
        self.predict_redirect = Signal()       # predictor chose target != PC+2

    def elaborate(self, platform):
        m = Module()

        predictor = self._predictor or Little64V4StaticBackwardTakenPredictor()
        m.submodules.predictor = predictor

        m.d.comb += [
            predictor.instruction.eq(self.instruction),
            predictor.pc.eq(self.pc),
            self.predicted_next_pc.eq(predictor.predicted_next_pc),
            self.predict_redirect.eq(
                predictor.is_branch & (predictor.predicted_next_pc != self.post_increment_pc)
            ),
        ]

        decode_rd = instruction_rd(self.instruction)
        decode_rs1 = instruction_rs1(self.instruction)
        execute_hazard = Signal()
        memory_hazard = Signal()
        execute_write_hazard = Signal()
        memory_write_hazard = Signal()

        # ---- Operand A (register Rd) bypass chain (same priority as V3) ----
        m.d.comb += self.outputs.operand_a.eq(
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
        )

        # ---- Operand B (register Rs1) bypass chain ----
        m.d.comb += self.outputs.operand_b.eq(
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
        )

        # ---- Flags bypass ----
        m.d.comb += self.outputs.flags.eq(
            Mux(
                self.execute_valid & self.execute_flags_write,
                self.execute_flags_value,
                Mux(
                    self.memory_final_valid & self.memory_final_flags_write,
                    self.memory_final_flags_value,
                    Mux(self.retire_valid & self.retire_flags_write, self.retire_flags_value, self._flags),
                ),
            )
        )

        # ---- Load-use / write hazard detection (same as V3) ----
        m.d.comb += [
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


__all__ = ['Little64V4DecodeStage']
