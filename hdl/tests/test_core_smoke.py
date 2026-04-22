from __future__ import annotations

from dataclasses import replace

import pytest

from amaranth import Elaboratable, Module, ResetInserter, Signal
from amaranth.sim import Simulator

from little64_cores.isa import CPU_CONTROL_PAGING_ENABLE, CPU_CONTROL_USER_MODE, TrapVector
from little64_cores.variants import create_core
from shared_program import assemble_source, encode_gp_imm, run_program_source, run_program_words


pytestmark = pytest.mark.core_capabilities('reset', 'shared-architecture')


STOP_WORD = encode_gp_imm('STOP', 0, 0)


class _ResettableCore(Elaboratable):
    def __init__(self, core) -> None:
        self._core = core
        self.test_reset = Signal()
        self.i_bus = core.i_bus
        self.d_bus = core.d_bus
        self.halted = core.halted
        self.locked_up = core.locked_up
        self.register_file = core.register_file
        self.flags = core.flags
        self.special_regs = core.special_regs

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = ResetInserter(self.test_reset)(self._core)
        return m


def test_core_reset_contract_and_external_startup_state(shared_core_config) -> None:
    observed = run_program_source('STOP', config=shared_core_config, max_cycles=16)

    assert observed['locked_up'] == 0
    assert observed['halted'] == 1
    assert observed['registers'][0] == 0
    assert observed['registers'][15] == 2
    assert observed['flags'] == 0
    assert observed['trap_cause'] == 0
    assert observed['trap_fault_addr'] == 0
    assert observed['trap_access'] == 0
    assert observed['trap_pc'] == 0
    assert observed['trap_aux'] == 0
    assert observed['special_registers']['cpu_control'] == 0
    assert observed['special_registers']['interrupt_table_base'] == 0
    assert observed['special_registers']['interrupt_mask'] == 0
    assert observed['special_registers']['interrupt_mask_high'] == 0
    assert observed['special_registers']['interrupt_states'] == 0
    assert observed['special_registers']['interrupt_states_high'] == 0
    assert observed['special_registers']['interrupt_epc'] == 0
    assert observed['special_registers']['interrupt_eflags'] == 0
    assert observed['special_registers']['interrupt_cpu_control'] == 0

    seeded_special_registers = {
        'cpu_control': 0x1,
        'interrupt_table_base': 0x1234_5600,
        'interrupt_mask': 0x10,
        'interrupt_mask_high': 0x20,
        'interrupt_states': 0x40,
        'interrupt_states_high': 0x80,
        'interrupt_epc': 0x2222,
        'interrupt_eflags': 0x5,
        'interrupt_cpu_control': 0x1,
    }

    seeded = run_program_words(
        [],
        config=replace(shared_core_config, reset_vector=0x40),
        initial_special_registers=seeded_special_registers,
        extra_code_words={0x40: STOP_WORD},
        max_cycles=16,
    )

    assert seeded['locked_up'] == 0
    assert seeded['halted'] == 1
    assert seeded['registers'][15] == 0x42
    for name, value in seeded_special_registers.items():
        assert seeded['special_registers'][name] == value


def test_indirect_call_via_literal_pool_target(shared_core_config) -> None:
    prefix = assemble_source('\n'.join([
        'LOAD @literal, R1',
        'MOVE R15+2, R14',
        'MOVE R1, R15',
        'STOP',
        'literal:',
    ]))
    literal_words = [0x0000, 0x0000, 0x0000, 0x0000]
    target_words = assemble_source('\n'.join([
        'target:',
        'LDI #0x5A, R2',
        'MOVE R14, R15',
        'STOP',
    ]))
    program = prefix + literal_words + target_words

    literal_address = len(prefix) * 2
    target_address = (len(prefix) + len(literal_words)) * 2
    initial_data_memory = {
        literal_address + index: byte
        for index, byte in enumerate(target_address.to_bytes(8, 'little'))
    }

    observed = run_program_words(
        program,
        config=shared_core_config,
        initial_data_memory=initial_data_memory,
        max_cycles=128,
    )

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['registers'][1] == target_address
    assert observed['registers'][2] == 0x5A
    assert observed['registers'][14] == 0x06
    assert observed['registers'][15] == literal_address


def test_indirect_call_via_stack_spilled_target(shared_core_config) -> None:
    prefix = assemble_source('\n'.join([
        'LDI #0x00, R13',
        'LDI.S1 #0x20, R13',
        'LDI #8, R12',
        'LOAD @literal, R1',
        'SUB R12, R13',
        'STORE [R13], R1',
        'LOAD [R13], R1',
        'MOVE R15+2, R14',
        'MOVE R1, R15',
        'ADD R12, R13',
        'STOP',
        'literal:',
    ]))
    literal_words = [0x0000, 0x0000, 0x0000, 0x0000]
    target_words = assemble_source('\n'.join([
        'target:',
        'LDI #0x5A, R2',
        'MOVE R14, R15',
        'STOP',
    ]))
    program = prefix + literal_words + target_words

    literal_address = len(prefix) * 2
    target_address = (len(prefix) + len(literal_words)) * 2
    initial_data_memory = {
        literal_address + index: byte
        for index, byte in enumerate(target_address.to_bytes(8, 'little'))
    }

    observed = run_program_words(
        program,
        config=shared_core_config,
        initial_data_memory=initial_data_memory,
        max_cycles=128,
    )

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['registers'][1] == target_address
    assert observed['registers'][2] == 0x5A
    assert observed['registers'][13] == 0x2000
    assert observed['registers'][14] == 0x12
    assert observed['registers'][15] == literal_address


def test_core_reset_after_execution_restores_architectural_state(shared_core_config) -> None:
    reset_vector = 0x20
    words = assemble_source('\n'.join([
        'LDI #0x34, R1',
        'LDI #0x01, R2',
        'ADD R1, R2',
        'STOP',
    ]))

    code_memory: dict[int, int] = {}
    for word_index, word in enumerate(words):
        base = reset_vector + word_index * 2
        code_memory[base] = word & 0xFF
        code_memory[base + 1] = (word >> 8) & 0xFF

    def read_code_qword(addr: int) -> int:
        return sum((code_memory.get(addr + byte_index, 0) & 0xFF) << (8 * byte_index) for byte_index in range(8))

    dut = _ResettableCore(create_core(replace(shared_core_config, reset_vector=reset_vector)))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed: dict[str, int] = {}

    async def bus_process(ctx):
        while True:
            if ctx.get(dut.i_bus.cyc) and ctx.get(dut.i_bus.stb):
                ctx.set(dut.i_bus.dat_r, read_code_qword(ctx.get(dut.i_bus.adr)))
                ctx.set(dut.i_bus.ack, 1)
            else:
                ctx.set(dut.i_bus.ack, 0)

            if ctx.get(dut.d_bus.cyc) and ctx.get(dut.d_bus.stb):
                ctx.set(dut.d_bus.dat_r, 0)
                ctx.set(dut.d_bus.ack, 1)
            else:
                ctx.set(dut.d_bus.ack, 0)
            await ctx.tick()

    async def checker_process(ctx):
        ctx.set(dut.test_reset, 0)

        for _ in range(128):
            if ctx.get(dut.halted):
                break
            await ctx.tick()

        observed['pre_reset_halted'] = ctx.get(dut.halted)
        observed['pre_reset_r1'] = ctx.get(dut.register_file[1])
        observed['pre_reset_r2'] = ctx.get(dut.register_file[2])

        ctx.set(dut.test_reset, 1)
        await ctx.tick()
        await ctx.tick()
        observed['during_reset_halted'] = ctx.get(dut.halted)
        observed['during_reset_locked_up'] = ctx.get(dut.locked_up)
        observed['during_reset_r1'] = ctx.get(dut.register_file[1])
        observed['during_reset_r2'] = ctx.get(dut.register_file[2])
        observed['during_reset_r15'] = ctx.get(dut.register_file[15])
        observed['during_reset_flags'] = ctx.get(dut.flags)
        observed['during_reset_cpu_control'] = ctx.get(dut.special_regs.cpu_control)
        observed['during_reset_interrupt_mask'] = ctx.get(dut.special_regs.interrupt_mask)
        observed['during_reset_interrupt_states'] = ctx.get(dut.special_regs.interrupt_states)
        observed['during_reset_trap_cause'] = ctx.get(dut.special_regs.trap_cause)
        observed['during_reset_trap_pc'] = ctx.get(dut.special_regs.trap_pc)

        ctx.set(dut.test_reset, 0)
        await ctx.tick()
        await ctx.tick()

        for _ in range(128):
            if ctx.get(dut.halted):
                break
            await ctx.tick()

        observed['post_reset_halted'] = ctx.get(dut.halted)
        observed['post_reset_r1'] = ctx.get(dut.register_file[1])
        observed['post_reset_r2'] = ctx.get(dut.register_file[2])

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(300e-6)

    assert observed['pre_reset_halted'] == 1
    assert observed['pre_reset_r1'] == 0x34
    assert observed['pre_reset_r2'] == 0x35

    assert observed['during_reset_halted'] == 0
    assert observed['during_reset_locked_up'] == 0
    assert observed['during_reset_r1'] == 0
    assert observed['during_reset_r2'] == 0
    assert observed['during_reset_r15'] == reset_vector
    assert observed['during_reset_flags'] == 0
    assert observed['during_reset_cpu_control'] == 0
    assert observed['during_reset_interrupt_mask'] == 0
    assert observed['during_reset_interrupt_states'] == 0
    assert observed['during_reset_trap_cause'] == 0
    assert observed['during_reset_trap_pc'] == 0

    assert observed['post_reset_halted'] == 1
    assert observed['post_reset_r1'] == 0x34
    assert observed['post_reset_r2'] == 0x35


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


def test_completed_program_records_commit_activity(shared_core_config) -> None:
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
    assert observed['commit_count'] >= 1


def test_completed_memory_program_records_commit_activity(shared_core_config) -> None:
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
    assert observed['commit_count'] >= 1
