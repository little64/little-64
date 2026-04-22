from __future__ import annotations

import pytest

from shared_program import (
    ProgramExecution,
    encode_gp_imm,
    encode_gp_rr,
    encode_ldi,
    load_gp_imm_cases,
    load_gp_two_reg_cases,
    load_ldi_cases,
    run_batched_program_words,
)


pytestmark = pytest.mark.core_capabilities('shared-architecture')


POST_SINGLE_INSTRUCTION_PC = 4
CHUNK_SIZE = 64
GP_TWO_REG_CASES = load_gp_two_reg_cases()
GP_IMM_CASES = load_gp_imm_cases()
LDI_CASES = load_ldi_cases()

_CHUNK_RESULT_CACHE: dict[tuple[str, str, int], list[dict[str, object]]] = {}


def _build_two_reg_initial_registers(case) -> dict[int, int]:
    if case.rs1 == case.rd:
        assert case.rs1_value == case.rd_value, f'alias case must use one seed value: {case.description}'
        return {} if case.rd == 0 else {case.rd: case.rd_value}

    registers: dict[int, int] = {}
    if case.rs1 != 0:
        registers[case.rs1] = case.rs1_value
    if case.rd != 0:
        registers[case.rd] = case.rd_value
    return registers


def _assert_no_special_state_clobber(observed) -> None:
    assert observed['trap_cause'] == 0
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_pc'] == 0
    assert observed['trap_aux'] == 0
    assert observed['data_memory'] == {}
    assert observed['special_registers'] == {
        'cpu_control': 0,
        'interrupt_table_base': 0,
        'interrupt_mask': 0,
        'interrupt_mask_high': 0,
        'interrupt_states': 0,
        'interrupt_states_high': 0,
        'interrupt_epc': 0,
        'interrupt_eflags': 0,
        'interrupt_cpu_control': 0,
    }


def _chunk_case_params(cases, group_prefix: str) -> list[pytest.ParameterSet]:
    return [
        pytest.param(
            case_index,
            case_index // CHUNK_SIZE,
            id=case.description,
            marks=pytest.mark.xdist_group(f'{group_prefix}-{case_index // CHUNK_SIZE}'),
        )
        for case_index, case in enumerate(cases)
    ]


def _chunk_cases(cases, chunk_index: int):
    start = chunk_index * CHUNK_SIZE
    return cases[start:start + CHUNK_SIZE]


def _get_chunk_results(kind: str, chunk_index: int, shared_core_config, cases, build_execution) -> list[dict[str, object]]:
    cache_key = (kind, shared_core_config.core_variant, chunk_index)
    cached = _CHUNK_RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    chunk_cases = _chunk_cases(cases, chunk_index)
    observed_results = run_batched_program_words(
        [build_execution(case) for case in chunk_cases],
        config=shared_core_config,
    )
    _CHUNK_RESULT_CACHE[cache_key] = observed_results
    return observed_results


def _assert_single_instruction_case(case, observed) -> list[str]:
    failures: list[str] = []

    if observed['locked_up'] != 0:
        failures.append(f'{case.description}: expected locked_up=0, got {observed["locked_up"]}')
    if observed['halted'] != 1:
        failures.append(f'{case.description}: expected halted=1, got {observed["halted"]}')
    expected_rd = 0 if case.rd == 0 else case.expected_rd
    if observed['registers'][case.rd] != expected_rd:
        failures.append(
            f'{case.description}: R{case.rd} expected {expected_rd:#x}, got {observed["registers"][case.rd]:#x}'
        )
    if (observed['flags'] & 0x7) != case.expected_flags:
        failures.append(
            f'{case.description}: flags expected {case.expected_flags:#x}, got {(observed["flags"] & 0x7):#x}'
        )

    for register_index in range(16):
        expected_value = 0
        if register_index == case.rd and register_index != 0:
            expected_value = case.expected_rd
        elif hasattr(case, 'rs1') and register_index == case.rs1 and case.rs1 != case.rd:
            expected_value = case.rs1_value
        elif register_index == 15:
            expected_value = POST_SINGLE_INSTRUCTION_PC
        if observed['registers'][register_index] != expected_value:
            failures.append(
                f'{case.description}: R{register_index} expected {expected_value:#x}, got {observed["registers"][register_index]:#x}'
            )

    try:
        _assert_no_special_state_clobber(observed)
    except AssertionError as exc:
        failures.append(f'{case.description}: {exc}')

    return failures


@pytest.mark.parametrize(('case_index', 'chunk_index'), _chunk_case_params(GP_TWO_REG_CASES, 'shared-isa-gp-two-reg'))
def test_shared_gp_two_reg_cases(case_index: int, chunk_index: int, shared_core_config) -> None:
    observed_results = _get_chunk_results(
        'gp-two-reg',
        chunk_index,
        shared_core_config,
        GP_TWO_REG_CASES,
        lambda case: ProgramExecution(
            words=[encode_gp_rr(case.opcode_name, case.rs1, case.rd), encode_gp_imm('STOP', 0, 0)],
            initial_registers=_build_two_reg_initial_registers(case),
            max_cycles=20,
        ),
    )
    case = GP_TWO_REG_CASES[case_index]
    failures = _assert_single_instruction_case(case, observed_results[case_index % CHUNK_SIZE])
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize(('case_index', 'chunk_index'), _chunk_case_params(GP_IMM_CASES, 'shared-isa-gp-imm'))
def test_shared_gp_imm_cases(case_index: int, chunk_index: int, shared_core_config) -> None:
    observed_results = _get_chunk_results(
        'gp-imm',
        chunk_index,
        shared_core_config,
        GP_IMM_CASES,
        lambda case: ProgramExecution(
            words=[encode_gp_imm(case.opcode_name, case.imm4, case.rd), encode_gp_imm('STOP', 0, 0)],
            initial_registers={} if case.rd == 0 else {case.rd: case.initial},
            max_cycles=20,
        ),
    )
    case = GP_IMM_CASES[case_index]
    failures = _assert_single_instruction_case(case, observed_results[case_index % CHUNK_SIZE])
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize(('case_index', 'chunk_index'), _chunk_case_params(LDI_CASES, 'shared-isa-ldi'))
def test_shared_ldi_cases(case_index: int, chunk_index: int, shared_core_config) -> None:
    observed_results = _get_chunk_results(
        'ldi',
        chunk_index,
        shared_core_config,
        LDI_CASES,
        lambda case: ProgramExecution(
            words=[encode_ldi(case.shift, case.imm8, case.rd), encode_gp_imm('STOP', 0, 0)],
            initial_registers={} if case.rd == 0 else {case.rd: case.initial},
            initial_flags=case.initial_flags,
            max_cycles=20,
        ),
    )
    case = LDI_CASES[case_index]
    failures = _assert_single_instruction_case(case, observed_results[case_index % CHUNK_SIZE])
    assert not failures, '\n'.join(failures)