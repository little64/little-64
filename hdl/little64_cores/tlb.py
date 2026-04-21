from __future__ import annotations

from math import log2

from amaranth import Elaboratable, Signal


class Little64TLB(Elaboratable):
    """Definition-only TLB interface.

    Core-local implementations live under basic/, v2/, and v3/.
    """

    def __init__(self, *, entries: int = 64, address_width: int = 64, generation_bits: int = 8) -> None:
        if entries < 2 or entries & (entries - 1):
            raise ValueError('Little64TLB entries must be a power of two and at least 2')
        if generation_bits < 1:
            raise ValueError('Little64TLB generation_bits must be at least 1')

        self.entries = entries
        self.address_width = address_width
        self.generation_bits = generation_bits
        self.page_offset_bits = 12
        self.page_number_width = address_width - self.page_offset_bits
        self.index_bits = int(log2(entries))

        self.lookup_vaddr = Signal(address_width)
        self.lookup_hit = Signal()
        self.lookup_paddr = Signal(address_width)
        self.lookup_perm_read = Signal()
        self.lookup_perm_write = Signal()
        self.lookup_perm_execute = Signal()
        self.lookup_perm_user = Signal()

        self.fill_valid = Signal()
        self.fill_vpage = Signal(self.page_number_width)
        self.fill_ppage = Signal(self.page_number_width)
        self.fill_perm_read = Signal()
        self.fill_perm_write = Signal()
        self.fill_perm_execute = Signal()
        self.fill_perm_user = Signal()

        self.flush_all = Signal()

    def elaborate(self, platform):
        raise NotImplementedError('Use core-local TLB implementations in basic/v2/v3')
