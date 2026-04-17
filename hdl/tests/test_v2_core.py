from __future__ import annotations

from amaranth.sim import Simulator

from little64.config import Little64CoreConfig
from little64.isa import TrapVector
from little64.v2 import Little64V2Core, Little64V2FetchFrontend, V2PipelineState


STOP_INSTRUCTION = 0xDF00
LDI_R1_IMM12 = 0x8121
UNSUPPORTED_GP_INSTRUCTION = 0xC500


def test_v2_frontend_reuses_buffered_fetch_line() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    seen_addresses: list[int] = []
    observed = {}

    def driver_process():
        yield frontend.pc.eq(0)
        for cycle in range(8):
            if cycle == 4:
                yield frontend.pc.eq(2)
            yield
        observed['line_valid'] = (yield frontend.line_valid)
        observed['instruction_valid'] = (yield frontend.instruction_valid)
        observed['instruction_word'] = (yield frontend.instruction_word)

    def bus_process():
        request_active_last = False
        while True:
            request_active = (yield frontend.i_bus.cyc) and (yield frontend.i_bus.stb)
            if request_active and not request_active_last:
                seen_addresses.append((yield frontend.i_bus.adr))
            if request_active:
                yield frontend.i_bus.dat_r.eq(STOP_INSTRUCTION | (LDI_R1_IMM12 << 16))
                yield frontend.i_bus.ack.eq(1)
            else:
                yield frontend.i_bus.ack.eq(0)
            request_active_last = request_active
            yield

    sim.add_sync_process(driver_process)
    sim.add_sync_process(bus_process)
    sim.run_until(10e-6, run_passive=True)

    assert seen_addresses == [0]
    assert observed['line_valid'] == 1
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == LDI_R1_IMM12


def test_v2_core_fetches_stop_then_halts() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {'commit_count': 0}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                yield dut.i_bus.dat_r.eq(STOP_INSTRUCTION)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)
            yield

    def checker_process():
        for _ in range(32):
            if (yield dut.commit_valid):
                observed['commit_count'] += 1
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield
        observed['halted'] = (yield dut.halted)
        observed['locked_up'] = (yield dut.locked_up)
        observed['state'] = (yield dut.state)
        observed['instruction'] = (yield dut.current_instruction)

    sim.add_sync_process(bus_process)
    sim.add_sync_process(checker_process)
    sim.run_until(40e-6, run_passive=True)

    assert observed['commit_count'] == 0
    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['state'] == V2PipelineState.HALTED
    assert observed['instruction'] == STOP_INSTRUCTION


def test_v2_core_decodes_stop_from_upper_fetch_slot() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=6))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                yield dut.i_bus.dat_r.eq(STOP_INSTRUCTION << 48)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)
            yield

    def checker_process():
        for _ in range(20):
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield
        observed['instruction'] = (yield dut.current_instruction)
        observed['halted'] = (yield dut.halted)
        observed['fetch_pc'] = (yield dut.fetch_pc)
        observed['fetch_phys_addr'] = (yield dut.fetch_phys_addr)

    sim.add_sync_process(bus_process)
    sim.add_sync_process(checker_process)
    sim.run_until(20e-6, run_passive=True)

    assert observed['instruction'] == STOP_INSTRUCTION
    assert observed['halted'] == 1
    assert observed['fetch_pc'] == 6
    assert observed['fetch_phys_addr'] == 6


def test_v2_core_records_invalid_instruction_trap_before_lockup() -> None:
    dut = Little64V2Core(Little64CoreConfig(core_variant='v2', reset_vector=0))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed = {'commit_count': 0}

    def bus_process():
        while True:
            if (yield dut.i_bus.cyc) and (yield dut.i_bus.stb):
                yield dut.i_bus.dat_r.eq(UNSUPPORTED_GP_INSTRUCTION)
                yield dut.i_bus.ack.eq(1)
            else:
                yield dut.i_bus.ack.eq(0)

            if (yield dut.d_bus.cyc) and (yield dut.d_bus.stb):
                yield dut.d_bus.dat_r.eq(0)
                yield dut.d_bus.ack.eq(1)
            else:
                yield dut.d_bus.ack.eq(0)
            yield

    def checker_process():
        for _ in range(32):
            if (yield dut.commit_valid):
                observed['commit_count'] += 1
            if (yield dut.halted) or (yield dut.locked_up):
                break
            yield
        observed['halted'] = (yield dut.halted)
        observed['locked_up'] = (yield dut.locked_up)
        observed['state'] = (yield dut.state)
        observed['trap_cause'] = (yield dut.special_regs.trap_cause)
        observed['trap_pc'] = (yield dut.special_regs.trap_pc)

    sim.add_sync_process(bus_process)
    sim.add_sync_process(checker_process)
    sim.run_until(40e-6, run_passive=True)

    assert observed['commit_count'] == 0
    assert observed['halted'] == 0
    assert observed['locked_up'] == 1
    assert observed['state'] == V2PipelineState.STALLED
    assert observed['trap_cause'] == TrapVector.INVALID_INSTRUCTION
    assert observed['trap_pc'] == 0