from __future__ import annotations

from little64_cores.config import Little64CoreConfig
from shared_program import run_program_source


V3_CONFIG = Little64CoreConfig(core_variant='v3', reset_vector=0)


def test_v3_straight_line_gp_pipeline_executes_back_to_back_dependencies() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #5, R1',
            'ADD R1, R1',
            'ADD R1, R1',
            'STOP',
        ]),
        config=V3_CONFIG,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 20
    assert observed['registers'][15] == 8
    assert observed['commit_count'] == 3


def test_v3_forwards_flags_into_following_conditional_branch() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #1, R1',
            'LDI #1, R2',
            'SUB R1, R2',
            'JUMP.Z @done',
            'LDI #0x7f, R3',
            'done:',
            'STOP',
        ]),
        config=V3_CONFIG,
        max_cycles=40,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0
    assert observed['flags'] & 0x1 == 1


def test_v3_redirects_unconditional_jump_and_squashes_younger_fetch() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #1, R1',
            'JUMP @target',
            'LDI #0xff, R2',
            'target:',
            'LDI #0x12, R2',
            'STOP',
        ]),
        config=V3_CONFIG,
        max_cycles=40,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][2] == 0x12


def test_v3_handles_split_store_load_roundtrip() -> None:
    observed = run_program_source(
        'STORE [R2], R1\nLOAD [R2], R3\nSTOP',
        config=V3_CONFIG,
        initial_registers={1: 0xCAFE_BABE_DEAD_BEEF, 2: 0x1007},
        max_cycles=96,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0xCAFE_BABE_DEAD_BEEF


def test_v3_pop_same_register_matches_emulator_alias_semantics() -> None:
    observed = run_program_source(
        'POP R13, R13\nSTOP',
        config=V3_CONFIG,
        initial_registers={13: 0x2000},
        initial_data_memory={
            0x2000 + 0: 0x00,
            0x2000 + 1: 0x10,
        },
        max_cycles=96,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][13] == 0x1008


def test_v3_pc_relative_push_reads_then_pushes_loaded_value() -> None:
    observed = run_program_source(
        'PUSH @2, R13\nSTOP',
        config=V3_CONFIG,
        initial_registers={13: 0x2000},
        initial_data_memory={
            6 + 0: 0xEF,
            6 + 1: 0xCD,
            6 + 2: 0xAB,
            6 + 3: 0x89,
            6 + 4: 0x67,
            6 + 5: 0x45,
            6 + 6: 0x23,
            6 + 7: 0x01,
        },
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][13] == 0x1FF8
    assert observed['data_memory'][0x1FF8] == 0xEF
    assert observed['data_memory'][0x1FFF] == 0x01