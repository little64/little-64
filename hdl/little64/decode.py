from __future__ import annotations

# Shared decode metadata is definition-only; executable field extractors now
# live in per-core helper modules.
INSTR_RD_SLICE = (0, 4)
INSTR_RS1_SLICE = (4, 8)
INSTR_GP_IMM4_SLICE = (4, 8)
INSTR_LDI_IMM8_SLICE = (4, 12)
INSTR_LS_OFFSET2_SLICE = (8, 10)
INSTR_GP_OPCODE_SLICE = (8, 13)
INSTR_LS_OPCODE_SLICE = (10, 14)
INSTR_LDI_SHIFT_SLICE = (12, 14)
INSTR_TOP3_SLICE = (13, 16)
INSTR_TOP2_SLICE = (14, 16)
TOP2_LDI = 0b10
TOP3_GP = 0b110

__all__ = [
    'INSTR_GP_IMM4_SLICE',
    'INSTR_GP_OPCODE_SLICE',
    'INSTR_LDI_IMM8_SLICE',
    'INSTR_LDI_SHIFT_SLICE',
    'INSTR_LS_OFFSET2_SLICE',
    'INSTR_LS_OPCODE_SLICE',
    'INSTR_RD_SLICE',
    'INSTR_RS1_SLICE',
    'INSTR_TOP2_SLICE',
    'INSTR_TOP3_SLICE',
    'TOP2_LDI',
    'TOP3_GP',
]