from __future__ import annotations

import pytest

from little64_cores.config import Little64CoreConfig
from little64_cores.isa import CPU_CONTROL_PAGING_ENABLE, CPU_CONTROL_USER_MODE, TrapVector
from shared_program import assemble_source, run_program_source, run_program_words
from test_traps import (
    AUX_CANONICAL,
    AUX_NO_VALID_PTE,
    AUX_PERMISSION,
    _aux_code,
    _build_mapping,
    _vector_entry,
)


NON_DEFAULT_CACHE_TOPOLOGIES = ('unified', 'split')


def _v2_config(cache_topology: str = 'none') -> Little64CoreConfig:
    return Little64CoreConfig(core_variant='v2', cache_topology=cache_topology)


@pytest.mark.parametrize('cache_topology', NON_DEFAULT_CACHE_TOPOLOGIES)
def test_v2_noncanonical_fetch_raises_canonical_page_fault(cache_topology: str) -> None:
    noncanonical_pc = 0x0000_0080_0000_0000

    observed = run_program_words(
        [],
        config=_v2_config(cache_topology),
        initial_registers={15: noncanonical_pc},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': 0x4000,
        },
        max_cycles=64,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_CANONICAL
    assert observed['trap_fault_addr'] == noncanonical_pc
    assert observed['trap_access'] == 2
    assert observed['trap_pc'] == noncanonical_pc
    assert observed['trap_aux'] == _aux_code(AUX_CANONICAL, 2)


@pytest.mark.parametrize('cache_topology', NON_DEFAULT_CACHE_TOPOLOGIES)
def test_v2_user_syscall_fetches_paged_interrupt_vector_in_supervisor_mode(cache_topology: str) -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000
    program_pa = 0x0
    vector_base_va = 0xFFFF_FFC0_0000_7000
    vector_base_pa = 0x7000
    handler_va = 0xFFFF_FFC0_0000_8000
    handler_pa = 0x8000
    trap_vector = TrapVector.SYSCALL

    program_words = assemble_source('SYSCALL')
    handler_words = assemble_source('STOP')
    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=program_va, pa=program_pa, r=True, w=False, x=True, user=True)
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=vector_base_va, pa=vector_base_pa, r=True, w=False, x=False, user=False)
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=handler_va, pa=handler_pa, r=True, w=False, x=True, user=False)
    memory.update(_vector_entry(vector_base_pa, trap_vector, handler_va))

    observed = run_program_words(
        [],
        config=_v2_config(cache_topology),
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_USER_MODE | CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
            'interrupt_table_base': vector_base_va,
        },
        extra_code_words={
            **{program_pa + index * 2: word for index, word in enumerate(program_words)},
            **{handler_pa + index * 2: word for index, word in enumerate(handler_words)},
        },
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL
    assert observed['special_registers']['interrupt_cpu_control'] & CPU_CONTROL_USER_MODE
