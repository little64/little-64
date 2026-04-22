from __future__ import annotations

import pytest

from shared_program import load_jump_program_cases, load_memory_program_cases, run_program_source


pytestmark = pytest.mark.core_capabilities('shared-architecture')


def _u64_bytes(value: int) -> dict[int, int]:
    return {byte_index: (value >> (8 * byte_index)) & 0xFF for byte_index in range(8)}


def _assert_case(case, shared_core_config) -> None:
    observed = run_program_source(case.source, config=shared_core_config)
    assert observed['locked_up'] == 0
    assert observed['halted'] == 1

    if case.reg_a >= 0:
        assert observed['registers'][case.reg_a] == case.value_a
    if case.reg_b >= 0:
        assert observed['registers'][case.reg_b] == case.value_b
    if case.reg_c >= 0:
        assert observed['registers'][case.reg_c] == case.value_c


@pytest.mark.parametrize('case', load_jump_program_cases(), ids=lambda case: case.description)
def test_shared_jump_program_cases(case, shared_core_config) -> None:
    _assert_case(case, shared_core_config)


@pytest.mark.parametrize('case', load_memory_program_cases(), ids=lambda case: case.description)
def test_shared_memory_program_cases(case, shared_core_config) -> None:
    _assert_case(case, shared_core_config)


def test_push_and_pop_preserve_flags_and_stack_value(shared_core_config) -> None:
    observed = run_program_source(
        'PUSH R1, R13\nPOP R2, R13\nSTOP',
        config=shared_core_config,
        initial_registers={1: 0x1122_3344_5566_7788, 13: 0x2000},
        initial_flags=0x7,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][2] == 0x1122_3344_5566_7788
    assert observed['registers'][13] == 0x2000
    assert observed['flags'] == 0x7
    assert observed['data_memory'][0x1FF8] == 0x88
    assert observed['data_memory'][0x1FFF] == 0x11


def test_push_r0_writes_zero_and_preserves_r0(shared_core_config) -> None:
    observed = run_program_source(
        'PUSH R0, R13\nLOAD [R13], R2\nSTOP',
        config=shared_core_config,
        initial_registers={13: 0x2000},
        initial_flags=0x5,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][0] == 0
    assert observed['registers'][2] == 0
    assert observed['registers'][13] == 0x1FF8
    assert observed['flags'] == 0x5


def test_pop_into_r0_leaves_r0_zero_and_increments_stack_pointer(shared_core_config) -> None:
    observed = run_program_source(
        'POP R0, R13\nSTOP',
        config=shared_core_config,
        initial_registers={13: 0x2000},
        initial_data_memory={0x2000 + offset: byte for offset, byte in _u64_bytes(0xCAFE_BABE_DEAD_BEEF).items()},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][0] == 0
    assert observed['registers'][13] == 0x2008


def test_pop_same_register_matches_emulator_alias_semantics(shared_core_config) -> None:
    observed = run_program_source(
        'POP R13, R13\nSTOP',
        config=shared_core_config,
        initial_registers={13: 0x2000},
        initial_data_memory={0x2000 + offset: byte for offset, byte in _u64_bytes(0x1000).items()},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][13] == 0x1008


@pytest.mark.parametrize(
    ('opcode', 'value', 'expected'),
    [
        ('LOAD', 0x1122_3344_5566_7788, 0x1122_3344_5566_7788),
        ('BYTE_LOAD', 0xAB, 0xAB),
        ('SHORT_LOAD', 0xBEEF, 0xBEEF),
        ('WORD_LOAD', 0xDEAD_BEEF, 0xDEAD_BEEF),
    ],
)
def test_pc_relative_load_variants_use_post_increment_pc(opcode: str, value: int, expected: int, shared_core_config) -> None:
    observed = run_program_source(
        f'{opcode} @2, R1\nMOVE @1, R2\nSTOP',
        config=shared_core_config,
        initial_data_memory={6 + offset: byte for offset, byte in _u64_bytes(value).items()},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == expected
    assert observed['registers'][2] == 6


@pytest.mark.parametrize(
    ('opcode', 'value', 'expected_bytes'),
    [
        ('STORE', 0x1122_3344_5566_7788, _u64_bytes(0x1122_3344_5566_7788)),
        ('BYTE_STORE', 0xAB, {0: 0xAB}),
        ('SHORT_STORE', 0xBEEF, {0: 0xEF, 1: 0xBE}),
        ('WORD_STORE', 0xDEAD_BEEF, {0: 0xEF, 1: 0xBE, 2: 0xAD, 3: 0xDE}),
    ],
)
def test_pc_relative_store_variants_write_effective_address(opcode: str, value: int, expected_bytes: dict[int, int], shared_core_config) -> None:
    observed = run_program_source(
        f'{opcode} @2, R1\nSTOP',
        config=shared_core_config,
        initial_registers={1: value},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    for offset, byte in expected_bytes.items():
        assert observed['data_memory'][6 + offset] == byte


def test_pc_relative_push_reads_memory_then_pushes_to_stack(shared_core_config) -> None:
    observed = run_program_source(
        'PUSH @2, R13\nSTOP',
        config=shared_core_config,
        initial_registers={13: 0x2000},
        initial_data_memory={6 + offset: byte for offset, byte in _u64_bytes(0xCAFE_BABE_DEAD_BEEF).items()},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][13] == 0x1FF8
    assert observed['data_memory'][0x1FF8] == 0xEF
    assert observed['data_memory'][0x1FFF] == 0xCA


def test_pc_relative_pop_writes_popped_value_to_effective_address(shared_core_config) -> None:
    observed = run_program_source(
        'POP @2, R13\nSTOP',
        config=shared_core_config,
        initial_registers={13: 0x2000},
        initial_data_memory={
            **{0x2000 + offset: byte for offset, byte in _u64_bytes(0x0123_4567_89AB_CDEF).items()},
        },
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][13] == 0x2008
    assert observed['data_memory'][6] == 0xEF
    assert observed['data_memory'][13] == 0x01
