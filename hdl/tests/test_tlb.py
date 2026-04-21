from __future__ import annotations

from amaranth.sim import Settle, Simulator

from little64_cores.v2.tlb import Little64V2TLB


def test_tlb_fill_lookup_and_flush() -> None:
    dut = Little64V2TLB(entries=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.lookup_vaddr.eq(0x0000_0000_0000_1234)
        yield Settle()
        assert (yield dut.lookup_hit) == 0

        yield dut.fill_valid.eq(1)
        yield dut.fill_vpage.eq(0x0000_0000_0000_1)
        yield dut.fill_ppage.eq(0x0000_0000_0001_01)
        yield dut.fill_perm_read.eq(1)
        yield dut.fill_perm_write.eq(1)
        yield dut.fill_perm_execute.eq(0)
        yield dut.fill_perm_user.eq(1)
        yield

        yield dut.fill_valid.eq(0)
        yield dut.lookup_vaddr.eq(0x0000_0000_0000_1234)
        yield Settle()
        assert (yield dut.lookup_hit) == 1
        assert (yield dut.lookup_paddr) == 0x0000_0000_0010_1234
        assert (yield dut.lookup_perm_read) == 1
        assert (yield dut.lookup_perm_write) == 1
        assert (yield dut.lookup_perm_execute) == 0
        assert (yield dut.lookup_perm_user) == 1

        yield dut.flush_all.eq(1)
        yield
        yield dut.flush_all.eq(0)
        yield Settle()
        assert (yield dut.lookup_hit) == 0

    sim.add_sync_process(process)
    sim.run()


def test_tlb_flush_generations_do_not_clear_entries_broadcast() -> None:
    dut = Little64V2TLB(entries=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.fill_valid.eq(1)
        yield dut.fill_vpage.eq(0x0000_0000_0000_2)
        yield dut.fill_ppage.eq(0x0000_0000_0002_02)
        yield dut.fill_perm_read.eq(1)
        yield

        yield dut.fill_valid.eq(0)
        yield dut.lookup_vaddr.eq(0x0000_0000_0000_2456)
        yield Settle()
        assert (yield dut.lookup_hit) == 1
        assert (yield dut.lookup_paddr) == 0x0000_0000_0020_2456

        yield dut.flush_all.eq(1)
        yield
        yield dut.flush_all.eq(0)
        yield Settle()
        assert (yield dut.lookup_hit) == 0

        yield dut.fill_valid.eq(1)
        yield dut.fill_vpage.eq(0x0000_0000_0000_2)
        yield dut.fill_ppage.eq(0x0000_0000_0003_02)
        yield

        yield dut.fill_valid.eq(0)
        yield Settle()
        assert (yield dut.lookup_hit) == 1
        assert (yield dut.lookup_paddr) == 0x0000_0000_0030_2456

        yield dut.flush_all.eq(1)
        yield
        yield dut.flush_all.eq(0)
        yield Settle()
        assert (yield dut.lookup_hit) == 0

    sim.add_sync_process(process)
    sim.run()


def test_tlb_generation_wrap_clears_stale_entries() -> None:
    dut = Little64V2TLB(entries=8, generation_bits=2)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.fill_valid.eq(1)
        yield dut.fill_vpage.eq(0x0000_0000_0000_3)
        yield dut.fill_ppage.eq(0x0000_0000_0004_03)
        yield dut.fill_perm_read.eq(1)
        yield

        yield dut.fill_valid.eq(0)
        yield dut.lookup_vaddr.eq(0x0000_0000_0000_3567)
        yield Settle()
        assert (yield dut.lookup_hit) == 1

        for _ in range(4):
            yield dut.flush_all.eq(1)
            yield
            yield dut.flush_all.eq(0)
            yield Settle()
            assert (yield dut.lookup_hit) == 0

    sim.add_sync_process(process)
    sim.run()
