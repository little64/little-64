from __future__ import annotations

from little64_cores.config import Little64CoreConfig
from little64_cores.isa import (
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_PAGING_ENABLE,
    CPU_CONTROL_USER_MODE,
    TrapVector,
)
from shared_program import assemble_source, encode_gp_imm, encode_ls_reg, run_program_source, run_program_words
from test_traps import (
    AUX_NO_VALID_PTE,
    AUX_PERMISSION,
    _aux_code,
    _build_mapping,
    _vector_entry,
)


def _v3_config() -> Little64CoreConfig:
    return Little64CoreConfig(core_variant='v3', cache_topology='none')


def test_v3_paged_store_reaches_translated_physical_address() -> None:
    root = 0x4000
    l1_code = 0x5000
    l1_data = 0x6000
    l0_code = 0x7000
    l0_data = 0x8000
    data_va = 0xFFFF_FFC0_0000_3000
    data_pa = 0x3000
    value = 0x1122_3344_5566_7788

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)
    _build_mapping(memory, root=root, l1=l1_data, l0=l0_data, va=data_va, pa=data_pa, r=True, w=True, x=False, user=False)

    observed = run_program_words(
        [
            encode_ls_reg('STORE', 0, 2, 1),
            encode_gp_imm('STOP', 0, 0),
        ],
        config=_v3_config(),
        initial_registers={1: value, 2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    encoded = sum(observed['data_memory'][data_pa + offset] << (8 * offset) for offset in range(8))
    assert encoded == value


def test_v3_paged_load_reads_translated_physical_address() -> None:
    root = 0x4000
    l1_code = 0x5000
    l1_data = 0x6000
    l0_code = 0x7000
    l0_data = 0x8000
    data_va = 0xFFFF_FFC0_0000_3000
    data_pa = 0x3000
    value = 0x1122_3344_5566_7788

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)
    _build_mapping(memory, root=root, l1=l1_data, l0=l0_data, va=data_va, pa=data_pa, r=True, w=True, x=False, user=False)
    for offset in range(8):
        memory[data_pa + offset] = (value >> (8 * offset)) & 0xFF

    observed = run_program_words(
        [
            encode_ls_reg('LOAD', 0, 2, 3),
            encode_gp_imm('STOP', 0, 0),
        ],
        config=_v3_config(),
        initial_registers={2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][3] == value


def test_v3_paged_store_and_load_round_trip() -> None:
    root = 0x4000
    l1_code = 0x5000
    l1_data = 0x6000
    l0_code = 0x7000
    l0_data = 0x8000
    data_va = 0xFFFF_FFC0_0000_3000
    data_pa = 0x3000
    value = 0x1122_3344_5566_7788

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)
    _build_mapping(memory, root=root, l1=l1_data, l0=l0_data, va=data_va, pa=data_pa, r=True, w=True, x=False, user=False)

    observed = run_program_words(
        [
            encode_ls_reg('STORE', 0, 2, 1),
            encode_ls_reg('LOAD', 0, 2, 3),
            encode_gp_imm('STOP', 0, 0),
        ],
        config=_v3_config(),
        initial_registers={1: value, 2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == 0
    assert observed['registers'][3] == value


def test_v3_store_without_write_permission_raises_data_page_fault() -> None:
    root = 0x4000
    l1_code = 0x5000
    l1_data = 0x6000
    l0_code = 0x7000
    l0_data = 0x8000
    data_va = 0xFFFF_FFC0_0000_3000

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)
    _build_mapping(memory, root=root, l1=l1_data, l0=l0_data, va=data_va, pa=0x3000, r=True, w=False, x=False, user=False)

    observed = run_program_words(
        [encode_ls_reg('STORE', 0, 2, 1)],
        config=_v3_config(),
        initial_registers={1: 0xAA, 2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=96,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_PERMISSION
    assert observed['trap_fault_addr'] == data_va
    assert observed['trap_access'] == 1
    assert observed['trap_pc'] == 0
    assert observed['trap_aux'] == _aux_code(AUX_PERMISSION, 0)


def test_v3_load_without_mapping_raises_not_present_data_page_fault() -> None:
    root = 0x4000
    l1_code = 0x5000
    l0_code = 0x6000
    data_va = 0xFFFF_FFC0_0000_3000

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)

    observed = run_program_words(
        [encode_ls_reg('LOAD', 0, 2, 1)],
        config=_v3_config(),
        initial_registers={2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
        },
        initial_data_memory=memory,
        max_cycles=96,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_NOT_PRESENT
    assert observed['trap_fault_addr'] == data_va
    assert observed['trap_access'] == 0
    assert observed['trap_pc'] == 0
    assert observed['trap_aux'] == _aux_code(AUX_NO_VALID_PTE, 2)


def test_v3_user_syscall_fetches_paged_interrupt_vector() -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000
    program_pa = 0x0
    vector_base_va = 0xFFFF_FFC0_0000_7000
    vector_base_pa = 0x7000
    handler_va = 0xFFFF_FFC0_0000_8000
    handler_pa = 0x8000

    program_words = assemble_source('SYSCALL')
    handler_words = assemble_source('STOP')
    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=program_va, pa=program_pa, r=True, w=False, x=True, user=True)
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=vector_base_va, pa=vector_base_pa, r=True, w=False, x=False, user=False)
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=handler_va, pa=handler_pa, r=True, w=False, x=True, user=False)
    memory.update(_vector_entry(vector_base_pa, TrapVector.SYSCALL, handler_va))

    observed = run_program_words(
        [],
        config=_v3_config(),
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


def test_v3_paged_interrupt_table_lookup_failure_preserves_original_trap() -> None:
    root = 0x4000
    l1 = 0x5000
    l0 = 0x6000
    program_va = 0xFFFF_FFC0_0000_0000
    program_pa = 0x0
    vector_base_va = 0xFFFF_FFC0_0000_7000
    program_words = assemble_source('SYSCALL')

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1, l0=l0, va=program_va, pa=program_pa, r=True, w=False, x=True, user=False)

    observed = run_program_words(
        [],
        config=_v3_config(),
        initial_registers={15: program_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
            'interrupt_table_base': vector_base_va,
        },
        extra_code_words={program_pa + index * 2: word for index, word in enumerate(program_words)},
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.SYSCALL_FROM_SUPERVISOR


def test_v3_maskable_irq_delivery_enters_handler() -> None:
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
        config=_v3_config(),
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


def test_v3_data_page_fault_can_enter_handler() -> None:
    root = 0x4000
    l1_code = 0x5000
    l0_code = 0x6000
    data_va = 0xFFFF_FFC0_0000_3000
    vector_base = 0x100
    handler_addr = 0x40
    handler_words = assemble_source('STOP')

    memory: dict[int, int] = {}
    _build_mapping(memory, root=root, l1=l1_code, l0=l0_code, va=0x0, pa=0x0, r=True, w=False, x=True, user=False)
    memory.update(_vector_entry(vector_base, TrapVector.PAGE_FAULT_NOT_PRESENT, handler_addr))

    observed = run_program_words(
        [encode_ls_reg('LOAD', 0, 2, 1)],
        config=_v3_config(),
        initial_registers={2: data_va},
        initial_special_registers={
            'cpu_control': CPU_CONTROL_PAGING_ENABLE,
            'page_table_root_physical': root,
            'interrupt_table_base': vector_base,
        },
        extra_code_words={handler_addr + index * 2: word for index, word in enumerate(handler_words)},
        initial_data_memory=memory,
        max_cycles=128,
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['trap_cause'] == TrapVector.PAGE_FAULT_NOT_PRESENT
