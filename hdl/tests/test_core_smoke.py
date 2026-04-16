from __future__ import annotations

from amaranth.sim import Simulator

from little64.config import Little64CoreConfig
from little64.isa import CPU_CONTROL_PAGING_ENABLE, CPU_CONTROL_USER_MODE, TrapVector
from little64.core import Little64Core
from shared_program import assemble_source, run_program_source


def test_core_fetches_ldi_then_stops() -> None:
    config = Little64CoreConfig(reset_vector=0)
    dut = Little64Core(config)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    ldi_r1_imm12 = 0x8121
    stop = 0xDF00
    fetch_word = ldi_r1_imm12 | (stop << 16)
    observed = {}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                yield dut.i_bus.dat_r.eq(fetch_word)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)
            yield

    def checker_process():
        for _ in range(16):
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield

        observed['r1'] = (yield dut.register_file[1])
        observed['r0'] = (yield dut.register_file[0])
        observed['halted'] = (yield dut.halted)

    sim.add_sync_process(bus_process)
    sim.add_sync_process(checker_process)
    sim.run_until(12e-6, run_passive=True)

    assert observed['r1'] == 0x12
    assert observed['r0'] == 0
    assert observed['halted'] == 1


def test_core_round_trips_special_registers_via_lsr_and_ssr() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #17, R2',
            'LDI #0x5A, R1',
            'LDI.S1 #0xA5, R1',
            'SSR R2, R1',
            'LSR R2, R3',
            'STOP',
        ])
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][3] == 0xA55A
    assert observed['trap_cause'] == 0


def test_core_allows_user_thread_pointer_access_via_lsr() -> None:
    handler_addr = 0x40
    vector_base = 0x100
    handler_words = assemble_source('STOP')
    observed = run_program_source(
        '\n'.join([
            'LDI.S1 #0x80, R2',
            'LSR R2, R1',
            'STOP',
        ]),
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
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][1] == 0x1234_5678_9ABC_DEF0


def test_core_traps_user_supervisor_bank_lsr() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0, R2',
            'LSR R2, R1',
            'STOP',
        ]),
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 2
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_aux'] == 0
    assert observed['registers'][1] == 0


def test_core_traps_user_supervisor_bank_ssr() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0, R2',
            'LDI #0x34, R1',
            'LDI.S1 #0x12, R1',
            'SSR R2, R1',
            'STOP',
        ]),
        initial_special_registers={'cpu_control': CPU_CONTROL_USER_MODE},
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['trap_cause'] == TrapVector.PRIVILEGED_INSTRUCTION
    assert observed['trap_pc'] == 6
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_aux'] == 0
    assert observed['registers'][1] == 0x1234


def test_core_locks_up_when_paging_is_enabled_without_mmu_support() -> None:
    observed = run_program_source(
        'STOP',
        config=Little64CoreConfig(enable_mmu=False, reset_vector=0),
        initial_special_registers={'cpu_control': CPU_CONTROL_PAGING_ENABLE},
        max_cycles=16,
    )

    assert observed['halted'] == 0
    assert observed['locked_up'] == 1


def test_commit_valid_pulses_for_each_instruction() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #42, R1',
            'LDI #7, R2',
            'ADD R1, R2',
            'STOP',
        ])
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == 4


def test_commit_valid_pulses_for_memory_instructions() -> None:
    observed = run_program_source(
        '\n'.join([
            'LDI #0x10, R2',
            'LDI.S1 #0x10, R2',
            'LDI #0xAB, R1',
            'STORE [R2], R1',
            'LOAD [R2], R3',
            'STOP',
        ])
    )

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['commit_count'] == 6
