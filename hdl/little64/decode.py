from __future__ import annotations

from amaranth import Const


def instruction_rd(instruction):
    return instruction[0:4]


def instruction_rs1(instruction):
    return instruction[4:8]


def instruction_gp_imm4(instruction):
    return instruction[4:8]


def instruction_ldi_imm8(instruction):
    return instruction[4:12]


def instruction_ls_offset2(instruction):
    return instruction[8:10]


def instruction_gp_opcode(instruction):
    return instruction[8:13]


def instruction_ls_opcode(instruction):
    return instruction[10:14]


def instruction_ldi_shift(instruction):
    return instruction[12:14]


def instruction_top3(instruction):
    return instruction[13:16]


def instruction_top2(instruction):
    return instruction[14:16]


def is_ldi_format(instruction):
    return instruction_top2(instruction) == Const(0b10, 2)


def is_gp_format(instruction):
    return instruction_top3(instruction) == Const(0b110, 3)


__all__ = [
    'instruction_gp_imm4',
    'instruction_gp_opcode',
    'instruction_ldi_imm8',
    'instruction_ldi_shift',
    'instruction_ls_offset2',
    'instruction_ls_opcode',
    'instruction_rd',
    'instruction_rs1',
    'instruction_top2',
    'instruction_top3',
    'is_gp_format',
    'is_ldi_format',
]