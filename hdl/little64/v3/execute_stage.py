from __future__ import annotations

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from .helpers import (
    flag_value,
    instruction_gp_imm4,
    instruction_gp_opcode,
    instruction_ldi_imm8,
    instruction_ldi_shift,
    instruction_ls_offset2,
    instruction_ls_opcode,
    instruction_rd,
    instruction_rs1,
    instruction_top2,
    instruction_top3,
    ls_condition,
    sign_extend,
)
from ..isa import CPU_CONTROL_USER_MODE, GPOpcode, LSOpcode, TrapVector
from .bundles import V3ExecuteOutputs


class Little64V3ExecuteStage(Elaboratable):
    """Combinational execute stage for the current X-stage instruction."""

    def __init__(self) -> None:
        self.valid = Signal()
        self.instruction = Signal(16)
        self.pc = Signal(64)
        self.operand_a = Signal(64)
        self.operand_b = Signal(64)
        self.flags = Signal(3)
        self.cpu_control = Signal(64)
        self.interrupt_epc = Signal(64)
        self.interrupt_eflags = Signal(64)
        self.interrupt_cpu_control = Signal(64)
        self.ll_reservation_valid = Signal()
        self.ll_reservation_addr = Signal(64)

        self.special_read_data = Signal(64)
        self.special_read_access_fault = Signal()
        self.special_write_access_fault = Signal()

        self.special_read_selector = Signal(16)
        self.special_write_stb = Signal()
        self.special_write_selector = Signal(16)
        self.special_write_data = Signal(64)

        self.post_increment_pc = Signal(64)
        self.outputs = V3ExecuteOutputs()

    def elaborate(self, platform):
        m = Module()

        execute_rd = instruction_rd(self.instruction)
        execute_rs1 = instruction_rs1(self.instruction)
        execute_top2 = instruction_top2(self.instruction)
        execute_top3 = instruction_top3(self.instruction)
        execute_gp_opcode = instruction_gp_opcode(self.instruction)
        execute_imm4 = instruction_gp_imm4(self.instruction)
        execute_ldi_shift = instruction_ldi_shift(self.instruction)
        execute_ldi_imm8 = instruction_ldi_imm8(self.instruction)
        execute_ls_offset2 = instruction_ls_offset2(self.instruction)
        execute_ls_opcode = instruction_ls_opcode(self.instruction)

        execute_jump_rel10 = Signal(64)
        execute_jump_rel13 = Signal(64)
        execute_ls_jump_target = Signal(64)
        execute_ls_pc_effective = Signal(64)
        execute_ls_pc_push_addr = Signal(64)
        execute_ls_jump_taken = Signal()
        ls_rd_value = Signal(64)
        ls_rs1_value = Signal(64)
        ls_addr = Signal(64)
        ls_pc_rel6 = Signal(64)
        sign_extended_ldi = Signal(64)
        ldi_value = Signal(64)
        shift_index = Signal(7)
        sum_value = Signal(65)
        sub_value = Signal(64)
        load_width = Signal(4)
        store_width = Signal(4)

        sll_results = Array([
            self.operand_a if amount == 0 else Const(0, 64) if amount == 64 else (self.operand_a << amount)[:64]
            for amount in range(65)
        ])
        sll_carries = Array([
            Const(0, 1) if amount in (0, 64) else ((self.operand_a >> (64 - amount)) != 0)
            for amount in range(65)
        ])
        srl_results = Array([
            self.operand_a if amount == 0 else Const(0, 64) if amount == 64 else self.operand_a >> amount
            for amount in range(65)
        ])
        srl_carries = Array([
            Const(0, 1) if amount in (0, 64) else (((self.operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])
        sra_results = Array([
            self.operand_a if amount == 0 else
            Mux(self.operand_a[63], Const(0xFFFFFFFFFFFFFFFF, 64), Const(0, 64)) if amount == 64 else
            (self.operand_a.as_signed() >> amount).as_unsigned()
            for amount in range(65)
        ])
        sra_carries = Array([
            Const(0, 1) if amount in (0, 64) else (((self.operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])
        slli_results = Array([
            self.operand_a if amount == 0 else (self.operand_a << amount)[:64]
            for amount in range(16)
        ])
        slli_carries = Array([
            Const(0, 1) if amount == 0 else ((self.operand_a >> (64 - amount)) != 0)
            for amount in range(16)
        ])
        srli_results = Array([
            self.operand_a if amount == 0 else self.operand_a >> amount
            for amount in range(16)
        ])
        srli_carries = Array([
            Const(0, 1) if amount == 0 else (((self.operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])
        srai_results = Array([
            self.operand_a if amount == 0 else (self.operand_a.as_signed() >> amount).as_unsigned()
            for amount in range(16)
        ])
        srai_carries = Array([
            Const(0, 1) if amount == 0 else (((self.operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])

        m.d.comb += [
            self.post_increment_pc.eq(self.pc + 2),
            self.special_read_selector.eq(self.operand_b[:16]),
            self.special_write_stb.eq(self.valid & (execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.SSR)),
            self.special_write_selector.eq(self.operand_b[:16]),
            self.special_write_data.eq(self.operand_a),
            ls_rd_value.eq(Mux(execute_rd == 15, self.post_increment_pc, self.operand_a)),
            ls_rs1_value.eq(Mux(execute_rs1 == 15, self.post_increment_pc, self.operand_b)),
            ls_addr.eq(ls_rs1_value + (execute_ls_offset2 << 1)),
            ls_pc_rel6.eq(sign_extend(self.instruction[4:10], 6, 64)),
            execute_jump_rel10.eq(sign_extend(self.instruction[:10], 10, 64) << 1),
            execute_jump_rel13.eq(sign_extend(self.instruction[:13], 13, 64) << 1),
            execute_ls_pc_effective.eq(self.post_increment_pc + (ls_pc_rel6 << 1)),
            execute_ls_jump_target.eq(self.post_increment_pc + execute_jump_rel10),
            execute_ls_pc_push_addr.eq(self.operand_a - 8),
            execute_ls_jump_taken.eq(ls_condition(self.flags, execute_ls_opcode)),
            shift_index.eq(Mux(self.operand_b >= 64, 64, self.operand_b[:7])),
            sum_value.eq(self.operand_a + self.operand_b),
            sub_value.eq(self.operand_a - self.operand_b),
            sign_extended_ldi.eq(sign_extend(Cat(Const(0, 24), execute_ldi_imm8), 32, 64)),
            load_width.eq(Mux(execute_ls_opcode == LSOpcode.BYTE_LOAD, 1,
                          Mux(execute_ls_opcode == LSOpcode.SHORT_LOAD, 2,
                          Mux(execute_ls_opcode == LSOpcode.WORD_LOAD, 4, 8)))),
            store_width.eq(Mux(execute_ls_opcode == LSOpcode.BYTE_STORE, 1,
                           Mux(execute_ls_opcode == LSOpcode.SHORT_STORE, 2,
                           Mux(execute_ls_opcode == LSOpcode.WORD_STORE, 4, 8)))),
            self.outputs.reg_write.eq(0),
            self.outputs.reg_index.eq(execute_rd),
            self.outputs.reg_value.eq(0),
            self.outputs.flags_write.eq(0),
            self.outputs.flags_value.eq(self.flags),
            self.outputs.cpu_control_write.eq(0),
            self.outputs.cpu_control_value.eq(0),
            self.outputs.next_pc.eq(self.post_increment_pc),
            self.outputs.halt.eq(0),
            self.outputs.lockup.eq(0),
            self.outputs.trap.eq(0),
            self.outputs.trap_cause.eq(0),
            self.outputs.clear_reservation.eq(0),
            self.outputs.memory_start.eq(0),
            self.outputs.memory_addr.eq(0),
            self.outputs.memory_width_bytes.eq(0),
            self.outputs.memory_write.eq(0),
            self.outputs.memory_store_value.eq(0),
            self.outputs.memory_reg_write.eq(0),
            self.outputs.memory_reg_index.eq(execute_rd),
            self.outputs.memory_flags_write.eq(0),
            self.outputs.memory_flags_value.eq(self.flags),
            self.outputs.memory_set_reservation.eq(0),
            self.outputs.memory_reservation_addr.eq(0),
            self.outputs.memory_next_pc.eq(self.post_increment_pc),
            self.outputs.memory_post_reg_write.eq(0),
            self.outputs.memory_post_reg_index.eq(0),
            self.outputs.memory_post_reg_value.eq(0),
            self.outputs.memory_post_reg_delta.eq(0),
            self.outputs.memory_post_reg_use_load_result.eq(0),
            self.outputs.memory_chain_store.eq(0),
            self.outputs.memory_chain_store_addr.eq(0),
            self.outputs.memory_chain_store_use_load_result.eq(0),
            self.outputs.memory_chain_store_value.eq(0),
        ]

        m.d.comb += ldi_value.eq(self.operand_a)
        with m.Switch(execute_ldi_shift):
            with m.Case(0):
                m.d.comb += ldi_value.eq(execute_ldi_imm8)
            with m.Case(1):
                m.d.comb += ldi_value.eq(self.operand_a | (execute_ldi_imm8 << 8))
            with m.Case(2):
                m.d.comb += ldi_value.eq(self.operand_a | (execute_ldi_imm8 << 16))
            with m.Case(3):
                m.d.comb += ldi_value.eq(self.operand_a | sign_extended_ldi)

        with m.If(self.valid):
            with m.If(execute_top2 == 0b10):
                m.d.comb += [
                    self.outputs.reg_write.eq(1),
                    self.outputs.reg_value.eq(ldi_value),
                ]
            with m.Elif(execute_top2 == 0b00):
                with m.Switch(execute_ls_opcode):
                    with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(ls_addr),
                            self.outputs.memory_width_bytes.eq(load_width),
                            self.outputs.memory_reg_write.eq(1),
                            self.outputs.memory_reg_index.eq(execute_rd),
                        ]
                    with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(ls_addr),
                            self.outputs.memory_width_bytes.eq(store_width),
                            self.outputs.memory_write.eq(1),
                            self.outputs.memory_store_value.eq(ls_rd_value),
                        ]
                    with m.Case(LSOpcode.PUSH):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(ls_rd_value - 8),
                            self.outputs.memory_width_bytes.eq(8),
                            self.outputs.memory_write.eq(1),
                            self.outputs.memory_store_value.eq(ls_rs1_value),
                            self.outputs.memory_post_reg_write.eq(1),
                            self.outputs.memory_post_reg_index.eq(execute_rd),
                            self.outputs.memory_post_reg_value.eq(ls_rd_value - 8),
                        ]
                    with m.Case(LSOpcode.POP):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(ls_rd_value),
                            self.outputs.memory_width_bytes.eq(8),
                            self.outputs.memory_reg_write.eq(1),
                            self.outputs.memory_reg_index.eq(execute_rs1),
                            self.outputs.memory_post_reg_write.eq(1),
                            self.outputs.memory_post_reg_index.eq(execute_rd),
                            self.outputs.memory_post_reg_value.eq(ls_rd_value + 8),
                            self.outputs.memory_post_reg_delta.eq(8),
                            self.outputs.memory_post_reg_use_load_result.eq(execute_rd == execute_rs1),
                        ]
                    with m.Case(LSOpcode.MOVE):
                        m.d.comb += [
                            self.outputs.reg_write.eq(1),
                            self.outputs.reg_value.eq(ls_addr),
                            self.outputs.next_pc.eq(Mux(execute_rd == 15, ls_addr, self.post_increment_pc)),
                        ]
                    with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                        m.d.comb += [
                            self.outputs.reg_write.eq(execute_ls_jump_taken),
                            self.outputs.reg_value.eq(ls_addr),
                            self.outputs.next_pc.eq(Mux(execute_ls_jump_taken & (execute_rd == 15), ls_addr, self.post_increment_pc)),
                        ]
                    with m.Default():
                        m.d.comb += self.outputs.lockup.eq(1)
            with m.Elif(execute_top2 == 0b01):
                with m.Switch(execute_ls_opcode):
                    with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(execute_ls_pc_effective),
                            self.outputs.memory_width_bytes.eq(load_width),
                            self.outputs.memory_reg_write.eq(1),
                            self.outputs.memory_reg_index.eq(execute_rd),
                        ]
                    with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(execute_ls_pc_effective),
                            self.outputs.memory_width_bytes.eq(store_width),
                            self.outputs.memory_write.eq(1),
                            self.outputs.memory_store_value.eq(self.operand_a),
                        ]
                    with m.Case(LSOpcode.PUSH):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(execute_ls_pc_effective),
                            self.outputs.memory_width_bytes.eq(8),
                            self.outputs.memory_post_reg_write.eq(1),
                            self.outputs.memory_post_reg_index.eq(execute_rd),
                            self.outputs.memory_post_reg_value.eq(execute_ls_pc_push_addr),
                            self.outputs.memory_chain_store.eq(1),
                            self.outputs.memory_chain_store_addr.eq(execute_ls_pc_push_addr),
                            self.outputs.memory_chain_store_use_load_result.eq(1),
                        ]
                    with m.Case(LSOpcode.POP):
                        m.d.comb += [
                            self.outputs.memory_start.eq(1),
                            self.outputs.memory_addr.eq(self.operand_a),
                            self.outputs.memory_width_bytes.eq(8),
                            self.outputs.memory_post_reg_write.eq(1),
                            self.outputs.memory_post_reg_index.eq(execute_rd),
                            self.outputs.memory_post_reg_value.eq(self.operand_a + 8),
                            self.outputs.memory_chain_store.eq(1),
                            self.outputs.memory_chain_store_addr.eq(execute_ls_pc_effective),
                            self.outputs.memory_chain_store_use_load_result.eq(1),
                        ]
                    with m.Case(LSOpcode.MOVE):
                        m.d.comb += [
                            self.outputs.reg_write.eq(1),
                            self.outputs.reg_value.eq(execute_ls_pc_effective),
                            self.outputs.next_pc.eq(Mux(execute_rd == 15, execute_ls_pc_effective, self.post_increment_pc)),
                        ]
                    with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                        pass
                    with m.Default():
                        m.d.comb += self.outputs.lockup.eq(1)
                with m.Switch(execute_ls_opcode):
                    with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                        m.d.comb += self.outputs.next_pc.eq(Mux(execute_ls_jump_taken, execute_ls_jump_target, self.post_increment_pc))
            with m.Else():
                with m.Switch(execute_top3):
                    with m.Case(0b111):
                        m.d.comb += self.outputs.next_pc.eq(self.post_increment_pc + execute_jump_rel13)
                    with m.Case(0b110):
                        with m.Switch(execute_gp_opcode):
                            with m.Case(GPOpcode.ADD):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(sum_value[:64]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(sum_value[:64], sum_value[64])),
                                ]
                            with m.Case(GPOpcode.SUB):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(sub_value),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(sub_value, self.operand_b > self.operand_a)),
                                ]
                            with m.Case(GPOpcode.TEST):
                                m.d.comb += [
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(sub_value, self.operand_b > self.operand_a)),
                                ]
                            with m.Case(GPOpcode.AND):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(self.operand_a & self.operand_b),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(self.operand_a & self.operand_b, 0)),
                                ]
                            with m.Case(GPOpcode.OR):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(self.operand_a | self.operand_b),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(self.operand_a | self.operand_b, 0)),
                                ]
                            with m.Case(GPOpcode.XOR):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(self.operand_a ^ self.operand_b),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(self.operand_a ^ self.operand_b, 0)),
                                ]
                            with m.Case(GPOpcode.SLL):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(sll_results[shift_index]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(sll_results[shift_index], sll_carries[shift_index])),
                                ]
                            with m.Case(GPOpcode.SRL):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(srl_results[shift_index]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(srl_results[shift_index], srl_carries[shift_index])),
                                ]
                            with m.Case(GPOpcode.SRA):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(sra_results[shift_index]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(sra_results[shift_index], sra_carries[shift_index])),
                                ]
                            with m.Case(GPOpcode.SLLI):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(slli_results[execute_imm4]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(slli_results[execute_imm4], slli_carries[execute_imm4])),
                                ]
                            with m.Case(GPOpcode.SRLI):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(srli_results[execute_imm4]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(srli_results[execute_imm4], srli_carries[execute_imm4])),
                                ]
                            with m.Case(GPOpcode.SRAI):
                                m.d.comb += [
                                    self.outputs.reg_write.eq(1),
                                    self.outputs.reg_value.eq(srai_results[execute_imm4]),
                                    self.outputs.flags_write.eq(1),
                                    self.outputs.flags_value.eq(flag_value(srai_results[execute_imm4], srai_carries[execute_imm4])),
                                ]
                            with m.Case(GPOpcode.LSR):
                                with m.If(self.special_read_access_fault):
                                    m.d.comb += [
                                        self.outputs.trap.eq(1),
                                        self.outputs.trap_cause.eq(TrapVector.PRIVILEGED_INSTRUCTION),
                                    ]
                                with m.Else():
                                    m.d.comb += [
                                        self.outputs.reg_write.eq(1),
                                        self.outputs.reg_value.eq(self.special_read_data),
                                    ]
                            with m.Case(GPOpcode.LLR):
                                m.d.comb += [
                                    self.outputs.memory_start.eq(1),
                                    self.outputs.memory_addr.eq(self.operand_b),
                                    self.outputs.memory_width_bytes.eq(8),
                                    self.outputs.memory_reg_write.eq(1),
                                    self.outputs.memory_reg_index.eq(execute_rd),
                                    self.outputs.memory_set_reservation.eq(1),
                                    self.outputs.memory_reservation_addr.eq(self.operand_b),
                                ]
                            with m.Case(GPOpcode.SCR):
                                with m.If(self.ll_reservation_valid & (self.ll_reservation_addr == self.operand_b)):
                                    m.d.comb += [
                                        self.outputs.memory_start.eq(1),
                                        self.outputs.memory_addr.eq(self.operand_b),
                                        self.outputs.memory_width_bytes.eq(8),
                                        self.outputs.memory_write.eq(1),
                                        self.outputs.memory_store_value.eq(self.operand_a),
                                        self.outputs.memory_flags_write.eq(1),
                                        self.outputs.memory_flags_value.eq(Cat(Const(1, 1), self.flags[1:3])),
                                    ]
                                with m.Else():
                                    m.d.comb += [
                                        self.outputs.flags_write.eq(1),
                                        self.outputs.flags_value.eq(Cat(Const(0, 1), self.flags[1:3])),
                                        self.outputs.clear_reservation.eq(1),
                                    ]
                            with m.Case(GPOpcode.SSR):
                                with m.If(self.special_write_access_fault):
                                    m.d.comb += [
                                        self.outputs.trap.eq(1),
                                        self.outputs.trap_cause.eq(TrapVector.PRIVILEGED_INSTRUCTION),
                                    ]
                            with m.Case(GPOpcode.SYSCALL):
                                m.d.comb += [
                                    self.outputs.trap.eq(1),
                                    self.outputs.trap_cause.eq(
                                        Mux(
                                            (self.cpu_control & CPU_CONTROL_USER_MODE) != 0,
                                            TrapVector.SYSCALL,
                                            TrapVector.SYSCALL_FROM_SUPERVISOR,
                                        )
                                    ),
                                ]
                            with m.Case(GPOpcode.IRET):
                                with m.If((self.cpu_control & CPU_CONTROL_USER_MODE) != 0):
                                    m.d.comb += [
                                        self.outputs.trap.eq(1),
                                        self.outputs.trap_cause.eq(TrapVector.PRIVILEGED_INSTRUCTION),
                                    ]
                                with m.Else():
                                    m.d.comb += [
                                        self.outputs.flags_write.eq(1),
                                        self.outputs.flags_value.eq(self.interrupt_eflags[:3]),
                                        self.outputs.cpu_control_write.eq(1),
                                        self.outputs.cpu_control_value.eq(self.interrupt_cpu_control),
                                        self.outputs.next_pc.eq(self.interrupt_epc),
                                    ]
                            with m.Case(GPOpcode.STOP):
                                with m.If((self.cpu_control & CPU_CONTROL_USER_MODE) != 0):
                                    m.d.comb += [
                                        self.outputs.trap.eq(1),
                                        self.outputs.trap_cause.eq(TrapVector.PRIVILEGED_INSTRUCTION),
                                    ]
                                with m.Else():
                                    m.d.comb += self.outputs.halt.eq(1)
                            with m.Default():
                                m.d.comb += [
                                    self.outputs.trap.eq(1),
                                    self.outputs.trap_cause.eq(TrapVector.INVALID_INSTRUCTION),
                                ]
                    with m.Default():
                        m.d.comb += [
                            self.outputs.trap.eq(1),
                            self.outputs.trap_cause.eq(TrapVector.INVALID_INSTRUCTION),
                        ]

        return m


__all__ = ['Little64V3ExecuteStage']