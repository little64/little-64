"""V4 branch predictor interface and static policies.

The predictor is an Amaranth Elaboratable wired as a submodule of the
V4 decode stage.  Its interface is stable so alternative policies (e.g.
dynamic 2-bit counters, BTB) can be dropped in without changing the
decode stage or core.

Predictor contract
------------------
Inputs (driven by decode stage from the FD pipeline register):
  instruction   -- 16-bit instruction word in the FD latch
  pc            -- PC of that instruction

Outputs (read by decode stage):
  is_branch        -- 1 if instruction is a conditional branch
  predicted_next_pc -- predicted address of the instruction that follows;
                       equals pc+2 for non-branches and for not-taken
                       predictions; equals branch target for taken predictions

The *predicted_next_pc* is stored in the DE latch so that execute can
compare it against the actual computed next_pc and signal a mispredict
when they differ.
"""
from __future__ import annotations

from amaranth import Elaboratable, Module, Mux, Signal

from ..isa import LSOpcode
from ..v3.helpers import sign_extend


class Little64V4StaticNotTakenPredictor(Elaboratable):
    """Always predict fall-through (PC + 2).

    Provides zero branch penalty for not-taken branches and the standard
    2-cycle flush penalty for taken branches.  Serves as a safe baseline
    and as the fall-back when the instruction is not a recognised branch.
    """

    def __init__(self) -> None:
        self.instruction = Signal(16)
        self.pc = Signal(64)

        self.is_branch = Signal()
        self.predicted_next_pc = Signal(64)

    def elaborate(self, platform):
        m = Module()
        top2 = self.instruction[14:16]
        top3 = self.instruction[13:16]
        ls_opcode = self.instruction[10:14]

        m.d.comb += [
            self.is_branch.eq(
                ((top2 == 0b01) & (ls_opcode >= LSOpcode.JUMP_Z)) |
                (top3 == 0b111)
            ),
            self.predicted_next_pc.eq(self.pc + 2),
        ]
        return m


class Little64V4StaticBackwardTakenPredictor(Elaboratable):
    """Predict taken for PC-relative conditional branches with negative offsets.

    A backward branch (loop back-edge) has a negative 10-bit PC-relative
    offset (bit 9 of the instruction word is 1) and is predicted taken.
    This eliminates the 2-cycle flush penalty for correctly-predicted loop
    back-edges, which is the primary bottleneck in tight ALU loops.

    Forward branches and register-indirect branches fall back to not-taken.
    """

    def __init__(self) -> None:
        self.instruction = Signal(16)
        self.pc = Signal(64)

        self.is_branch = Signal()
        self.predicted_next_pc = Signal(64)

    def elaborate(self, platform):
        m = Module()

        top2 = self.instruction[14:16]
        top3 = self.instruction[13:16]
        ls_opcode = self.instruction[10:14]

        post_increment_pc = Signal(64)
        # Signed 10-bit offset × 2 (format-01 conditional branches).
        jump_rel10 = Signal(64)
        cond_branch_target = Signal(64)
        # Signed 13-bit offset × 2 (format-111 unconditional UJMP).
        jump_rel13 = Signal(64)
        ujmp_target = Signal(64)

        is_pc_rel_cond_branch = Signal()
        is_cond_backward = Signal()
        is_ujmp = Signal()
        is_ujmp_backward = Signal()

        m.d.comb += [
            post_increment_pc.eq(self.pc + 2),
            jump_rel10.eq(sign_extend(self.instruction[0:10], 10, 64) << 1),
            cond_branch_target.eq(post_increment_pc + jump_rel10),
            jump_rel13.eq(sign_extend(self.instruction[0:13], 13, 64) << 1),
            ujmp_target.eq(post_increment_pc + jump_rel13),
            # Format-01 (top2 == 0b01) PC-relative conditional branch.
            is_pc_rel_cond_branch.eq((top2 == 0b01) & (ls_opcode >= LSOpcode.JUMP_Z)),
            # Negative offset for conditional branch → bit 9 (MSB of 10-bit field) is 1.
            is_cond_backward.eq(self.instruction[9]),
            # Format-111 (top3 == 0b111) unconditional UJMP.
            is_ujmp.eq(top3 == 0b111),
            # Negative offset for UJMP → bit 12 (MSB of 13-bit field) is 1.
            is_ujmp_backward.eq(self.instruction[12]),
            self.is_branch.eq(is_pc_rel_cond_branch | is_ujmp),
            self.predicted_next_pc.eq(
                Mux(
                    is_ujmp,
                    # Unconditional: always taken (backward or not).
                    ujmp_target,
                    Mux(
                        is_pc_rel_cond_branch & is_cond_backward,
                        cond_branch_target,
                        post_increment_pc,
                    ),
                )
            ),
        ]
        return m


__all__ = [
    'Little64V4StaticBackwardTakenPredictor',
    'Little64V4StaticNotTakenPredictor',
]
