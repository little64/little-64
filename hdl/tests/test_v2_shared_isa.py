from __future__ import annotations

import pytest

from little64_cores.config import Little64CoreConfig
from shared_program import (
    encode_gp_imm,
    encode_gp_rr,
    encode_ldi,
    load_gp_imm_cases,
    load_gp_two_reg_cases,
    load_ldi_cases,
    run_single_instruction,
)


POST_SINGLE_INSTRUCTION_PC = 4
V2_CONFIG = Little64CoreConfig(core_variant='v2', reset_vector=0)


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


@pytest.mark.parametrize('case', load_gp_two_reg_cases(), ids=lambda case: case.description)
def test_v2_shared_gp_two_reg_cases(case) -> None:
    observed = run_single_instruction(
        encode_gp_rr(case.opcode_name, case.rs1, case.rd),
        config=V2_CONFIG,
        initial_registers=_build_two_reg_initial_registers(case),
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == (0 if case.rd == 0 else case.expected_rd)
    assert observed['flags'] & 0x7 == case.expected_flags
    for register_index in range(16):
        expected_value = 0
        if register_index == case.rd and register_index != 0:
            expected_value = case.expected_rd
        elif register_index == case.rs1 and case.rs1 != case.rd:
            expected_value = case.rs1_value
        elif register_index == 15:
            expected_value = POST_SINGLE_INSTRUCTION_PC
        assert observed['registers'][register_index] == expected_value
    _assert_no_special_state_clobber(observed)


@pytest.mark.parametrize('case', load_gp_imm_cases(), ids=lambda case: case.description)
def test_v2_shared_gp_imm_cases(case) -> None:
    observed = run_single_instruction(
        encode_gp_imm(case.opcode_name, case.imm4, case.rd),
        config=V2_CONFIG,
        initial_registers={} if case.rd == 0 else {case.rd: case.initial},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == (0 if case.rd == 0 else case.expected_rd)
    assert observed['flags'] & 0x7 == case.expected_flags
    for register_index in range(16):
        expected_value = 0
        if register_index == case.rd and register_index != 0:
            expected_value = case.expected_rd
        elif register_index == 15:
            expected_value = POST_SINGLE_INSTRUCTION_PC
        assert observed['registers'][register_index] == expected_value
    _assert_no_special_state_clobber(observed)


@pytest.mark.parametrize('case', load_ldi_cases(), ids=lambda case: case.description)
def test_v2_shared_ldi_cases(case) -> None:
    observed = run_single_instruction(
        encode_ldi(case.shift, case.imm8, case.rd),
        config=V2_CONFIG,
        initial_registers={} if case.rd == 0 else {case.rd: case.initial},
        initial_flags=case.initial_flags,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == (0 if case.rd == 0 else case.expected_rd)
    assert observed['flags'] & 0x7 == case.expected_flags
    for register_index in range(16):
        expected_value = 0
        if register_index == case.rd and register_index != 0:
            expected_value = case.expected_rd
        elif register_index == 15:
            expected_value = POST_SINGLE_INSTRUCTION_PC
        assert observed['registers'][register_index] == expected_value
    _assert_no_special_state_clobber(observed)