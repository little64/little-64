from __future__ import annotations

from amaranth import Cat, Const, Mux

from ..isa import LSOpcode


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


def is_gp_format(instruction):
    return instruction_top3(instruction) == Const(0b110, 3)


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


def ls_condition(flags, opcode):
    z = flags[0]
    c = flags[1]
    s = flags[2]
    return Mux(opcode == LSOpcode.JUMP_Z, z,
        Mux(opcode == LSOpcode.JUMP_C, c,
        Mux(opcode == LSOpcode.JUMP_S, s,
        Mux(opcode == LSOpcode.JUMP_GT, (~z) & (~s),
        Mux(opcode == LSOpcode.JUMP_LT, s, Const(0, 1))))))


def is_canonical39(addr):
    sign_bit = addr[38]
    upper = addr[39:64]
    return Mux(sign_bit, upper == Const((1 << 25) - 1, 25), upper == 0)


def encode_aux(subtype: int, level):
    return Const(subtype, 64) | (level << 8)


__all__ = [
    'encode_aux',
    'flag_value',
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
    'is_canonical39',
    'is_gp_format',
    'ls_condition',
    'sign_extend',
]