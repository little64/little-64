from __future__ import annotations

from amaranth import Cat, Const, Mux

from .isa import LSOpcode


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


__all__ = ['flag_value', 'ls_condition', 'sign_extend']