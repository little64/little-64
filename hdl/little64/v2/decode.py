from __future__ import annotations

from ..decode import instruction_gp_opcode, instruction_top3, is_gp_format
from ..isa import GPOpcode


gp_opcode_bits = instruction_gp_opcode


def is_stop_instruction(instruction):
    return is_gp_format(instruction) & (instruction_gp_opcode(instruction) == GPOpcode.STOP)


__all__ = [
    'gp_opcode_bits',
    'instruction_gp_opcode',
    'instruction_top3',
    'is_gp_format',
    'is_stop_instruction',
]