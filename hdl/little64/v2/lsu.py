from __future__ import annotations

from enum import IntEnum

from amaranth import Cat, Const, Elaboratable, Module, Mux, Signal

from ..wishbone import WishboneMasterInterface
from .frontend import DEFAULT_BUS_TIMEOUT_CYCLES


class V2LSUState(IntEnum):
    IDLE = 0
    FIRST = 1
    SECOND = 2


class Little64V2LSU(Elaboratable):
    def __init__(self,
                 *,
                 address_width: int = 64,
                 data_width: int = 64,
                 bus_timeout_cycles: int = DEFAULT_BUS_TIMEOUT_CYCLES) -> None:
        if bus_timeout_cycles < 0:
            raise ValueError('bus_timeout_cycles must be non-negative')
        self.bus_timeout_cycles = bus_timeout_cycles

        self.bus = WishboneMasterInterface(
            data_width=data_width,
            address_width=address_width,
            name='d_bus',
        )

        self.request_valid = Signal()
        self.request_ready = Signal()
        self.request_addr = Signal(address_width)
        self.request_width_bytes = Signal(4)
        self.request_write = Signal()
        self.request_store_value = Signal(data_width)

        self.response_valid = Signal()
        self.response_error = Signal()
        self.response_load_value = Signal(data_width)
        self.response_write = Signal()
        self.response_addr = Signal(address_width)
        self.active = Signal()
        self.bus_watchdog_timeout = Signal()

        self.state = Signal(2, init=V2LSUState.IDLE)

    def elaborate(self, platform):
        m = Module()

        latched_addr = Signal.like(self.request_addr)
        latched_width = Signal.like(self.request_width_bytes)
        latched_write = Signal()
        latched_store_value = Signal.like(self.request_store_value)
        first_data = Signal(64)
        beat_started = Signal()

        byte_offset = Signal(3)
        base_sel = Signal(8)
        shifted_sel = Signal(16)
        split_needed = Signal()
        first_beat_sel = Signal(8)
        second_beat_sel = Signal(8)
        shifted_dat_w = Signal(128)
        first_beat_dat_w = Signal(64)
        second_beat_dat_w = Signal(64)
        word_aligned_addr = Signal.like(self.request_addr)
        next_word_addr = Signal.like(self.request_addr)
        single_read_data = Signal(64)
        combined_read_data = Signal(64)

        bus_active = Signal()
        watchdog_fire = Signal()
        effective_err = Signal()

        m.d.comb += [
            bus_active.eq(self.state != V2LSUState.IDLE),
            effective_err.eq(self.bus.err | watchdog_fire),
            self.bus_watchdog_timeout.eq(watchdog_fire),
        ]

        if self.bus_timeout_cycles > 0:
            watchdog_counter = Signal(range(self.bus_timeout_cycles + 1))
            m.d.comb += watchdog_fire.eq(
                bus_active & (watchdog_counter == self.bus_timeout_cycles)
            )
            with m.If(bus_active & ~self.bus.ack & ~self.bus.err & ~watchdog_fire):
                m.d.sync += watchdog_counter.eq(watchdog_counter + 1)
            with m.Else():
                m.d.sync += watchdog_counter.eq(0)

        m.d.comb += [
            self.request_ready.eq(self.state == V2LSUState.IDLE),
            self.active.eq(self.state != V2LSUState.IDLE),
            self.response_valid.eq(0),
            self.response_error.eq(0),
            self.response_load_value.eq(0),
            self.response_write.eq(latched_write),
            self.response_addr.eq(latched_addr),
            byte_offset.eq(latched_addr[0:3]),
            # NOTE: default fall-through is 0xFF rather than 0x00. A Wishbone
            # transaction with sel=0 is legal but many LiteX peripherals
            # (including the UART CSR bridge on real hardware) will neither
            # ack nor err such a cycle, causing the LSU to hang until the
            # watchdog fires. Defaulting to a full-word select keeps the bus
            # well-formed even if ``latched_width`` is ever driven to an
            # unexpected value; the response-path masking below still applies
            # the architected width to the returned data.
            base_sel.eq(Mux(latched_width == 1, 0x01,
                        Mux(latched_width == 2, 0x03,
                        Mux(latched_width == 4, 0x0F,
                        Mux(latched_width == 8, 0xFF, 0xFF))))),
            word_aligned_addr.eq(latched_addr & Const(~0x7 & ((1 << len(self.request_addr)) - 1), len(self.request_addr))),
            next_word_addr.eq(word_aligned_addr + 8),
            first_beat_sel.eq(shifted_sel[0:8]),
            second_beat_sel.eq(shifted_sel[8:16]),
            first_beat_dat_w.eq(shifted_dat_w[0:64]),
            second_beat_dat_w.eq(shifted_dat_w[64:128]),
            split_needed.eq(shifted_sel[8:16] != 0),
            self.bus.adr.eq(Mux(self.state == V2LSUState.SECOND, next_word_addr, word_aligned_addr)),
            self.bus.dat_w.eq(Mux(self.state == V2LSUState.SECOND, second_beat_dat_w, first_beat_dat_w)),
            self.bus.sel.eq(Mux(self.state == V2LSUState.SECOND, second_beat_sel, first_beat_sel)),
            self.bus.cyc.eq(self.state != V2LSUState.IDLE),
            self.bus.stb.eq(self.state != V2LSUState.IDLE),
            self.bus.we.eq(latched_write & (self.state != V2LSUState.IDLE)),
            self.bus.cti.eq(0),
            self.bus.bte.eq(0),
        ]

        with m.Switch(byte_offset):
            for offset in range(8):
                with m.Case(offset):
                    m.d.comb += [
                        shifted_sel.eq(base_sel << offset),
                        shifted_dat_w.eq(latched_store_value << (offset * 8)),
                    ]

        with m.Switch(byte_offset):
            for offset in range(8):
                with m.Case(offset):
                    if offset == 0:
                        m.d.comb += single_read_data.eq(self.bus.dat_r)
                        m.d.comb += combined_read_data.eq(first_data)
                    else:
                        m.d.comb += [
                            single_read_data.eq(Cat(self.bus.dat_r[offset * 8:64], Const(0, offset * 8))),
                            combined_read_data.eq(Cat(first_data[offset * 8:64], self.bus.dat_r[0:offset * 8])),
                        ]

        with m.If((self.state == V2LSUState.IDLE) & self.request_valid):
            m.d.sync += [
                latched_addr.eq(self.request_addr),
                latched_width.eq(self.request_width_bytes),
                latched_write.eq(self.request_write),
                latched_store_value.eq(self.request_store_value),
                beat_started.eq(0),
                self.state.eq(V2LSUState.FIRST),
            ]
        with m.Elif(self.state == V2LSUState.FIRST):
            with m.If(~beat_started):
                m.d.sync += beat_started.eq(1)
            with m.Elif(effective_err):
                m.d.comb += [
                    self.response_valid.eq(1),
                    self.response_error.eq(1),
                ]
                m.d.sync += self.state.eq(V2LSUState.IDLE)
            with m.Elif(self.bus.ack):
                with m.If(split_needed):
                    m.d.sync += [
                        first_data.eq(self.bus.dat_r),
                        beat_started.eq(0),
                        self.state.eq(V2LSUState.SECOND),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.response_valid.eq(1),
                        self.response_load_value.eq(Mux(latched_width == 1, single_read_data & 0xFF,
                                                    Mux(latched_width == 2, single_read_data & 0xFFFF,
                                                    Mux(latched_width == 4, single_read_data & 0xFFFFFFFF,
                                                    single_read_data)))),
                    ]
                    m.d.sync += self.state.eq(V2LSUState.IDLE)
        with m.Elif(self.state == V2LSUState.SECOND):
            with m.If(~beat_started):
                m.d.sync += beat_started.eq(1)
            with m.Elif(effective_err):
                m.d.comb += [
                    self.response_valid.eq(1),
                    self.response_error.eq(1),
                ]
                m.d.sync += self.state.eq(V2LSUState.IDLE)
            with m.Elif(self.bus.ack):
                m.d.comb += [
                    self.response_valid.eq(1),
                    self.response_load_value.eq(Mux(latched_width == 1, combined_read_data & 0xFF,
                                                Mux(latched_width == 2, combined_read_data & 0xFFFF,
                                                Mux(latched_width == 4, combined_read_data & 0xFFFFFFFF,
                                                combined_read_data)))),
                ]
                m.d.sync += self.state.eq(V2LSUState.IDLE)

        return m


__all__ = ['Little64V2LSU', 'V2LSUState']