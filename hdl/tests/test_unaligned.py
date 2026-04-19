"""Tests for unaligned memory accesses on the Little-64 HDL core.

The ISA permits loads and stores at any byte alignment.  When an access
crosses a 64-bit word boundary the core must issue two Wishbone beats
(split access) transparently.

Every width × byte-offset combination is exercised for both loads and
stores, including offsets that force a split access.
"""
from __future__ import annotations

import pytest

from shared_program import (
    encode_gp_imm,
    encode_ls_reg,
    run_program_words,
    run_program_source,
)


# ──── helpers ────────────────────────────────────────────────────────────

def _bytes_of(value: int, width: int) -> dict[int, int]:
    """Return {byte_offset: byte_value} for the low *width* bytes of *value*."""
    return {i: (value >> (8 * i)) & 0xFF for i in range(width)}


def _width_for_opcode(opcode: str) -> int:
    return {'BYTE_LOAD': 1, 'BYTE_STORE': 1,
            'SHORT_LOAD': 2, 'SHORT_STORE': 2,
            'WORD_LOAD': 4, 'WORD_STORE': 4,
            'LOAD': 8, 'STORE': 8}[opcode]


_LOAD_OPCODES = ['BYTE_LOAD', 'SHORT_LOAD', 'WORD_LOAD', 'LOAD']
_STORE_OPCODES = ['BYTE_STORE', 'SHORT_STORE', 'WORD_STORE', 'STORE']

_TEST_VALUES = {
    1: 0xAB,
    2: 0xBEEF,
    4: 0xDEAD_BEEF,
    8: 0x1122_3344_5566_7788,
}


def _load_cases():
    """Generate (opcode, base_addr, value) tuples covering every offset."""
    for opcode in _LOAD_OPCODES:
        width = _width_for_opcode(opcode)
        value = _TEST_VALUES[width]
        for offset in range(8):
            addr = 0x1000 + offset
            yield pytest.param(opcode, addr, value, width,
                               id=f'{opcode}-off{offset}')


def _store_cases():
    for opcode in _STORE_OPCODES:
        width = _width_for_opcode(opcode)
        value = _TEST_VALUES[width]
        for offset in range(8):
            addr = 0x1000 + offset
            yield pytest.param(opcode, addr, value, width,
                               id=f'{opcode}-off{offset}')


# ──── load tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(('opcode', 'addr', 'value', 'width'), list(_load_cases()))
def test_unaligned_load(opcode: str, addr: int, value: int, width: int, shared_core_config) -> None:
    """Load *width* bytes from *addr* and verify the result in R1."""
    data_mem = {addr + i: b for i, b in _bytes_of(value, width).items()}
    observed = run_program_source(
        f'{opcode} [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={2: addr},
        initial_data_memory=data_mem,
        max_cycles=64,
    )

    assert observed['locked_up'] == 0, f'locked up for {opcode} at offset {addr & 7}'
    assert observed['halted'] == 1
    assert observed['registers'][1] == value, (
        f'{opcode} at offset {addr & 7}: expected {value:#x}, got {observed["registers"][1]:#x}')


# ──── store tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize(('opcode', 'addr', 'value', 'width'), list(_store_cases()))
def test_unaligned_store(opcode: str, addr: int, value: int, width: int, shared_core_config) -> None:
    """Store *width* bytes to *addr* and verify memory contents."""
    observed = run_program_source(
        f'{opcode} [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 2: addr},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0, f'locked up for {opcode} at offset {addr & 7}'
    assert observed['halted'] == 1
    mem = observed['data_memory']
    for i in range(width):
        expected_byte = (value >> (8 * i)) & 0xFF
        actual_byte = mem.get(addr + i, 0)
        assert actual_byte == expected_byte, (
            f'{opcode} at offset {addr & 7}: byte {i} expected {expected_byte:#x}, got {actual_byte:#x}')


# ──── round-trip tests ───────────────────────────────────────────────────

@pytest.mark.parametrize('offset', range(8), ids=[f'off{i}' for i in range(8)])
def test_unaligned_qword_store_then_load_roundtrip(offset: int, shared_core_config) -> None:
    """Store a qword at an unaligned address, then load it back."""
    addr = 0x1000 + offset
    value = 0xCAFE_BABE_DEAD_BEEF
    observed = run_program_source(
        'STORE [R2], R1\nLOAD [R2], R3\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 2: addr},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == value, (
        f'round-trip at offset {offset}: expected {value:#x}, got {observed["registers"][3]:#x}')


@pytest.mark.parametrize('offset', range(8), ids=[f'off{i}' for i in range(8)])
def test_unaligned_word_store_then_load_roundtrip(offset: int, shared_core_config) -> None:
    """Store a 32-bit word at an unaligned address, then load it back."""
    addr = 0x1000 + offset
    value = 0xDEAD_BEEF
    observed = run_program_source(
        'WORD_STORE [R2], R1\nWORD_LOAD [R2], R3\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 2: addr},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == value


@pytest.mark.parametrize('offset', range(8), ids=[f'off{i}' for i in range(8)])
def test_unaligned_short_store_then_load_roundtrip(offset: int, shared_core_config) -> None:
    """Store a 16-bit short at an unaligned address, then load it back."""
    addr = 0x1000 + offset
    value = 0xBEEF
    observed = run_program_source(
        'SHORT_STORE [R2], R1\nSHORT_LOAD [R2], R3\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 2: addr},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == value


# ──── boundary crossing validation ───────────────────────────────────────

def test_qword_load_at_offset7_crosses_boundary(shared_core_config) -> None:
    """A LOAD at byte offset 7 must split: 1 byte from word N, 7 from word N+1."""
    addr = 0x1007
    value = 0x0102_0304_0506_0708
    data_mem = {addr + i: b for i, b in _bytes_of(value, 8).items()}
    observed = run_program_source(
        'LOAD [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={2: addr},
        initial_data_memory=data_mem,
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == value


def test_qword_store_at_offset7_crosses_boundary(shared_core_config) -> None:
    """A STORE at byte offset 7 must split across two Wishbone words."""
    addr = 0x1007
    value = 0x0102_0304_0506_0708
    observed = run_program_source(
        'STORE [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 2: addr},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    mem = observed['data_memory']
    for i in range(8):
        assert mem.get(addr + i, 0) == (value >> (8 * i)) & 0xFF


def test_word_load_at_offset6_crosses_boundary(shared_core_config) -> None:
    """A WORD_LOAD at offset 6 reads 2 bytes from word N and 2 from word N+1."""
    addr = 0x1006
    value = 0xDEAD_BEEF
    data_mem = {addr + i: b for i, b in _bytes_of(value, 4).items()}
    observed = run_program_source(
        'WORD_LOAD [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={2: addr},
        initial_data_memory=data_mem,
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == value


def test_short_load_at_offset7_crosses_boundary(shared_core_config) -> None:
    """A SHORT_LOAD at offset 7 reads 1 byte from word N and 1 from word N+1."""
    addr = 0x1007
    value = 0xBEEF
    data_mem = {addr + i: b for i, b in _bytes_of(value, 2).items()}
    observed = run_program_source(
        'SHORT_LOAD [R2], R1\nSTOP',
        config=shared_core_config,
        initial_registers={2: addr},
        initial_data_memory=data_mem,
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == value


# ──── push/pop unaligned stack ───────────────────────────────────────────

@pytest.mark.parametrize('offset', range(8), ids=[f'off{i}' for i in range(8)])
def test_push_pop_with_unaligned_stack(offset: int, shared_core_config) -> None:
    """PUSH/POP should work with any stack alignment."""
    sp = 0x2000 + offset
    value = 0xCAFE_BABE_DEAD_BEEF
    observed = run_program_source(
        'PUSH R1, R13\nPOP R3, R13\nSTOP',
        config=shared_core_config,
        initial_registers={1: value, 13: sp},
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == value
    assert observed['registers'][13] == sp
