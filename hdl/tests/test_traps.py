from __future__ import annotations

from pathlib import Path

import pytest

from little64_cores.isa import (
    CPU_CONTROL_CUR_INT_SHIFT,
    CPU_CONTROL_IN_INTERRUPT,
    CPU_CONTROL_PAGING_ENABLE,
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_USER_MODE,
    TrapVector,
)
from shared_program import assemble_source, encode_gp_imm, encode_gp_rr, encode_ls_reg, run_program_source, run_program_words


pytestmark = pytest.mark.core_capabilities('interrupts', 'mmu')


PTE_V = 1 << 0
PTE_R = 1 << 1
PTE_W = 1 << 2
PTE_X = 1 << 3
PTE_U = 1 << 4
AUX_NO_VALID_PTE = 1
AUX_INVALID_NONLEAF = 2
AUX_PERMISSION = 3
AUX_RESERVED = 4
AUX_CANONICAL = 5


def _encode_u64(value: int) -> dict[int, int]:
    return {byte_index: (value >> (8 * byte_index)) & 0xFF for byte_index in range(8)}


def _vector_entry(base: int, vector: int, handler: int) -> dict[int, int]:
    entry = base + (vector * 8)
    return {entry + offset: byte for offset, byte in _encode_u64(handler).items()}


def _table_pte(table_page: int) -> int:
    return ((table_page >> 12) << 10) | PTE_V


def _leaf_pte(phys_page: int, *, r: bool, w: bool, x: bool, user: bool = False) -> int:
    pte = ((phys_page >> 12) << 10) | PTE_V
    if r:
        pte |= PTE_R
    if w:
        pte |= PTE_W
    if x:
        pte |= PTE_X
    if user:
        pte |= PTE_U
    return pte


def _write_u64(memory: dict[int, int], addr: int, value: int) -> None:
    for offset, byte in _encode_u64(value).items():
        memory[addr + offset] = byte


def _aux_code(subtype: int, level: int) -> int:
    return (subtype & 0xF) | ((level & 0xFF) << 8)


def _build_mapping(memory: dict[int, int], *, root: int, l1: int, l0: int, va: int, pa: int,
                   r: bool, w: bool, x: bool, user: bool = False) -> None:
    _write_u64(memory, root + (((va >> 30) & 0x1FF) * 8), _table_pte(l1))
    _write_u64(memory, l1 + (((va >> 21) & 0x1FF) * 8), _table_pte(l0))
    _write_u64(memory, l0 + (((va >> 12) & 0x1FF) * 8), _leaf_pte(pa, r=r, w=w, x=x, user=user))


def test_supervisor_syscall_without_handler_locks_with_vector4(shared_core_config) -> None:
    observed = run_program_source('SYSCALL', config=shared_core_config, max_cycles=32)

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL_FROM_SUPERVISOR
    assert observed['trap_pc'] == 0


def test_invalid_gp_opcode_raises_invalid_instruction_trap(shared_core_config) -> None:
    reserved_gp_opcode = (0b110 << 13) | (5 << 8)

    observed = run_program_words([reserved_gp_opcode], config=shared_core_config, max_cycles=32)

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.INVALID_INSTRUCTION
    assert observed['trap_pc'] == 0
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_aux'] == 0


def test_load_into_r15_redirects_control_flow(shared_core_config) -> None:
    target = 0x20
    stop = encode_gp_imm('STOP', 0, 0)

    observed = run_program_words(
        [encode_ls_reg('LOAD', 0, 5, 15), stop],
        config=shared_core_config,
        initial_registers={5: 0x80},
        extra_code_words={target: stop},
        initial_data_memory={
            0x80 + byte_index: (target >> (8 * byte_index)) & 0xFF
            for byte_index in range(8)
        },
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][15] == target + 2


def test_ls_register_form_reads_r15_as_post_incremented_pc(shared_core_config) -> None:
    stop = encode_gp_imm('STOP', 0, 0)

    observed = run_program_words(
        [
            encode_ls_reg('MOVE', 2, 15, 14),
            encode_ls_reg('MOVE', 0, 14, 15),
            stop,
            stop,
        ],
        config=shared_core_config,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][14] == 0x6
    assert observed['registers'][15] == 0x8


def test_move_into_r15_reaches_higher_half_target_when_paging_enabled(shared_core_config) -> None:
    root = 0x4000
    l1_low = 0x5000
    l0_low = 0x6000
    l1_high = 0x7000
    l0_high = 0x8000
    high_target_va = 0xFFFF_FFC0_0000_0100
    stop = encode_gp_imm('STOP', 0, 0)

    memory: dict[int, int] = {}
    _write_u64(memory, root + (((0x0 >> 30) & 0x1FF) * 8), _table_pte(l1_low))
    _write_u64(memory, l1_low + (((0x0 >> 21) & 0x1FF) * 8), _table_pte(l0_low))
    _write_u64(memory, l0_low + (((0x0 >> 12) & 0x1FF) * 8), _leaf_pte(0x0, r=True, w=True, x=True))

    _write_u64(memory, root + (((high_target_va >> 30) & 0x1FF) * 8), _table_pte(l1_high))
    _write_u64(memory, l1_high + (((high_target_va >> 21) & 0x1FF) * 8), _table_pte(l0_high))
    _write_u64(memory, l0_high + (((high_target_va >> 12) & 0x1FF) * 8), _leaf_pte(0x100, r=True, w=True, x=True))

    observed = run_program_words(
        [encode_ls_reg('MOVE', 0, 3, 15), stop],
        config=shared_core_config,
        extra_code_words={0x100: stop},
        initial_registers={3: high_target_va, 15: 0},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=64,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][15] == high_target_va + 2


def test_l2_superpage_translation_preserves_non_aligned_phys_base(shared_core_config) -> None:
    root = 0x4000
    program_va = 0xFFFF_FFC0_0052_A100
    program_pa = 0x0062_A100
    stop = encode_gp_imm('STOP', 0, 0)

    memory: dict[int, int] = {}
    _write_u64(
        memory,
        root + (((program_va >> 30) & 0x1FF) * 8),
        _leaf_pte(0x0010_0000, r=True, w=True, x=True),
    )

    observed = run_program_words(
        [],
        config=shared_core_config,
        extra_code_words={program_pa: stop},
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][15] == program_va + 2


def test_noncanonical_fetch_raises_canonical_page_fault(shared_core_config) -> None:
    noncanonical_pc = 0x0000_0080_0000_0000

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: noncanonical_pc},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': 0x4000,
        },
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_CANONICAL
    assert observed['trap_fault_addr'] == noncanonical_pc
    assert observed['trap_access'] == 2
    assert observed['trap_pc'] == noncanonical_pc
    assert observed['trap_aux'] == _aux_code(AUX_CANONICAL, 2)


def test_missing_l2_pte_raises_not_present_page_fault(shared_core_config) -> None:
    root = 0x4000
    program_va = 0xFFFF_FFC0_0000_0000

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        max_cycles=48,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_NOT_PRESENT
    assert observed['trap_fault_addr'] == program_va
    assert observed['trap_access'] == 2
    assert observed['trap_pc'] == program_va
    assert observed['trap_aux'] == _aux_code(AUX_NO_VALID_PTE, 2)


def test_execute_without_x_permission_raises_permission_page_fault(shared_core_config) -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=program_va, pa=0x0, r=True, w=False, x=False, user=False)

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=48,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_PERMISSION
    assert observed['trap_fault_addr'] == program_va
    assert observed['trap_access'] == 2
    assert observed['trap_pc'] == program_va
    assert observed['trap_aux'] == _aux_code(AUX_PERMISSION, 0)


def test_reserved_pte_bits_raise_reserved_fault_subtype(shared_core_config) -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000

    memory: dict[int, int] = {}
    _write_u64(memory, root + (((program_va >> 30) & 0x1FF) * 8), _table_pte(l1))
    _write_u64(memory, l1 + (((program_va >> 21) & 0x1FF) * 8), _table_pte(l0))
    _write_u64(memory, l0 + (((program_va >> 12) & 0x1FF) * 8), _leaf_pte(0x0, r=True, w=False, x=True) | (1 << 60))

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=48,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_RESERVED
    assert observed['trap_fault_addr'] == program_va
    assert observed['trap_access'] == 2
    assert observed['trap_pc'] == program_va
    assert observed['trap_aux'] == _aux_code(AUX_RESERVED, 0)


def test_user_syscall_without_handler_locks_with_vector3(shared_core_config) -> None:
    observed = run_program_source(
        'SYSCALL',
        config=shared_core_config,
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL
    assert observed['trap_pc'] == 0


def test_supervisor_iret_restores_saved_context(shared_core_config) -> None:
    observed = run_program_source(
        '\n'.join([
            'IRET',
            'LDI #0xEE, R1',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={
            'interrupt_epc': 4,
            'interrupt_eflags': 0b101,
            'interrupt_cpu_control': 0,
        },
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['flags'] == 0b101
    assert observed['registers'][1] == 0


def test_user_iret_without_handler_raises_privileged_trap(shared_core_config) -> None:
    observed = run_program_source(
        'IRET',
        config=shared_core_config,
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 0


def test_user_stop_without_handler_raises_privileged_trap(shared_core_config) -> None:
    observed = run_program_source(
        'STOP',
        config=shared_core_config,
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 0


def test_supervisor_syscall_enters_handler_and_iret_returns(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    handler_words = assemble_source(
        '\n'.join([
            'LDI #21, R2',
            'LSR R2, R3',
            'LDI #2, R4',
            'ADD R4, R3',
            'SSR R2, R3',
            'LDI #0x7B, R1',
            'IRET',
        ])
    )
    observed = run_program_source(
        '\n'.join([
            'SYSCALL',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={'interrupt_table_base': vector_base},
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, TrapVector.SYSCALL_FROM_SUPERVISOR, handler_addr),
        max_cycles=96,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x7B
    assert observed['trap_cause'] == TrapVector.SYSCALL_FROM_SUPERVISOR
    assert observed['special_registers']['interrupt_epc'] == 2
    assert observed['special_registers']['interrupt_cpu_control'] == 0


def test_user_syscall_handler_can_adjust_return_mode_before_iret(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    handler_words = assemble_source(
        '\n'.join([
            'LDI #21, R2',
            'LSR R2, R3',
            'LDI #2, R4',
            'ADD R4, R3',
            'SSR R2, R3',
            'LDI #23, R2',
            'LDI #0, R3',
            'SSR R2, R3',
            'LDI #0x55, R1',
            'IRET',
        ])
    )
    observed = run_program_source(
        '\n'.join([
            'SYSCALL',
            'STOP',
        ]),
        config=shared_core_config,
        initial_special_registers={
            'cpu_control': CPU_CONTROL_USER_MODE,
            'interrupt_table_base': vector_base,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, TrapVector.SYSCALL, handler_addr),
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x55
    assert observed['trap_cause'] == TrapVector.SYSCALL
    assert observed['special_registers']['interrupt_epc'] == 2
    assert observed['special_registers']['cpu_control'] == 0


def test_maskable_irq_enters_handler_and_iret_returns(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    irq_vector = 65
    handler_words = assemble_source(
        '\n'.join([
            'LDI #21, R2',
            'LDI #2, R3',
            'SSR R2, R3',
            'LDI #20, R2',
            'LDI #0, R3',
            'SSR R2, R3',
            'LDI #0x44, R1',
            'IRET',
        ])
    )
    observed = run_program_source(
        '\n'.join([
            'JUMP @spin',
            'STOP',
            'spin:',
            'JUMP @spin',
        ]),
        config=shared_core_config,
        initial_special_registers={
            'cpu_control': CPU_CONTROL_INT_ENABLE,
            'interrupt_table_base': vector_base,
            'interrupt_mask_high': 1 << 1,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, irq_vector, handler_addr),
        irq_schedule={0: 1, 1: 0},
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x44
    assert observed['special_registers']['interrupt_epc'] == 2
    assert observed['special_registers']['interrupt_states_high'] & (1 << 1) == 0


def test_maskable_irq_handler_push_pop_preserves_gprs(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    irq_vector = 65
    initial_regs = {
        1: 0x1111,
        2: 0x2222,
        3: 0x3333,
        4: 0x4444,
        5: 0x5555,
        6: 0x6666,
        7: 0x7777,
        8: 0x8888,
        9: 0x9999,
        10: 0xAAAA,
        11: 0xBBBB,
        12: 0xCCCC,
        13: 0x3000,
        14: 0xDDDD,
    }
    handler_words = assemble_source(
        '\n'.join([
            'PUSH R1, R13',
            'PUSH R2, R13',
            'PUSH R3, R13',
            'PUSH R4, R13',
            'PUSH R5, R13',
            'PUSH R6, R13',
            'PUSH R7, R13',
            'PUSH R8, R13',
            'PUSH R9, R13',
            'PUSH R10, R13',
            'PUSH R11, R13',
            'PUSH R12, R13',
            'LDI #21, R2',
            'LDI #2, R3',
            'SSR R2, R3',
            'LDI #20, R2',
            'LDI #0, R3',
            'SSR R2, R3',
            'POP R12, R13',
            'POP R11, R13',
            'POP R10, R13',
            'POP R9, R13',
            'POP R8, R13',
            'POP R7, R13',
            'POP R6, R13',
            'POP R5, R13',
            'POP R4, R13',
            'POP R3, R13',
            'POP R2, R13',
            'POP R1, R13',
            'STOP',
        ])
    )
    # Main program spins; the IRQ handler itself STOPs after restoring registers.
    # This makes termination unconditional regardless of pipeline depth / interrupt_epc timing.
    observed = run_program_source(
        'spin:\nJUMP @spin',
        config=shared_core_config,
        initial_registers=initial_regs,
        initial_special_registers={
            'cpu_control': CPU_CONTROL_INT_ENABLE,
            'interrupt_table_base': vector_base,
            'interrupt_mask_high': 1 << 1,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, irq_vector, handler_addr),
        irq_schedule={0: 1, 1: 0},
        max_cycles=1024,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    for reg_index, reg_value in initial_regs.items():
        assert observed['registers'][reg_index] == reg_value


def test_lower_irq_vector_wins_and_pending_bits_are_not_cleared_on_entry(shared_core_config) -> None:
    vector_base = 0x100
    handler_65_addr = 0x40
    handler_66_addr = 0x60
    handler_65_words = assemble_source('LDI #0x41, R1\nSTOP')
    handler_66_words = assemble_source('LDI #0x42, R1\nSTOP')

    observed = run_program_source(
        '\n'.join([
            'JUMP @spin',
            'spin:',
            'JUMP @spin',
        ]),
        config=shared_core_config,
        initial_special_registers={
            'cpu_control': CPU_CONTROL_INT_ENABLE,
            'interrupt_table_base': vector_base,
            'interrupt_mask_high': (1 << 1) | (1 << 2),
        },
        extra_code_words={
            **{handler_65_addr + index * 2: word for index, word in enumerate(handler_65_words)},
            **{handler_66_addr + index * 2: word for index, word in enumerate(handler_66_words)},
        },
        initial_data_memory={
            **_vector_entry(vector_base, 65, handler_65_addr),
            **_vector_entry(vector_base, 66, handler_66_addr),
        },
        irq_schedule={0: 0b11, 1: 0},
        max_cycles=96,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x41
    assert observed['special_registers']['interrupt_states_high'] & 0x6 == 0x6
    assert ((observed['special_registers']['cpu_control'] >> CPU_CONTROL_CUR_INT_SHIFT) & 0x7F) == 65


def test_user_syscall_fetches_paged_interrupt_vector_in_supervisor_mode(shared_core_config) -> None:
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
    vector_entry = _vector_entry(vector_base_pa, trap_vector, handler_va)
    memory.update(vector_entry)

    observed = run_program_words(
        [],
        config=shared_core_config,
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
        max_cycles=96,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL
    assert observed['special_registers']['interrupt_cpu_control'] & CPU_CONTROL_USER_MODE


def test_paged_interrupt_table_fetch_failure_enters_lockup(shared_core_config) -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000
    program_pa = 0x0
    vector_base_va = 0xFFFF_FFC0_0000_7000
    program_words = assemble_source('SYSCALL')
    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=program_va, pa=program_pa, r=True, w=False, x=True, user=False)
    # Deliberately omit a mapping for vector_base_va so handler lookup faults during entry.
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=0xFFFF_FFC0_0000_8000, pa=0x8000, r=True, w=False, x=True, user=False)

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
            'interrupt_table_base': vector_base_va,
        },
        extra_code_words={program_pa + index * 2: word for index, word in enumerate(program_words)},
        initial_data_memory=memory,
        max_cycles=96,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL_FROM_SUPERVISOR


def test_exception_preempts_device_irq_handler(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    outer_irq = 65
    outer_cpu_control = CPU_CONTROL_IN_INTERRUPT | (outer_irq << CPU_CONTROL_CUR_INT_SHIFT)
    handler_words = assemble_source('JUMP @spin\nspin:\nJUMP @spin')

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: 1},
        initial_special_registers={
            'cpu_control': outer_cpu_control,
            'interrupt_table_base': vector_base,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, TrapVector.EXEC_ALIGN, handler_addr),
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 0
    assert observed['registers'][15] in (handler_addr, handler_addr + 2)
    assert observed['special_registers']['interrupt_epc'] == 1
    assert observed['special_registers']['interrupt_cpu_control'] == outer_cpu_control
    assert observed['trap_cause'] == TrapVector.EXEC_ALIGN
    assert ((observed['special_registers']['cpu_control'] >> CPU_CONTROL_CUR_INT_SHIFT) & 0x7F) == TrapVector.EXEC_ALIGN



def test_irq_does_not_drop_pending_mr_load_result_v4() -> None:
    """Guard against the MR-buffer IRQ admission typo regression in v4/core.py.

    The bug was `~mr.valid` (dead bundle field) in `irq_start` instead of `~mr_valid`
    (real MR-buffer occupancy signal), which allowed IRQ entry to race a pending load writeback.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / 'v4' / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    irq_start_begin = source.find('irq_start.eq(')
    entry_start_begin = source.find('entry_start.eq', irq_start_begin)
    assert irq_start_begin != -1
    assert entry_start_begin != -1

    irq_start_block = source[irq_start_begin:entry_start_begin]
    assert '~mr_valid &' in irq_start_block
    assert '~mr.valid' not in irq_start_block


def test_v4_clear_pipeline_sync_zeroes_mr_valid_not_bundle_field() -> None:
    """clear_pipeline_sync() must zero mr_valid (real Signal) — not mr.valid (dead bundle field).

    The pipeline-flush helper is the counterpart of the irq_start admission check.  If it were to
    zero only the dead bundle field `mr.valid`, the real `mr_valid` tracking signal would never be
    cleared on flush and the MR buffer would appear permanently full, stalling the pipeline.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / 'v4' / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    # Locate the clear_pipeline_sync function body (ends at the closing bracket before the next def)
    fn_begin = source.find('def clear_pipeline_sync():')
    fn_end = source.find('\n        def ', fn_begin + 1)
    assert fn_begin != -1 and fn_end != -1
    fn_body = source[fn_begin:fn_end]

    assert 'mr_valid.eq(0)' in fn_body, 'clear_pipeline_sync must zero mr_valid'
    assert 'mr.valid.eq(0)' not in fn_body, 'clear_pipeline_sync must not reference dead mr.valid'


def test_v4_irq_start_includes_storebuf_drain_guard() -> None:
    """irq_start must check ~storebuf_any_valid so a pending store drains before IRQ entry.

    Without this, an IRQ could take effect while a store-buffer entry is still waiting to commit,
    racing the store with the vector fetch over the LSU.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / 'v4' / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    irq_start_begin = source.find('irq_start.eq(')
    entry_start_begin = source.find('entry_start.eq', irq_start_begin)
    assert irq_start_begin != -1 and entry_start_begin != -1

    irq_start_block = source[irq_start_begin:entry_start_begin]
    assert '~storebuf_any_valid &' in irq_start_block


def test_v4_execute_to_storebuf_excludes_memory_flags_write() -> None:
    """execute_to_storebuf must exclude flags-write memory ops (SCR / compare-and-store variants).

    A flags-write memory op must always go through the main memory path so the flags register
    update (reg_write side-channel) is handled correctly.  Routing it to the store buffer, which
    only handles pure data stores, would silently drop the register writeback.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / 'v4' / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    storebuf_begin = source.find('execute_to_storebuf.eq(')
    storebuf_load_begin = source.find('execute_to_storebuf_load.eq(', storebuf_begin + 1)
    assert storebuf_begin != -1 and storebuf_load_begin != -1

    storebuf_block = source[storebuf_begin:storebuf_load_begin]
    assert '~execute_stage.outputs.memory_flags_write &' in storebuf_block


@pytest.mark.parametrize('variant', ['v3', 'v4'])
def test_ssr_write_gated_on_execute_to_retire(variant: str) -> None:
    """special_regs.write_stb must use execute_special_write_commit, not raw special_write_stb.

    execute_special_write_commit = special_write_stb & execute_to_retire.
    Without the execute_to_retire gate a squashed SSR (e.g., one following a load-redirect) would
    still commit its side effect to the special register file, corrupting cpu_control or
    interrupt_states_high.  The same gated signal must also guard the interrupt_states_high_set
    inhibit so a squashed SSR does not suppress a hardware IRQ edge.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / variant / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    assert 'execute_special_write_commit.eq(execute_stage.special_write_stb & execute_to_retire)' in source
    assert 'write_stb.eq(execute_special_write_commit)' in source
    assert '~(execute_special_write_commit & (execute_stage.special_write_selector == SpecialRegister.INTERRUPT_STATES_HIGH))' in source


def test_v3_irq_start_pipeline_signals_match_clear_inflight_sync() -> None:
    """Every pipeline-valid signal checked in v3 irq_start must also be zeroed by clear_inflight_sync.

    The irq_start gate and the pipeline-flush helper must agree on which registers constitute
    'pipeline not empty'.  A mismatch (signal checked but not cleared, or cleared but not checked)
    would either permit IRQ entry with in-flight work surviving the flush, or permanently block IRQ
    admission for registers that are never cleared.
    """
    core_path = Path(__file__).resolve().parents[1] / 'little64_cores' / 'v3' / 'core.py'
    source = core_path.read_text(encoding='utf-8')

    # Extract irq_start block
    irq_start_begin = source.find('irq_start.eq(')
    entry_start_begin = source.find('entry_start.eq', irq_start_begin)
    assert irq_start_begin != -1 and entry_start_begin != -1
    irq_start_block = source[irq_start_begin:entry_start_begin]

    # Extract clear_inflight_sync body
    fn_begin = source.find('def clear_inflight_sync():')
    fn_end = source.find('\n        def ', fn_begin + 1)
    assert fn_begin != -1 and fn_end != -1
    clear_body = source[fn_begin:fn_end]

    # All four pipeline-stage valid signals that irq_start checks must be cleared on flush.
    for signal in ('decode_valid', 'execute_valid', 'memory.valid', 'retire.valid'):
        assert f'~{signal}' in irq_start_block, f'irq_start missing check for {signal}'
        assert f'{signal}.eq(0)' in clear_body, f'clear_inflight_sync missing zero of {signal}'


def test_squashed_ssr_does_not_write_cpu_control_on_load_redirect(pipelined_core_config) -> None:
    observed = run_program_words(
        [
            encode_ls_reg('LOAD', 0, 3, 15),
            encode_gp_rr('SSR', 1, 2),
            encode_gp_imm('STOP', 0, 0),
        ],
        config=pipelined_core_config,
        initial_registers={
            1: 0,
            2: 0,
            3: 0x40,
        },
        initial_special_registers={'cpu_control': CPU_CONTROL_INT_ENABLE},
        initial_data_memory={
            0x40: 0x04,
            0x41: 0x00,
            0x42: 0x00,
            0x43: 0x00,
            0x44: 0x00,
            0x45: 0x00,
            0x46: 0x00,
            0x47: 0x00,
        },
        max_cycles=64,
    )

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['commit_count'] == 1
    assert observed['special_registers']['cpu_control'] == CPU_CONTROL_INT_ENABLE


def test_lower_numbered_exception_preempts_active_exception_and_preserves_trap_cause(shared_core_config) -> None:
    handler_addr = 0x40
    vector_base = 0x100
    outer_exception = TrapVector.SYSCALL_FROM_SUPERVISOR
    outer_cpu_control = CPU_CONTROL_IN_INTERRUPT | (outer_exception << CPU_CONTROL_CUR_INT_SHIFT)
    handler_words = assemble_source('JUMP @spin\nspin:\nJUMP @spin')

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: 1},
        initial_special_registers={
            'cpu_control': outer_cpu_control,
            'interrupt_table_base': vector_base,
            'trap_cause': outer_exception,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=_vector_entry(vector_base, TrapVector.EXEC_ALIGN, handler_addr),
        max_cycles=32,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 0
    assert observed['registers'][15] in (handler_addr, handler_addr + 2)
    assert observed['special_registers']['interrupt_epc'] == 1
    assert observed['special_registers']['interrupt_cpu_control'] == outer_cpu_control
    assert observed['trap_cause'] == outer_exception
    assert ((observed['special_registers']['cpu_control'] >> CPU_CONTROL_CUR_INT_SHIFT) & 0x7F) == TrapVector.EXEC_ALIGN


def test_exception_that_cannot_preempt_active_exception_enters_lockup(shared_core_config) -> None:
    active_exception = TrapVector.EXEC_ALIGN
    active_cpu_control = CPU_CONTROL_IN_INTERRUPT | (active_exception << CPU_CONTROL_CUR_INT_SHIFT)

    observed = run_program_source(
        'SYSCALL',
        config=shared_core_config,
        initial_special_registers={
            'cpu_control': active_cpu_control,
            'trap_cause': active_exception,
        },
        max_cycles=32,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == active_exception
    assert observed['trap_pc'] == 0


def test_invalid_nonleaf_l0_entry_raises_reserved_fault_subtype(shared_core_config) -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000
    memory: dict[int, int] = {}

    _write_u64(memory, root + (((program_va >> 30) & 0x1FF) * 8), _table_pte(l1))
    _write_u64(memory, l1 + (((program_va >> 21) & 0x1FF) * 8), _table_pte(l0))
    _write_u64(memory, l0 + (((program_va >> 12) & 0x1FF) * 8), _table_pte(0x7000))

    observed = run_program_words(
        [],
        config=shared_core_config,
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=48,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_RESERVED
    assert observed['trap_fault_addr'] == program_va
    assert observed['trap_access'] == 2
    assert observed['trap_aux'] == _aux_code(AUX_INVALID_NONLEAF, 0)