from __future__ import annotations

from amaranth.sim import Settle, Simulator

from little64.tlb import Little64TLB


def test_tlb_fill_lookup_and_flush() -> None:
    dut = Little64TLB(entries=8)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        yield dut.lookup_vaddr.eq(0x0000_0000_0000_1234)
        yield Settle()
        assert (yield dut.lookup_hit) == 0

        yield dut.fill_valid.eq(1)
        yield dut.fill_vaddr.eq(0x0000_0000_0000_1000)
        yield dut.fill_paddr.eq(0x0000_0000_0010_1000)
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
