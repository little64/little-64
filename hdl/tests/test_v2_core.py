from __future__ import annotations

from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.isa import TrapVector
from little64_cores.v2 import Little64V2Core, Little64V2FetchFrontend, V2PipelineState


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


def test_v2_frontend_ignores_stale_response_after_invalidate() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    line0 = 0xE004_B10D_940D_800D
    line8 = 0x0000_0000_0000_00BE
    line16 = 0x1021_1002_101F_43B1

    seen_addresses: list[int] = []
    pending_responses: list[list[int]] = []
    observed = {}

    def driver_process():
        yield frontend.pc.eq(0)
        yield frontend.invalidate.eq(0)
        for cycle in range(16):
            if cycle == 6:
                yield frontend.pc.eq(8)
            if cycle == 7:
                yield frontend.invalidate.eq(1)
                yield frontend.pc.eq(16)
            elif cycle == 8:
                yield frontend.invalidate.eq(0)
            yield
        observed['line_valid'] = (yield frontend.line_valid)
        observed['line_base'] = (yield frontend.line_base)
        observed['line_data'] = (yield frontend.line_data)
        observed['instruction_valid'] = (yield frontend.instruction_valid)
        observed['instruction_word'] = (yield frontend.instruction_word)

    def bus_process():
        request_active_last = False
        while True:
            yield frontend.i_bus.ack.eq(0)
            yield frontend.i_bus.err.eq(0)
            yield frontend.i_bus.dat_r.eq(0)
            request_active = (yield frontend.i_bus.cyc) and (yield frontend.i_bus.stb)
            if request_active and not request_active_last:
                address = (yield frontend.i_bus.adr)
                seen_addresses.append(address)
                pending_responses.append([address, 1])

            for pending in pending_responses:
                pending[1] -= 1

            if pending_responses and pending_responses[0][1] < 0:
                address = pending_responses.pop(0)[0]
                value = {0: line0, 8: line8, 16: line16}[address]
                yield frontend.i_bus.dat_r.eq(value)
                yield frontend.i_bus.ack.eq(1)

            request_active_last = request_active
            yield

    sim.add_sync_process(driver_process)
    sim.add_sync_process(bus_process)
    sim.run_until(20e-6, run_passive=True)

    assert seen_addresses == [0, 8, 16]
    assert observed['line_valid'] == 1
    assert observed['line_base'] == 16
    assert observed['line_data'] == line16
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == 0x43B1


def test_v2_frontend_reissues_redirected_fetch_after_cancelled_ack() -> None:
    frontend = Little64V2FetchFrontend()
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    line78 = 0x4444_3333_2222_1111
    line80 = 0x8888_7777_6666_5555
    line88 = 0xCCCC_BBBB_AAAA_9999
    expected_lines = {0x78: line78, 0x80: line80, 0x88: line88}

    seen_addresses: list[int] = []
    pending_responses: list[list[int]] = []
    observed = {}

    def driver_process():
        yield frontend.pc.eq(0x78)
        yield frontend.invalidate.eq(0)
        for cycle in range(22):
            if cycle == 7:
                yield frontend.pc.eq(0x80)
            if cycle == 9:
                yield frontend.invalidate.eq(1)
                yield frontend.pc.eq(0x88)
            elif cycle == 11:
                yield frontend.invalidate.eq(0)
            yield
        observed['line_valid'] = (yield frontend.line_valid)
        observed['line_base'] = (yield frontend.line_base)
        observed['line_data'] = (yield frontend.line_data)
        observed['instruction_valid'] = (yield frontend.instruction_valid)
        observed['instruction_word'] = (yield frontend.instruction_word)

    def bus_process():
        request_active_last = False
        while True:
            yield frontend.i_bus.ack.eq(0)
            yield frontend.i_bus.err.eq(0)
            yield frontend.i_bus.dat_r.eq(0)

            request_active = (yield frontend.i_bus.cyc) and (yield frontend.i_bus.stb)
            if request_active and not request_active_last:
                address = (yield frontend.i_bus.adr)
                if address in expected_lines:
                    seen_addresses.append(address)
                pending_responses.append([address, 1])

            for pending in pending_responses:
                pending[1] -= 1

            if pending_responses and pending_responses[0][1] < 0:
                address = pending_responses.pop(0)[0]
                value = expected_lines.get(address, 0)
                yield frontend.i_bus.dat_r.eq(value)
                yield frontend.i_bus.ack.eq(1)

            request_active_last = request_active
            yield

    sim.add_sync_process(driver_process)
    sim.add_sync_process(bus_process)
    sim.run_until(28e-6, run_passive=True)

    assert seen_addresses == [0x78, 0x80, 0x88]
    assert observed['line_valid'] == 1
    assert observed['line_base'] == 0x88
    assert observed['line_data'] == line88
    assert observed['instruction_valid'] == 1
    assert observed['instruction_word'] == 0x9999


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