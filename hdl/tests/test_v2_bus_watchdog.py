from __future__ import annotations

from amaranth.sim import Simulator

from little64_cores.config import Little64CoreConfig
from little64_cores.v2 import Little64V2FetchFrontend, Little64V2LSU, V2LSUState
from little64_cores.v3 import Little64V3Core


def _run_frontend_with_stuck_bus(*, bus_timeout_cycles: int, cycles: int) -> dict[str, object]:
    frontend = Little64V2FetchFrontend(bus_timeout_cycles=bus_timeout_cycles)
    sim = Simulator(frontend)
    sim.add_clock(1e-6)

    observed: dict[str, object] = {
        'fetch_error_cycle': None,
        'fetch_error_final': 0,
        'cyc_history': [],
    }

    async def driver_process(ctx):
        ctx.set(frontend.pc, 0)
        for cycle in range(cycles):
            fetch_error = ctx.get(frontend.fetch_error)
            cyc = ctx.get(frontend.i_bus.cyc)
            observed['cyc_history'].append(cyc)
            if fetch_error and observed['fetch_error_cycle'] is None:
                observed['fetch_error_cycle'] = cycle
            await ctx.tick()
        observed['fetch_error_final'] = ctx.get(frontend.fetch_error)

    async def bus_process(ctx):
        while True:
            ctx.set(frontend.i_bus.ack, 0)
            ctx.set(frontend.i_bus.err, 0)
            ctx.set(frontend.i_bus.dat_r, 0)
            await ctx.tick()

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until((cycles + 4) * 1e-6)
    return observed


def test_v2_frontend_watchdog_disabled_hangs_forever_without_ack() -> None:
    result = _run_frontend_with_stuck_bus(bus_timeout_cycles=0, cycles=64)
    assert result['fetch_error_cycle'] is None
    assert result['fetch_error_final'] == 0
    # cyc must remain asserted at every observed cycle after initial request issue
    late_cyc = result['cyc_history'][8:]
    assert all(value == 1 for value in late_cyc)


def test_v2_frontend_watchdog_converts_stuck_fetch_into_fetch_error() -> None:
    timeout = 8
    result = _run_frontend_with_stuck_bus(bus_timeout_cycles=timeout, cycles=64)
    assert result['fetch_error_cycle'] is not None
    assert result['fetch_error_cycle'] <= timeout + 4


def _run_lsu_with_stuck_bus(*, bus_timeout_cycles: int, cycles: int) -> dict[str, object]:
    lsu = Little64V2LSU(bus_timeout_cycles=bus_timeout_cycles)
    sim = Simulator(lsu)
    sim.add_clock(1e-6)

    observed: dict[str, object] = {
        'response_error_cycle': None,
        'response_error_final': 0,
        'response_valid_at_error': 0,
        'cyc_history': [],
    }

    async def driver_process(ctx):
        ctx.set(lsu.request_valid, 0)
        ctx.set(lsu.request_addr, 0)
        ctx.set(lsu.request_width_bytes, 8)
        ctx.set(lsu.request_write, 0)
        ctx.set(lsu.request_store_value, 0)
        await ctx.tick()
        ctx.set(lsu.request_valid, 1)
        await ctx.tick()
        ctx.set(lsu.request_valid, 0)
        for cycle in range(cycles):
            cyc = ctx.get(lsu.bus.cyc)
            response_error = ctx.get(lsu.response_error)
            response_valid = ctx.get(lsu.response_valid)
            observed['cyc_history'].append(cyc)
            if response_error and observed['response_error_cycle'] is None:
                observed['response_error_cycle'] = cycle
                observed['response_valid_at_error'] = response_valid
            await ctx.tick()
        observed['response_error_final'] = ctx.get(lsu.response_error)

    async def bus_process(ctx):
        while True:
            ctx.set(lsu.bus.ack, 0)
            ctx.set(lsu.bus.err, 0)
            ctx.set(lsu.bus.dat_r, 0)
            await ctx.tick()

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(driver_process)
    sim.run_until((cycles + 8) * 1e-6)
    return observed


def test_v2_lsu_watchdog_disabled_hangs_forever_without_ack() -> None:
    result = _run_lsu_with_stuck_bus(bus_timeout_cycles=0, cycles=64)
    assert result['response_error_cycle'] is None
    assert result['response_error_final'] == 0
    late_cyc = result['cyc_history'][4:]
    assert all(value == 1 for value in late_cyc)


def test_v2_lsu_watchdog_converts_stuck_transaction_into_response_error() -> None:
    timeout = 8
    result = _run_lsu_with_stuck_bus(bus_timeout_cycles=timeout, cycles=64)
    assert result['response_error_cycle'] is not None
    assert result['response_valid_at_error'] == 1
    assert result['response_error_cycle'] <= timeout + 8


def _run_v3_core_with_stuck_ibus(*, bus_timeout_cycles: int, cycles: int) -> dict[str, object]:
    config = Little64CoreConfig(
        core_variant='v3',
        reset_vector=0,
        bus_timeout_cycles=bus_timeout_cycles,
    )
    dut = Little64V3Core(config)

    sim = Simulator(dut)
    sim.add_clock(1e-6)

    observed: dict[str, object] = {
        'locked_up_cycle': None,
        'locked_up_final': 0,
    }

    async def bus_process(ctx):
        while True:
            await ctx.tick()
            ctx.set(dut.i_bus.ack, 0)
            ctx.set(dut.i_bus.err, 0)
            ctx.set(dut.d_bus.ack, 0)
            ctx.set(dut.d_bus.err, 0)

    async def observe_process(ctx):
        await ctx.tick()
        await ctx.tick()
        for cycle in range(cycles):
            await ctx.tick()
            if ctx.get(dut.locked_up) and observed['locked_up_cycle'] is None:
                observed['locked_up_cycle'] = cycle
                break
        observed['locked_up_final'] = ctx.get(dut.locked_up)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(observe_process)
    sim.run_until((cycles + 8) * 1e-6)
    return observed


def test_v3_core_with_stuck_ibus_watchdog_disabled_hangs_without_lockup() -> None:
    result = _run_v3_core_with_stuck_ibus(bus_timeout_cycles=0, cycles=128)
    assert result['locked_up_cycle'] is None
    assert result['locked_up_final'] == 0


def test_v3_core_with_stuck_ibus_watchdog_promotes_hang_to_lockup() -> None:
    result = _run_v3_core_with_stuck_ibus(bus_timeout_cycles=8, cycles=128)
    assert result['locked_up_cycle'] is not None
