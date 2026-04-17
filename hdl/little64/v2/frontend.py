from __future__ import annotations

from amaranth import Array, Const, Elaboratable, Module, Signal

from ..wishbone import WishboneMasterInterface


FETCH_LINE_BYTES = 8
FETCH_LINE_MASK = 0xFFFFFFFFFFFFFFF8


class Little64V2FetchFrontend(Elaboratable):
    def __init__(self, *, address_width: int = 64, data_width: int = 64) -> None:
        self.i_bus = WishboneMasterInterface(
            data_width=data_width,
            address_width=address_width,
            name='i_bus',
        )

        self.pc = Signal(64)
        self.invalidate = Signal()
        self.update_line_valid = Signal()
        self.update_line_data = Signal(data_width)

        self.instruction_valid = Signal()
        self.instruction_word = Signal(16)
        self.instruction_pc = Signal(64)
        self.fetch_phys_addr = Signal(64)
        self.request_inflight = Signal()
        self.fetch_error = Signal()

        self.line_valid = Signal()
        self.line_base = Signal(64)
        self.line_data = Signal(data_width)

    def elaborate(self, platform):
        m = Module()

        line_base_requested = Signal(64)
        line_hit = Signal()
        request_valid = Signal()
        request_line_base = Signal(64)
        bus_request_base = Signal(64)
        slot_index = Signal(2)
        instruction_words = Array([self.line_data.word_select(index, 16) for index in range(4)])

        m.d.comb += [
            line_base_requested.eq(self.pc & Const(FETCH_LINE_MASK, 64)),
            line_hit.eq(self.line_valid & (self.line_base == line_base_requested)),
            bus_request_base.eq(request_line_base),
            slot_index.eq(self.pc[1:3]),
            self.instruction_valid.eq(line_hit),
            self.instruction_word.eq(instruction_words[slot_index]),
            self.instruction_pc.eq(self.pc),
            self.fetch_phys_addr.eq(line_base_requested),
            self.fetch_error.eq(request_valid & self.i_bus.err),
            self.request_inflight.eq(request_valid),
            self.i_bus.adr.eq(bus_request_base),
            self.i_bus.dat_w.eq(0),
            self.i_bus.sel.eq((1 << self.i_bus.sel_width) - 1),
            self.i_bus.cyc.eq(request_valid),
            self.i_bus.stb.eq(request_valid),
            self.i_bus.we.eq(0),
            self.i_bus.cti.eq(0),
            self.i_bus.bte.eq(0),
        ]

        with m.If(self.invalidate):
            m.d.sync += [
                self.line_valid.eq(0),
                request_valid.eq(0),
            ]
        with m.Elif(self.update_line_valid):
            m.d.sync += self.line_data.eq(self.update_line_data)
        with m.Elif(~line_hit & ~request_valid):
            m.d.sync += [
                request_valid.eq(1),
                request_line_base.eq(line_base_requested),
            ]
        with m.Elif(request_valid & self.i_bus.ack & ~self.i_bus.err):
            m.d.sync += [
                request_valid.eq(0),
                self.line_valid.eq(1),
                self.line_base.eq(request_line_base),
                self.line_data.eq(self.i_bus.dat_r),
            ]
        with m.Elif(request_valid & self.i_bus.err):
            m.d.sync += [
                request_valid.eq(0),
                self.line_valid.eq(0),
            ]

        return m


__all__ = [
    'FETCH_LINE_BYTES',
    'FETCH_LINE_MASK',
    'Little64V2FetchFrontend',
]