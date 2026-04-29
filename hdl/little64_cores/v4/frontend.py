from __future__ import annotations

from math import log2

from amaranth import Array, Const, Elaboratable, Module, Mux, Signal

from ..wishbone import WishboneMasterInterface
from ..v3.frontend import DEFAULT_BUS_TIMEOUT_CYCLES, FETCH_LINE_MASK


class Little64V4FetchFrontend(Elaboratable):
    """V4 fetch frontend with a small direct-mapped multi-line I-cache.

    Interface is intentionally compatible with the V3 frontend so V4 core wiring
    can evolve independently without touching V3 sources.
    """

    def __init__(
        self,
        *,
        address_width: int = 64,
        data_width: int = 64,
        entries: int = 16,
        bus_timeout_cycles: int = DEFAULT_BUS_TIMEOUT_CYCLES,
    ) -> None:
        if bus_timeout_cycles < 0:
            raise ValueError('bus_timeout_cycles must be non-negative')
        if entries < 1 or entries & (entries - 1):
            raise ValueError('entries must be a power of two and at least 1')
        if data_width != 64:
            raise ValueError('Little64V4FetchFrontend expects 64-bit lines')

        self.bus_timeout_cycles = bus_timeout_cycles
        self.entries = entries
        self.index_bits = 0 if entries == 1 else int(log2(entries))
        self.line_offset_bits = 3
        self.line_number_width = address_width - self.line_offset_bits

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
        self.bus_watchdog_timeout = Signal()

        # Compatibility observability fields used by existing core logic.
        self.line_valid = Signal()
        self.line_base = Signal(64)
        self.line_data = Signal(data_width)

    def elaborate(self, platform):
        m = Module()

        valid_bits = [Signal(name=f'ife_valid_{index}') for index in range(self.entries)]
        tags = [Signal(self.line_number_width, name=f'ife_tag_{index}') for index in range(self.entries)]
        line_data = [Signal(64, name=f'ife_data_{index}') for index in range(self.entries)]

        line_base_requested = Signal(64)
        lookup_line = Signal(self.line_number_width)
        lookup_index = Signal(max(1, self.index_bits))
        lookup_tag = Signal(self.line_number_width)
        line_hit = Signal()
        hit_data = Signal(64)
        selected_line_data = Signal(64)

        request_valid = Signal()
        request_cancelled = Signal()
        request_line_base = Signal(64)
        request_line_number = Signal(self.line_number_width)
        request_index = Signal(max(1, self.index_bits))
        request_tag = Signal(self.line_number_width)
        request_is_prefetch = Signal()

        prefetch_valid = Signal()
        prefetch_base = Signal(64)
        prefetch_data = Signal(64)
        prefetch_hit = Signal()

        next_line_base = Signal(64)
        next_lookup_line = Signal(self.line_number_width)
        next_lookup_index = Signal(max(1, self.index_bits))
        next_lookup_tag = Signal(self.line_number_width)
        next_line_hit = Signal()
        prefetch_needed = Signal()

        bus_request_base = Signal(64)
        slot_index = Signal(2)
        instruction_words = Array([hit_data.word_select(index, 16) for index in range(4)])

        watchdog_fire = Signal()
        effective_err = Signal()

        m.d.comb += [
            line_base_requested.eq(self.pc & Const(FETCH_LINE_MASK, 64)),
            lookup_line.eq(line_base_requested[self.line_offset_bits:]),
            lookup_index.eq(0 if self.index_bits == 0 else lookup_line[:self.index_bits]),
            lookup_tag.eq(lookup_line),
            next_line_base.eq(line_base_requested + 8),
            next_lookup_line.eq(next_line_base[self.line_offset_bits:]),
            next_lookup_index.eq(0 if self.index_bits == 0 else next_lookup_line[:self.index_bits]),
            next_lookup_tag.eq(next_lookup_line),
            request_line_number.eq(request_line_base[self.line_offset_bits:]),
            request_index.eq(0 if self.index_bits == 0 else request_line_number[:self.index_bits]),
            request_tag.eq(request_line_number),
            line_hit.eq(Array(valid_bits)[lookup_index] & (Array(tags)[lookup_index] == lookup_tag)),
            next_line_hit.eq(Array(valid_bits)[next_lookup_index] & (Array(tags)[next_lookup_index] == next_lookup_tag)),
            prefetch_hit.eq(prefetch_valid & (prefetch_base == line_base_requested)),
            hit_data.eq(Array(line_data)[lookup_index]),
            selected_line_data.eq(Mux(prefetch_hit, prefetch_data, hit_data)),
            bus_request_base.eq(request_line_base),
            slot_index.eq(self.pc[1:3]),
            prefetch_needed.eq(
                (slot_index != 0) &
                ~request_valid &
                ~next_line_hit &
                ~(prefetch_valid & (prefetch_base == next_line_base))
            ),
            effective_err.eq(self.i_bus.err | watchdog_fire),
            self.bus_watchdog_timeout.eq(watchdog_fire),
            self.instruction_valid.eq(line_hit | prefetch_hit),
            self.instruction_word.eq(Array([selected_line_data.word_select(index, 16) for index in range(4)])[slot_index]),
            self.instruction_pc.eq(self.pc),
            self.fetch_phys_addr.eq(line_base_requested),
            self.fetch_error.eq(request_valid & ~request_cancelled & ~request_is_prefetch & effective_err),
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

        if self.bus_timeout_cycles > 0:
            watchdog_counter = Signal(range(self.bus_timeout_cycles + 1))
            m.d.comb += watchdog_fire.eq(
                request_valid & (watchdog_counter == self.bus_timeout_cycles)
            )
            with m.If(request_valid & ~self.i_bus.ack & ~self.i_bus.err & ~watchdog_fire):
                m.d.sync += watchdog_counter.eq(watchdog_counter + 1)
            with m.Else():
                m.d.sync += watchdog_counter.eq(0)

        with m.If(self.invalidate):
            # Conservative behavior: keep correctness by dropping all cached lines
            # on pipeline invalidation/redirect events.
            for valid_bit in valid_bits:
                m.d.sync += valid_bit.eq(0)
            m.d.sync += [
                request_cancelled.eq(request_valid),
                prefetch_valid.eq(0),
            ]

        # Promote prefetched data into the main cache when first used.
        with m.If(~self.invalidate & prefetch_hit & ~line_hit):
            with m.Switch(lookup_index):
                for index in range(self.entries):
                    with m.Case(index):
                        m.d.sync += [
                            valid_bits[index].eq(1),
                            tags[index].eq(lookup_tag),
                            line_data[index].eq(prefetch_data),
                        ]

        with m.If(request_valid & (self.i_bus.ack | effective_err)):
            m.d.sync += [
                request_valid.eq(0),
                request_cancelled.eq(0),
                request_is_prefetch.eq(0),
            ]
            with m.If(self.i_bus.ack & ~effective_err & ~request_cancelled & ~self.invalidate):
                with m.If(request_is_prefetch):
                    m.d.sync += [
                        prefetch_valid.eq(1),
                        prefetch_base.eq(request_line_base),
                        prefetch_data.eq(self.i_bus.dat_r),
                    ]
                with m.Else():
                    with m.Switch(request_index):
                        for index in range(self.entries):
                            with m.Case(index):
                                m.d.sync += [
                                    valid_bits[index].eq(1),
                                    tags[index].eq(request_tag),
                                    line_data[index].eq(self.i_bus.dat_r),
                                ]

        with m.If(~self.invalidate & self.update_line_valid & line_hit):
            with m.Switch(lookup_index):
                for index in range(self.entries):
                    with m.Case(index):
                        m.d.sync += line_data[index].eq(self.update_line_data)

        with m.If(~self.invalidate & ~(line_hit | prefetch_hit) & ~request_valid):
            # Demand misses take priority over speculative prefetch requests.
            m.d.sync += [
                request_valid.eq(1),
                request_cancelled.eq(0),
                request_line_base.eq(line_base_requested),
                request_is_prefetch.eq(0),
            ]
        with m.Elif(~self.invalidate & line_hit & prefetch_needed):
            # Speculatively fetch the next sequential line while consuming the
            # current one to reduce compulsory miss bubbles on streams.
            m.d.sync += [
                request_valid.eq(1),
                request_cancelled.eq(0),
                request_line_base.eq(next_line_base),
                request_is_prefetch.eq(1),
            ]

        # Keep these as stateful observability fields for compatibility with
        # shared test harness initialization behavior.
        with m.If(self.invalidate):
            m.d.sync += self.line_valid.eq(0)
        with m.Else():
            m.d.sync += [
                self.line_valid.eq(line_hit | prefetch_hit),
                self.line_base.eq(line_base_requested),
                self.line_data.eq(selected_line_data),
            ]

        return m


__all__ = [
    'Little64V4FetchFrontend',
]
