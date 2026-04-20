from __future__ import annotations

from amaranth import Cat, Const, Mux


def instruction_rd(instruction):
    return instruction[0:4]


def instruction_rs1(instruction):
    return instruction[4:8]


def instruction_gp_opcode(instruction):
    return instruction[8:13]


def instruction_ls_offset2(instruction):
    return instruction[8:10]


def instruction_ls_opcode(instruction):
    return instruction[10:14]


def instruction_top2(instruction):
    return instruction[14:16]


def instruction_top3(instruction):
    return instruction[13:16]


def sign_extend(value, width: int, target_width: int):
    extension_width = target_width - width
    if extension_width <= 0:
        return value
    return Cat(
        value,
        Mux(value[width - 1], Const((1 << extension_width) - 1, extension_width), Const(0, extension_width)),
    )


def flag_value(result, carry):
    return Cat(result == 0, carry, result[63])


__all__ = [
    'flag_value',
    'instruction_gp_opcode',
    'instruction_ls_offset2',
    'instruction_ls_opcode',
    'instruction_rd',
    'instruction_rs1',
    'instruction_top2',
    'instruction_top3',
    'sign_extend',
]