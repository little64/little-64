from __future__ import annotations

from amaranth import Elaboratable, Module, Signal


class Little64V3RetireStage(Elaboratable):
    """Decode retire-stage entries into architected writeback actions."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.reg_write = Signal()
        self.reg_index = Signal(4)
        self.reg_value = Signal(64)
        self.aux_reg_write = Signal()
        self.aux_reg_index = Signal(4)
        self.aux_reg_value = Signal(64)
        self.flags_write = Signal()
        self.flags_value = Signal(3)
        self.cpu_control_write = Signal()
        self.cpu_control_value = Signal(64)
        self.next_pc = Signal(64)
        self.commit = Signal()
        self.commit_pc = Signal(64)
        self.halt = Signal()
        self.lockup = Signal()
        self.trap = Signal()
        self.trap_cause = Signal(64)

        self.write_reg = Signal()
        self.write_reg_index = Signal(4)
        self.write_reg_value = Signal(64)
        self.write_aux_reg = Signal()
        self.write_aux_reg_index = Signal(4)
        self.write_aux_reg_value = Signal(64)
        self.write_flags = Signal()
        self.write_flags_value = Signal(3)
        self.write_cpu_control = Signal()
        self.write_cpu_control_value = Signal(64)
        self.commit_valid = Signal()
        self.commit_valid_pc = Signal(64)
        self.halt_request = Signal()
        self.lockup_request = Signal()
        self.trap_request = Signal()
        self.trap_write = Signal()
        self.trap_cause_value = Signal(64)
        self.trap_pc_value = Signal(64)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.write_reg.eq(self.valid & self.reg_write),
            self.write_reg_index.eq(self.reg_index),
            self.write_reg_value.eq(self.reg_value),
            self.write_aux_reg.eq(self.valid & self.aux_reg_write),
            self.write_aux_reg_index.eq(self.aux_reg_index),
            self.write_aux_reg_value.eq(self.aux_reg_value),
            self.write_flags.eq(self.valid & self.flags_write),
            self.write_flags_value.eq(self.flags_value),
            self.write_cpu_control.eq(self.valid & self.cpu_control_write),
            self.write_cpu_control_value.eq(self.cpu_control_value),
            self.commit_valid.eq(self.valid & self.commit),
            self.commit_valid_pc.eq(self.commit_pc),
            self.halt_request.eq(self.valid & self.halt),
            self.lockup_request.eq(self.valid & self.lockup),
            self.trap_request.eq(self.valid & self.trap),
            self.trap_write.eq(self.valid & self.trap),
            self.trap_cause_value.eq(self.trap_cause),
            self.trap_pc_value.eq(self.commit_pc),
        ]

        return m


__all__ = ['Little64V3RetireStage']