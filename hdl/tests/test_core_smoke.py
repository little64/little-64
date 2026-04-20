from __future__ import annotations

from dataclasses import replace

from little64.isa import CPU_CONTROL_PAGING_ENABLE, CPU_CONTROL_USER_MODE, TrapVector
from shared_program import assemble_source, run_program_source


def test_core_fetches_ldi_then_stops(shared_core_config) -> None:
    observed = run_program_source('LDI #0x12, R1\nSTOP', config=shared_core_config, max_cycles=16)

    assert observed['registers'][1] == 0x12
    assert observed['registers'][0] == 0
    assert observed['halted'] == 1


def test_core_round_trips_special_registers_via_lsr_and_ssr(shared_core_config) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #17, R2',
            'LDI #0x5A, R1',
            'LDI.S1 #0xA5, R1',
            'SSR R2, R1',
            'LSR R2, R3',
            'STOP',
        ]),
        config=shared_core_config,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0xA55A
    assert observed['trap_cause'] == 0


def test_core_allows_user_thread_pointer_access_via_lsr(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    handler_words = assemble_source('STOP')
    observed = run_program_source(
        '\n'.join([
            'LDI.S1 #0x80, R2',
            'LSR R2, R1',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={
            'cpu_control': CPU_CONTROL_USER_MODE,
            'thread_pointer': 0x1234_5678_9ABC_DEF0,
            'interrupt_table_base': vector_base,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory={
            vector_base + 16 + byte_index: (handler_addr >> (8 * byte_index)) & 0xFF
            for byte_index in range(8)
        },
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x1234_5678_9ABC_DEF0


def test_core_traps_user_supervisor_bank_lsr(shared_core_config) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0, R2',
            'LSR R2, R1',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 2
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_aux'] == 0
    assert observed['registers'][1] == 0


def test_core_traps_user_supervisor_bank_ssr(shared_core_config) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0, R2',
            'LDI #0x34, R1',
            'LDI.S1 #0x12, R1',
            'SSR R2, R1',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 6
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_aux'] == 0
    assert observed['registers'][1] == 0x1234


def test_core_locks_up_when_paging_is_enabled_without_mmu_support(shared_core_config) -> None:
    observed = run_program_source(
        'STOP',
        config=replace(shared_core_config, enable_mmu=False),
        initial_special_registers={'cpu_control': CPU_CONTROL_PAGING_ENABLE},
        max_cycles=16,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1


def test_commit_valid_pulses_for_each_instruction(shared_core_config, shared_core_variant) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #42, R1',
            'LDI #7, R2',
            'ADD R1, R2',
            'STOP',
        ]),
        config=shared_core_config,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == (4 if shared_core_variant == 'basic' else 3)


def test_commit_valid_pulses_for_memory_instructions(shared_core_config, shared_core_variant) -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0x10, R2',
            'LDI.S1 #0x10, R2',
            'LDI #0xAB, R1',
            'STORE [R2], R1',
            'LOAD [R2], R3',
            'STOP',
        ]),
        config=shared_core_config,
        max_cycles=48,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == (6 if shared_core_variant == 'basic' else 5)
