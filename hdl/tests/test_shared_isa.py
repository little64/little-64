from __future__ import annotations

import pytest

from shared_program import (
    encode_gp_imm,
    encode_gp_rr,
    encode_ldi,
    load_gp_imm_cases,
    load_gp_two_reg_cases,
    load_ldi_cases,
    run_single_instruction,
)


@pytest.mark.parametrize('case', load_gp_two_reg_cases(), ids=lambda case: case.description)
def test_shared_gp_two_reg_cases(case) -> None:
    observed = run_single_instruction(
        encode_gp_rr(case.opcode_name, case.rs1, case.rd),
        initial_registers={case.rs1: case.rs1_value, case.rd: case.rd_value},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == case.expected_rd
    assert observed['flags'] & 0x7 == case.expected_flags


@pytest.mark.parametrize('case', load_gp_imm_cases(), ids=lambda case: case.description)
def test_shared_gp_imm_cases(case) -> None:
    observed = run_single_instruction(
        encode_gp_imm(case.opcode_name, case.imm4, case.rd),
        initial_registers={case.rd: case.initial},
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == case.expected_rd
    assert observed['flags'] & 0x7 == case.expected_flags


@pytest.mark.parametrize('case', load_ldi_cases(), ids=lambda case: case.description)
def test_shared_ldi_cases(case) -> None:
    observed = run_single_instruction(
        encode_ldi(case.shift, case.imm8, case.rd),
        initial_registers={case.rd: case.initial},
        initial_flags=case.initial_flags,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][case.rd] == case.expected_rd
    assert observed['flags'] & 0x7 == case.expected_flags