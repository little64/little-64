#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


MASK64 = (1 << 64) - 1
REPO_ROOT = Path(__file__).resolve().parents[2]
GP_OPCODE_PATH = REPO_ROOT / 'host' / 'arch' / 'opcodes_gp.def'
GP_CASES_PATH = REPO_ROOT / 'tests' / 'shared' / 'gp_alu_cases.def'
LDI_CASES_PATH = REPO_ROOT / 'tests' / 'shared' / 'ldi_cases.def'

RR_OPS = ('ADD', 'SUB', 'TEST', 'AND', 'OR', 'XOR', 'SLL', 'SRL', 'SRA')
IMM_OPS = ('SLLI', 'SRLI', 'SRAI')
TOPOLOGY_REGS = tuple(range(15))
LDI_TOPOLOGY_REGS = tuple(range(1, 15))

RR_TOPOLOGY_VALUES = {
    'ADD': (0x0123_4567_89AB_CDEF, 0x1111_2222_3333_4444, 0x0101_0101_0101_0101),
    'SUB': (0x0000_0000_0000_0101, 0x1111_2222_3333_4444, 0x0101_0101_0101_0101),
    'TEST': (0x0000_0000_0000_0101, 0x1111_2222_3333_4444, 0x0101_0101_0101_0101),
    'AND': (0x00FF_00FF_00FF_00FF, 0xF0F0_F0F0_F0F0_F0F0, 0xA5A5_A5A5_A5A5_A5A5),
    'OR': (0x00FF_00FF_00FF_00FF, 0x3300_3300_3300_3300, 0x0F0F_0F0F_0F0F_0F0F),
    'XOR': (0x00FF_00FF_00FF_00FF, 0x3300_3300_3300_3300, 0x0F0F_0F0F_0F0F_0F0F),
    'SLL': (1, 0x0123_4567_89AB_CDEF, 1),
    'SRL': (1, 0xF123_4567_89AB_CDEF, 1),
    'SRA': (1, 0xF123_4567_89AB_CDEF, 1),
}

IMM_TOPOLOGY_INITIALS = {
    'SLLI': 0x0123_4567_89AB_CDEF,
    'SRLI': 0xFEDC_BA98_7654_3211,
    'SRAI': 0xF123_4567_89AB_CDEF,
}

LDI_FULL_SWEEP_INITIALS = {
    0: 0xFFFF_FFFF_FFFF_FFFF,
    1: 0x0000_0000_0000_0055,
    2: 0x0000_0000_0000_1234,
    3: 0x0000_0000_0012_3456,
}


def _u64(value: int) -> int:
    return value & MASK64


def _format_int(value: int) -> str:
    if value < 0:
        raise ValueError('instruction-case generator only emits non-negative literals')
    if value <= 9:
        return str(value)
    return f'0x{value:X}'


def _quote(text: str) -> str:
    return json.dumps(text)


def _format_macro(name: str, arguments: list[str]) -> str:
    return f'{name}({", ".join(arguments)})'


def _flag_bits(*, z: bool, c: bool, s: bool) -> int:
    return (1 if z else 0) | ((1 if c else 0) << 1) | ((1 if s else 0) << 2)


def _flags_from_result(result: int, *, carry: bool) -> int:
    result = _u64(result)
    return _flag_bits(z=result == 0, c=carry, s=bool((result >> 63) & 1))


def _signed_u64(value: int) -> int:
    value = _u64(value)
    if value & (1 << 63):
        return value - (1 << 64)
    return value


def _eval_shift_left(value: int, count: int) -> tuple[int, int]:
    value = _u64(value)
    if count == 0:
        result = value
        carry = False
    elif count >= 64:
        result = 0
        carry = False
    else:
        result = _u64(value << count)
        carry = (value >> (64 - count)) != 0
    return result, _flags_from_result(result, carry=carry)


def _eval_shift_right_logical(value: int, count: int) -> tuple[int, int]:
    value = _u64(value)
    if count == 0:
        result = value
        carry = False
    elif count >= 64:
        result = 0
        carry = False
    else:
        result = value >> count
        carry = bool((value >> (count - 1)) & 1)
    return result, _flags_from_result(result, carry=carry)


def _eval_shift_right_arithmetic(value: int, count: int) -> tuple[int, int]:
    value = _u64(value)
    if count == 0:
        result = value
        carry = False
    elif count >= 64:
        result = MASK64 if (value & (1 << 63)) else 0
        carry = False
    else:
        result = _u64(_signed_u64(value) >> count)
        carry = bool((value >> (count - 1)) & 1)
    return result, _flags_from_result(result, carry=carry)


def _eval_gp_rr(opcode: str, rs1_value: int, rd_value: int) -> tuple[int, int]:
    rs1_value = _u64(rs1_value)
    rd_value = _u64(rd_value)

    if opcode == 'ADD':
        full = rd_value + rs1_value
        result = _u64(full)
        return result, _flags_from_result(result, carry=full > MASK64)
    if opcode == 'SUB':
        result = _u64(rd_value - rs1_value)
        return result, _flags_from_result(result, carry=rs1_value > rd_value)
    if opcode == 'TEST':
        temp = _u64(rd_value - rs1_value)
        return rd_value, _flags_from_result(temp, carry=rs1_value > rd_value)
    if opcode == 'AND':
        result = rd_value & rs1_value
        return result, _flags_from_result(result, carry=False)
    if opcode == 'OR':
        result = rd_value | rs1_value
        return result, _flags_from_result(result, carry=False)
    if opcode == 'XOR':
        result = rd_value ^ rs1_value
        return result, _flags_from_result(result, carry=False)
    if opcode == 'SLL':
        return _eval_shift_left(rd_value, rs1_value)
    if opcode == 'SRL':
        return _eval_shift_right_logical(rd_value, rs1_value)
    if opcode == 'SRA':
        return _eval_shift_right_arithmetic(rd_value, rs1_value)
    raise ValueError(f'unhandled GP RR opcode: {opcode}')


def _eval_gp_imm(opcode: str, imm4: int, rd_value: int) -> tuple[int, int]:
    if opcode == 'SLLI':
        return _eval_shift_left(rd_value, imm4)
    if opcode == 'SRLI':
        return _eval_shift_right_logical(rd_value, imm4)
    if opcode == 'SRAI':
        return _eval_shift_right_arithmetic(rd_value, imm4)
    raise ValueError(f'unhandled GP IMM opcode: {opcode}')


def _eval_ldi(shift: int, imm8: int, initial: int) -> int:
    initial = _u64(initial)
    imm8 &= 0xFF
    if shift == 0:
        return imm8
    if shift == 1:
        return _u64(initial | (imm8 << 8))
    if shift == 2:
        return _u64(initial | (imm8 << 16))
    if shift == 3:
        value = initial | (imm8 << 24)
        if imm8 & 0x80:
            value |= ~((1 << 32) - 1)
        return _u64(value)
    raise ValueError(f'unhandled LDI shift: {shift}')


def _seed_value(register_index: int, requested: int) -> int:
    return 0 if register_index == 0 else _u64(requested)


def _parse_gp_opcode_metadata() -> dict[str, int]:
    pattern = re.compile(r'^LITTLE64_GP_OPCODE\([^,]+,\s*\d+,\s*"([^"]+)",\s*(\d+)\)')
    opcodes: dict[str, int] = {}
    for raw_line in GP_OPCODE_PATH.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('//'):
            continue
        match = pattern.match(line)
        if match:
            opcodes[match.group(1)] = int(match.group(2))
    return opcodes


def _validate_gp_opcode_metadata() -> None:
    opcodes = _parse_gp_opcode_metadata()
    for mnemonic in RR_OPS:
        if opcodes.get(mnemonic) != 2:
            raise SystemExit(f'expected GP opcode {mnemonic} to have RS1_RD encoding in {GP_OPCODE_PATH}')
    for mnemonic in IMM_OPS:
        if opcodes.get(mnemonic) != 3:
            raise SystemExit(f'expected GP opcode {mnemonic} to have IMM4_RD encoding in {GP_OPCODE_PATH}')


def _generate_gp_rr_cases() -> list[str]:
    rows: list[str] = []

    semantic_cases = [
        ('ADD', 1, 3, 2, 4, 'ADD 3+4=7'),
        ('ADD', 1, 0, 2, 0, 'ADD 0+0=0'),
        ('ADD', 1, 0, 2, 0x8000000000000000, 'ADD sign flag'),
        ('ADD', 1, 1, 2, 0xFFFFFFFFFFFFFFFF, 'ADD carry wrap to zero'),
        ('ADD', 1, 2, 2, 0xFFFFFFFFFFFFFFFF, 'ADD carry wrap to one'),
        ('SUB', 1, 3, 2, 7, 'SUB 7-3=4'),
        ('SUB', 1, 5, 2, 5, 'SUB 5-5=0'),
        ('SUB', 1, 5, 2, 3, 'SUB borrow sets C and S'),
        ('SUB', 1, 3, 2, 5, 'SUB 5-3 no borrow'),
        ('SUB', 1, 1, 2, 0, 'SUB 0-1 wraps negative'),
        ('TEST', 1, 7, 2, 7, 'TEST equal preserves Rd'),
        ('TEST', 1, 3, 2, 7, 'TEST Rd greater than Rs1'),
        ('TEST', 1, 7, 2, 3, 'TEST borrow preserves Rd'),
        ('AND', 1, 0xF, 2, 0xFF, 'AND mask low bits'),
        ('AND', 1, 0xF0, 2, 0x0F, 'AND zero result'),
        ('AND', 1, 0xFFFFFFFFFFFFFFFF, 2, 0xABCD, 'AND identity'),
        ('AND', 1, 0xFFFFFFFFFFFFFFFF, 2, 0x8000000000000000, 'AND sign flag'),
        ('OR', 1, 0xF0, 2, 0x0F, 'OR combine bits'),
        ('OR', 1, 0, 2, 0, 'OR zero result'),
        ('OR', 1, 0x8000000000000000, 2, 0, 'OR sign flag'),
        ('XOR', 1, 0xF0, 2, 0xFF, 'XOR toggle bits'),
        ('XOR', 1, 0xDEAD, 2, 0xDEAD, 'XOR self cancel'),
        ('XOR', 1, 0, 2, 0x8000000000000000, 'XOR sign flag'),
        ('SLL', 1, 0, 2, 42, 'SLL shift zero'),
        ('SLL', 1, 1, 2, 1, 'SLL basic shift'),
        ('SLL', 1, 63, 2, 1, 'SLL shift to sign bit'),
        ('SLL', 1, 1, 2, 0x8000000000000000, 'SLL carry from msb'),
        ('SLL', 1, 64, 2, 0xFFFFFFFFFFFFFFFF, 'SLL shift ge 64'),
        ('SLL', 1, 65, 2, 1, 'SLL shift 65'),
        ('SRL', 1, 0, 2, 0xABCD, 'SRL shift zero'),
        ('SRL', 1, 1, 2, 4, 'SRL 4>>1'),
        ('SRL', 1, 1, 2, 1, 'SRL carry from bit zero'),
        ('SRL', 1, 1, 2, 0x8000000000000000, 'SRL logical no sign extend'),
        ('SRL', 1, 63, 2, 0x8000000000000000, 'SRL msb down to one'),
        ('SRL', 1, 64, 2, 0xFFFFFFFFFFFFFFFF, 'SRL shift ge 64'),
        ('SRA', 1, 0, 2, 42, 'SRA shift zero'),
        ('SRA', 1, 1, 2, 4, 'SRA positive shift'),
        ('SRA', 1, 1, 2, 1, 'SRA carry from bit zero'),
        ('SRA', 1, 1, 2, 0x8000000000000000, 'SRA sign extends'),
        ('SRA', 1, 63, 2, 0x8000000000000000, 'SRA negative >>63'),
        ('SRA', 1, 64, 2, 0x8000000000000000, 'SRA negative shift ge 64'),
        ('SRA', 1, 64, 2, 1, 'SRA positive shift ge 64'),
    ]

    for opcode, rs1, rs1_value, rd, rd_value, description in semantic_cases:
        expected_rd, expected_flags = _eval_gp_rr(opcode, rs1_value, rd_value)
        rows.append(_format_macro(
            'LITTLE64_GP_TWO_REG_CASE',
            [
                _quote(opcode),
                _format_int(rs1),
                _format_int(rs1_value),
                _format_int(rd),
                _format_int(rd_value),
                _format_int(expected_rd),
                _format_int(expected_flags),
                _quote(description),
            ],
        ))

    for opcode in RR_OPS:
        rs1_template, rd_template, alias_template = RR_TOPOLOGY_VALUES[opcode]
        for rs1 in TOPOLOGY_REGS:
            for rd in TOPOLOGY_REGS:
                if rs1 == rd:
                    rs1_value = _seed_value(rs1, alias_template)
                    rd_value = rs1_value
                else:
                    rs1_value = _seed_value(rs1, rs1_template)
                    rd_value = _seed_value(rd, rd_template)
                expected_rd, expected_flags = _eval_gp_rr(opcode, rs1_value, rd_value)
                rows.append(_format_macro(
                    'LITTLE64_GP_TWO_REG_CASE',
                    [
                        _quote(opcode),
                        _format_int(rs1),
                        _format_int(rs1_value),
                        _format_int(rd),
                        _format_int(rd_value),
                        _format_int(expected_rd),
                        _format_int(expected_flags),
                        _quote(f'{opcode} topology rs1=R{rs1} rd=R{rd}'),
                    ],
                ))

    return rows


def _generate_gp_imm_cases() -> list[str]:
    rows: list[str] = []

    semantic_cases = [
        ('SLLI', 0, 1, 42, 'SLLI shift zero'),
        ('SLLI', 0, 1, 0, 'SLLI zero result'),
        ('SLLI', 1, 1, 1, 'SLLI 1<<1'),
        ('SLLI', 15, 1, 1, 'SLLI 1<<15'),
        ('SLLI', 1, 1, 0x4000000000000000, 'SLLI sign flag'),
        ('SLLI', 1, 1, 0x8000000000000000, 'SLLI carry from msb'),
        ('SLLI', 4, 1, 0xF000000000000000, 'SLLI multi-bit carry'),
        ('SRLI', 0, 1, 42, 'SRLI shift zero'),
        ('SRLI', 1, 1, 2, 'SRLI 2>>1'),
        ('SRLI', 1, 1, 1, 'SRLI carry from bit zero'),
        ('SRLI', 15, 1, 0x8000, 'SRLI down to one'),
        ('SRLI', 1, 1, 0x8000000000000000, 'SRLI logical no sign extend'),
        ('SRLI', 1, 1, 0xFFFFFFFFFFFFFFFF, 'SRLI all ones'),
        ('SRAI', 0, 1, 42, 'SRAI shift zero'),
        ('SRAI', 1, 1, 4, 'SRAI positive shift'),
        ('SRAI', 1, 1, 1, 'SRAI carry from bit zero'),
        ('SRAI', 1, 1, 0x8000000000000000, 'SRAI sign extends'),
        ('SRAI', 4, 1, 0x8000000000000000, 'SRAI fill top bits'),
        ('SRAI', 15, 1, 0x0000000000008000, 'SRAI positive down to one'),
        ('SRAI', 15, 1, 0x8000000000000000, 'SRAI wide negative shift'),
    ]

    for opcode, imm4, rd, initial, description in semantic_cases:
        expected_rd, expected_flags = _eval_gp_imm(opcode, imm4, initial)
        rows.append(_format_macro(
            'LITTLE64_GP_IMM_CASE',
            [
                _quote(opcode),
                _format_int(imm4),
                _format_int(rd),
                _format_int(initial),
                _format_int(expected_rd),
                _format_int(expected_flags),
                _quote(description),
            ],
        ))

    for opcode in IMM_OPS:
        initial_template = IMM_TOPOLOGY_INITIALS[opcode]
        for rd in TOPOLOGY_REGS:
            for imm4 in range(16):
                initial = _seed_value(rd, initial_template)
                expected_rd, expected_flags = _eval_gp_imm(opcode, imm4, initial)
                rows.append(_format_macro(
                    'LITTLE64_GP_IMM_CASE',
                    [
                        _quote(opcode),
                        _format_int(imm4),
                        _format_int(rd),
                        _format_int(initial),
                        _format_int(expected_rd),
                        _format_int(expected_flags),
                        _quote(f'{opcode} topology imm={imm4} rd=R{rd}'),
                    ],
                ))

    return rows


def _generate_ldi_cases() -> list[str]:
    rows: list[str] = []

    semantic_cases = [
        (0, 0x00, 1, 0xFFFFFFFFFFFFFFFF, 0x0, 'LDI #0 clears register'),
        (0, 0x01, 1, 0xFFFF, 0x0, 'LDI #1 replaces register'),
        (0, 0xFF, 1, 0x0, 0x0, 'LDI #255 max immediate'),
        (0, 0x42, 1, 0xDEAD, 0x0, 'LDI #0x42 replaces old value'),
        (1, 0xAB, 1, 0x0, 0x0, 'LDI.S1 OR into byte 1'),
        (1, 0xAB, 1, 0x55, 0x0, 'LDI.S1 preserves low byte'),
        (1, 0xAB, 1, 0xFF00, 0x0, 'LDI.S1 OR semantics'),
        (2, 0xCD, 1, 0x0, 0x0, 'LDI.S2 OR into byte 2'),
        (2, 0xCD, 1, 0x1234, 0x0, 'LDI.S2 preserves low bytes'),
        (3, 0x7F, 1, 0x0, 0x0, 'LDI.S3 positive no sign extend'),
        (3, 0x80, 1, 0x0, 0x0, 'LDI.S3 sign extends 0x80'),
        (3, 0x80, 1, 0x1234, 0x0, 'LDI.S3 sign extend preserves low bytes'),
        (3, 0xFF, 1, 0x0, 0x0, 'LDI.S3 sign extends 0xFF'),
        (0, 0x00, 3, 0x0, 0x0, 'LDI does not set flags when clear'),
        (0, 0x2A, 3, 0x0, 0x2, 'LDI preserves carry flag'),
    ]

    for shift, imm8, rd, initial, initial_flags, description in semantic_cases:
        expected_rd = _eval_ldi(shift, imm8, initial)
        rows.append(_format_macro(
            'LITTLE64_LDI_CASE',
            [
                _format_int(shift),
                _format_int(imm8),
                _format_int(rd),
                _format_int(initial),
                _format_int(expected_rd),
                _format_int(initial_flags),
                _format_int(initial_flags),
                _quote(description),
            ],
        ))

    for shift in range(4):
        initial = LDI_FULL_SWEEP_INITIALS[shift]
        initial_flags = 0x5
        for imm8 in range(256):
            expected_rd = _eval_ldi(shift, imm8, initial)
            rows.append(_format_macro(
                'LITTLE64_LDI_CASE',
                [
                    _format_int(shift),
                    _format_int(imm8),
                    '1',
                    _format_int(initial),
                    _format_int(expected_rd),
                    _format_int(initial_flags),
                    _format_int(initial_flags),
                    _quote(f'LDI full sweep shift={shift} imm=0x{imm8:02X} rd=R1'),
                ],
            ))

    topology_cases = [
        (0, 0x42, 0xDEAD_BEEF, 0x3, 'overwrite'),
        (1, 0xAB, 0x55, 0x3, 'byte1 OR'),
        (2, 0xCD, 0x1234, 0x3, 'byte2 OR'),
        (3, 0x80, 0x123456, 0x3, 'sign extend'),
    ]
    for rd in LDI_TOPOLOGY_REGS:
        for shift, imm8, requested_initial, initial_flags, description_suffix in topology_cases:
            initial = _seed_value(rd, requested_initial)
            expected_rd = _eval_ldi(shift, imm8, initial)
            rows.append(_format_macro(
                'LITTLE64_LDI_CASE',
                [
                    _format_int(shift),
                    _format_int(imm8),
                    _format_int(rd),
                    _format_int(initial),
                    _format_int(expected_rd),
                    _format_int(initial_flags),
                    _format_int(initial_flags),
                    _quote(f'LDI topology shift={shift} rd=R{rd} {description_suffix}'),
                ],
            ))

    return rows


def _render_file(header_lines: list[str], rows: list[str]) -> str:
    return '\n'.join(header_lines + [''] + rows) + '\n'


def _write_if_changed(path: Path, content: str, *, check: bool) -> bool:
    current = path.read_text(encoding='utf-8') if path.exists() else None
    if current == content:
        return False
    if check:
        print(f'stale generated instruction cases: {path}')
        return True
    path.write_text(content, encoding='utf-8')
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate shared Little64 GP/LDI instruction-case files.')
    parser.add_argument('--check', action='store_true', help='Fail if generated files are stale instead of rewriting them.')
    args = parser.parse_args()

    _validate_gp_opcode_metadata()

    gp_rows = _generate_gp_rr_cases() + [''] + _generate_gp_imm_cases()
    ldi_rows = _generate_ldi_cases()

    gp_content = _render_file(
        [
            '// Generated by tests/shared/generate_instruction_cases.py.',
            '// Shared by host and HDL GP instruction tests.',
        ],
        gp_rows,
    )
    ldi_content = _render_file(
        [
            '// Generated by tests/shared/generate_instruction_cases.py.',
            '// Shared by host and HDL LDI instruction tests.',
        ],
        ldi_rows,
    )

    changed = False
    changed |= _write_if_changed(GP_CASES_PATH, gp_content, check=args.check)
    changed |= _write_if_changed(LDI_CASES_PATH, ldi_content, check=args.check)
    return 1 if args.check and changed else 0


if __name__ == '__main__':
    raise SystemExit(main())