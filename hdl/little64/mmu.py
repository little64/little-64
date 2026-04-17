from __future__ import annotations

from amaranth import Const, Mux


PTE_V = 1 << 0
PTE_R = 1 << 1
PTE_W = 1 << 2
PTE_X = 1 << 3
PTE_U = 1 << 4
PTE_RESERVED_MASK = 0xFFC0000000000000

ACCESS_READ = 0
ACCESS_WRITE = 1
ACCESS_EXECUTE = 2

AUX_SUBTYPE_NONE = 0
AUX_SUBTYPE_NO_VALID_PTE = 1
AUX_SUBTYPE_INVALID_NONLEAF = 2
AUX_SUBTYPE_PERMISSION = 3
AUX_SUBTYPE_RESERVED_BIT = 4
AUX_SUBTYPE_CANONICAL = 5


def is_canonical39(addr):
    sign_bit = addr[38]
    upper = addr[39:64]
    return Mux(sign_bit, upper == Const((1 << 25) - 1, 25), upper == 0)


def encode_aux(subtype: int, level):
    return Const(subtype, 64) | (level << 8)


__all__ = [
    'ACCESS_EXECUTE',
    'ACCESS_READ',
    'ACCESS_WRITE',
    'AUX_SUBTYPE_CANONICAL',
    'AUX_SUBTYPE_INVALID_NONLEAF',
    'AUX_SUBTYPE_NO_VALID_PTE',
    'AUX_SUBTYPE_NONE',
    'AUX_SUBTYPE_PERMISSION',
    'AUX_SUBTYPE_RESERVED_BIT',
    'PTE_R',
    'PTE_RESERVED_MASK',
    'PTE_U',
    'PTE_V',
    'PTE_W',
    'PTE_X',
    'encode_aux',
    'is_canonical39',
]