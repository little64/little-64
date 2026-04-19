from __future__ import annotations

from amaranth import Elaboratable, Module, Mux, Signal

from .bundles import V3RetireStageState


class Little64V3MemoryStage(Elaboratable):
    """Combinational LSU-backed memory stage for the current M-stage entry."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.request_started = Signal()
        self.addr = Signal(64)
        self.width_bytes = Signal(4)
        self.write = Signal()
        self.store_value = Signal(64)
        self.reg_write = Signal()
        self.reg_index = Signal(4)
        self.flags_write = Signal()
        self.flags_value = Signal(3)
        self.set_reservation = Signal()
        self.reservation_addr = Signal(64)
        self.next_pc = Signal(64)
        self.commit_pc = Signal(64)
        self.post_reg_write = Signal()
        self.post_reg_index = Signal(4)
        self.post_reg_value = Signal(64)
        self.post_reg_delta = Signal(64)
        self.post_reg_use_load_result = Signal()
        self.chain_store = Signal()
        self.chain_store_addr = Signal(64)
        self.chain_store_use_load_result = Signal()
        self.chain_store_value = Signal(64)

        self.lsu_request_ready = Signal()
        self.lsu_response_valid = Signal()
        self.lsu_response_error = Signal()
        self.lsu_response_load_value = Signal(64)

        self.lsu_request_valid = Signal()
        self.lsu_request_addr = Signal(64)
        self.lsu_request_width_bytes = Signal(4)
        self.lsu_request_write = Signal()
        self.lsu_request_store_value = Signal(64)
        self.start_request = Signal()
        self.complete = Signal()
        self.final_response = Signal()
        self.chain_continue = Signal()
        self.next_chain_addr = Signal(64)
        self.next_chain_store_value = Signal(64)
        self.result = V3RetireStageState()

    def elaborate(self, platform):
        m = Module()

        response_post_value = Signal(64)
        response_next_pc = Signal(64)

        m.d.comb += [
            self.lsu_request_valid.eq(self.valid & ~self.request_started),
            self.lsu_request_addr.eq(self.addr),
            self.lsu_request_width_bytes.eq(self.width_bytes),
            self.lsu_request_write.eq(self.write),
            self.lsu_request_store_value.eq(self.store_value),
            self.start_request.eq(self.valid & ~self.request_started & self.lsu_request_ready),
            self.complete.eq(self.valid & self.lsu_response_valid),
            self.final_response.eq(self.complete & ~self.chain_store),
            self.chain_continue.eq(self.complete & self.chain_store & ~self.lsu_response_error),
            self.next_chain_addr.eq(self.chain_store_addr),
            self.next_chain_store_value.eq(
                Mux(
                    self.chain_store_use_load_result,
                    self.lsu_response_load_value,
                    self.chain_store_value,
                )
            ),
            response_post_value.eq(
                Mux(
                    self.post_reg_use_load_result,
                    self.lsu_response_load_value + self.post_reg_delta,
                    self.post_reg_value,
                )
            ),
            response_next_pc.eq(
                Mux(
                    self.post_reg_write & (self.post_reg_index == 15),
                    response_post_value,
                    Mux(
                        self.reg_write & (self.reg_index == 15),
                        self.lsu_response_load_value,
                        self.next_pc,
                    ),
                )
            ),
            self.result.valid.eq(self.final_response & ~self.lsu_response_error),
            self.result.flags_write.eq(self.flags_write),
            self.result.flags_value.eq(self.flags_value),
            self.result.next_pc.eq(response_next_pc),
            self.result.commit.eq(self.final_response & ~self.lsu_response_error),
            self.result.commit_pc.eq(self.commit_pc),
            self.result.halt.eq(0),
            self.result.lockup.eq(0),
            self.result.trap.eq(0),
            self.result.trap_cause.eq(0),
        ]

        with m.If(self.post_reg_write):
            with m.If(self.reg_write):
                with m.If(self.post_reg_index == self.reg_index):
                    m.d.comb += [
                        self.result.reg_write.eq(1),
                        self.result.reg_index.eq(self.reg_index),
                        self.result.reg_value.eq(response_post_value),
                        self.result.aux_reg_write.eq(0),
                        self.result.aux_reg_index.eq(0),
                        self.result.aux_reg_value.eq(0),
                    ]
                with m.Else():
                    m.d.comb += [
                        self.result.reg_write.eq(1),
                        self.result.reg_index.eq(self.reg_index),
                        self.result.reg_value.eq(self.lsu_response_load_value),
                        self.result.aux_reg_write.eq(1),
                        self.result.aux_reg_index.eq(self.post_reg_index),
                        self.result.aux_reg_value.eq(response_post_value),
                    ]
            with m.Else():
                m.d.comb += [
                    self.result.reg_write.eq(1),
                    self.result.reg_index.eq(self.post_reg_index),
                    self.result.reg_value.eq(response_post_value),
                    self.result.aux_reg_write.eq(0),
                    self.result.aux_reg_index.eq(0),
                    self.result.aux_reg_value.eq(0),
                ]
        with m.Else():
            m.d.comb += [
                self.result.reg_write.eq(self.reg_write),
                self.result.reg_index.eq(self.reg_index),
                self.result.reg_value.eq(self.lsu_response_load_value),
                self.result.aux_reg_write.eq(0),
                self.result.aux_reg_index.eq(0),
                self.result.aux_reg_value.eq(0),
            ]

        return m


__all__ = ['Little64V3MemoryStage']