from __future__ import annotations

from enum import IntEnum

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from ..config import Little64CoreConfig
from ..mmu import (
    ACCESS_EXECUTE,
    ACCESS_READ,
    ACCESS_WRITE,
    AUX_SUBTYPE_CANONICAL,
    AUX_SUBTYPE_INVALID_NONLEAF,
    AUX_SUBTYPE_NO_VALID_PTE,
    AUX_SUBTYPE_NONE,
    AUX_SUBTYPE_PERMISSION,
    AUX_SUBTYPE_RESERVED_BIT,
    PTE_R,
    PTE_RESERVED_MASK,
    PTE_U,
    PTE_V,
    PTE_W,
    PTE_X,
)
from .cache import Little64V2LineCache
from .frontend import Little64V2FetchFrontend
from .helpers import (
    encode_aux,
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
    is_canonical39,
    ls_condition,
    sign_extend,
)
from .special_registers import Little64V2SpecialRegisterFile
from .tlb import Little64V2TLB
from ..isa import (
    CPU_CONTROL_CUR_INT_MASK,
    CPU_CONTROL_CUR_INT_SHIFT,
    CPU_CONTROL_IN_INTERRUPT,
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_USER_MODE,
    GPOpcode,
    LSOpcode,
    SpecialRegister,
    TrapVector,
)
from .lsu import Little64V2LSU


class V2PipelineState(IntEnum):
    RESET = 0
    FETCH_TRANSLATE = 1
    FETCH_REQUEST = 2
    DECODE = 3
    EXECUTE = 4
    MEM_TRANSLATE = 5
    MEMORY = 6
    WRITEBACK = 7
    WALK = 8
    WALK_PROCESS = 9
    INTERRUPT_VECTOR_TRANSLATE = 10
    INTERRUPT_VECTOR_LOAD = 11
    STALLED = 12
    HALTED = 13
    EXECUTE_COMPLETE = 14


class WalkResumeKind(IntEnum):
    FETCH = 0
    MEMORY = 1
    VECTOR = 2


class Little64V2Core(Elaboratable):
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.config = config or Little64CoreConfig(core_variant='v2')
        if self.config.core_variant != 'v2':
            raise ValueError('Little64V2Core requires Little64CoreConfig(core_variant="v2")')

        self.frontend = Little64V2FetchFrontend(
            data_width=self.config.instruction_bus_width,
            address_width=self.config.address_width,
            bus_timeout_cycles=self.config.bus_timeout_cycles,
        )
        self.lsu = Little64V2LSU(
            data_width=self.config.data_bus_width,
            address_width=self.config.address_width,
            bus_timeout_cycles=self.config.bus_timeout_cycles,
        )
        self.dcache = None
        if self.config.cache_topology != 'none':
            self.dcache = Little64V2LineCache(
                entries=4,
                data_width=self.config.data_bus_width,
                address_width=self.config.address_width,
            )

        self.i_bus = self.frontend.i_bus
        self.d_bus = self.lsu.bus
        self.irq_lines = Signal(self.config.irq_input_count)
        self.halted = Signal()
        self.locked_up = Signal()
        self.state = Signal(4, init=V2PipelineState.RESET)
        self.current_instruction = Signal(16)
        self.fetch_pc = Signal(64)
        self.fetch_phys_addr = Signal(64)
        self.commit_valid = Signal()
        self.commit_pc = Signal(64)
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)

        self.register_file = [
            Signal(64, name=f'r{index}', init=self.config.reset_vector if index == 15 else 0)
            for index in range(16)
        ]
        self.regs = Array(self.register_file)
        self.flags = Signal(3)
        self.ll_reservation_addr = Signal(64)
        self.ll_reservation_valid = Signal()

        self.decode_pc = Signal(64)
        self.execute_pc = Signal(64)
        self.execute_instruction = Signal(16)
        self.execute_operand_a = Signal(64)
        self.execute_operand_b = Signal(64)
        self.execute_complete_reg_write = Signal()
        self.execute_complete_reg_index = Signal(4)
        self.execute_complete_reg_value = Signal(64)
        self.execute_complete_flags_write = Signal()
        self.execute_complete_flag_result = Signal(64)
        self.execute_complete_flag_carry = Signal()
        self.execute_complete_next_pc = Signal(64)
        self.execute_complete_lockup = Signal()
        self.execute_complete_commit_pc = Signal(64)
        self.writeback_reg_write = Signal()
        self.writeback_reg_index = Signal(4)
        self.writeback_reg_value = Signal(64)
        self.writeback_aux_reg_write = Signal()
        self.writeback_aux_reg_index = Signal(4)
        self.writeback_aux_reg_value = Signal(64)
        self.writeback_flags_write = Signal()
        self.writeback_flags_value = Signal(3)
        self.writeback_next_pc = Signal(64)
        self.writeback_halt = Signal()
        self.writeback_lockup = Signal()
        self.writeback_commit_pc = Signal(64)

        self.lsu_started = Signal()
        self.mem_addr = Signal(64)
        self.mem_virtual_addr = Signal(64)
        self.mem_width_bytes = Signal(4)
        self.mem_write = Signal()
        self.mem_store_value = Signal(64)
        self.mem_rd = Signal(4)
        self.mem_next_pc = Signal(64)
        self.mem_fault_pc = Signal(64)
        self.mem_flags_write = Signal()
        self.mem_flags_value = Signal(3)
        self.mem_set_reservation = Signal()
        self.mem_reservation_addr = Signal(64)
        self.mem_post_reg_write = Signal()
        self.mem_post_reg_index = Signal(4)
        self.mem_post_reg_value = Signal(64)
        self.mem_post_reg_delta = Signal(64)
        self.mem_post_reg_use_load_result = Signal()
        self.mem_chain_store = Signal()
        self.mem_chain_store_addr = Signal(64)
        self.mem_chain_store_use_load_result = Signal()
        self.mem_chain_store_value = Signal(64)
        self.mem_result_value = Signal(64)
        self.translate_virtual_addr = Signal(64)
        self.translate_access = Signal(2)

        self.walk_virtual_addr = Signal(64)
        self.walk_table_addr = Signal(64)
        self.walk_level = Signal(2)
        self.walk_access = Signal(2)
        self.walk_resume_kind = Signal(2)
        self.walk_pte_latched = Signal(64)
        self.interrupt_entry_vector = Signal(64)
        self.interrupt_entry_epc = Signal(64)
        self.interrupt_vector_phys = Signal(64)

        self.special_regs = Little64V2SpecialRegisterFile(self.config)
        self.tlb = Little64V2TLB(entries=self.config.tlb_entries) if self.config.enable_tlb else None

    def elaborate(self, platform):
        m = Module()
        m.submodules.frontend = self.frontend
        m.submodules.lsu = self.lsu
        m.submodules.special_regs = self.special_regs
        if self.dcache is not None:
            m.submodules.dcache = self.dcache
        if self.tlb is not None:
            m.submodules.tlb = self.tlb

        current_pc = self.register_file[15]
        decode_rd = instruction_rd(self.current_instruction)
        decode_rs1 = instruction_rs1(self.current_instruction)
        execute_rd = instruction_rd(self.execute_instruction)
        execute_rs1 = instruction_rs1(self.execute_instruction)
        execute_top2 = instruction_top2(self.execute_instruction)
        execute_top3 = instruction_top3(self.execute_instruction)
        execute_gp_opcode = instruction_gp_opcode(self.execute_instruction)
        execute_imm4 = instruction_gp_imm4(self.execute_instruction)
        execute_ldi_shift = instruction_ldi_shift(self.execute_instruction)
        execute_ldi_imm8 = instruction_ldi_imm8(self.execute_instruction)
        execute_ls_offset2 = instruction_ls_offset2(self.execute_instruction)
        execute_ls_opcode = instruction_ls_opcode(self.execute_instruction)

        operand_a = Signal(64)
        operand_b = Signal(64)
        shift_index = Signal(7)
        execute_post_increment_pc = Signal(64)
        execute_jump_rel10 = Signal(64)
        execute_jump_rel13 = Signal(64)
        execute_ls_pc_effective = Signal(64)
        execute_ls_jump_target = Signal(64)
        execute_ls_pc_push_addr = Signal(64)
        execute_ujump_target = Signal(64)
        execute_ls_jump_taken = Signal()
        ls_rd_value = Signal(64)
        ls_rs1_value = Signal(64)
        ls_addr = Signal(64)
        ls_push_addr = Signal(64)
        ls_pc_rel6 = Signal(64)

        next_reg_write = Signal()
        next_reg_index = Signal(4)
        next_reg_value = Signal(64)
        next_flags_write = Signal()
        next_flags_value = Signal(3)
        next_pc = Signal(64)
        next_lockup = Signal()
        next_mem_start = Signal()
        next_mem_addr = Signal(64)
        next_mem_virtual_addr = Signal(64)
        next_mem_width_bytes = Signal(4)
        next_mem_write = Signal()
        next_mem_store_value = Signal(64)
        next_mem_rd = Signal(4)
        next_mem_next_pc = Signal(64)
        next_mem_fault_pc = Signal(64)
        next_mem_flags_write = Signal()
        next_mem_flags_value = Signal(3)
        next_mem_set_reservation = Signal()
        next_mem_reservation_addr = Signal(64)
        next_mem_post_reg_write = Signal()
        next_mem_post_reg_index = Signal(4)
        next_mem_post_reg_value = Signal(64)
        next_mem_post_reg_delta = Signal(64)
        next_mem_post_reg_use_load_result = Signal()
        next_mem_chain_store = Signal()
        next_mem_chain_store_addr = Signal(64)
        next_mem_chain_store_use_load_result = Signal()
        next_mem_chain_store_value = Signal(64)
        execute_starts_memory = Signal()
        gp_alu_valid = Signal()
        gp_alu_reg_write = Signal()
        gp_alu_result_value = Signal(64)
        gp_alu_flags_write = Signal()
        gp_alu_flag_result = Signal(64)
        gp_alu_flag_carry = Signal()
        gp_alu_flags_value = Signal(3)

        sum_value = Signal(65)
        sub_value = Signal(64)
        ldi_value = Signal(64)
        sign_extended_ldi = Signal(64)
        load_width = Signal(4)
        store_width = Signal(4)

        special_write_active = Signal()
        core_cpu_control_write = Signal()
        core_cpu_control_data = Signal(64)
        core_interrupt_cpu_control_write = Signal()
        core_interrupt_cpu_control_data = Signal(64)
        core_interrupt_epc_write = Signal()
        core_interrupt_epc_data = Signal(64)
        core_interrupt_eflags_write = Signal()
        core_interrupt_eflags_data = Signal(64)
        core_trap_write = Signal()
        core_trap_cause_data = Signal(64)
        core_trap_fault_addr_data = Signal(64)
        core_trap_access_data = Signal(64)
        core_trap_pc_data = Signal(64)
        core_trap_aux_data = Signal(64)

        paging_enabled = Signal()
        tlb_lookup_vaddr = Signal(64)
        tlb_lookup_hit = Signal()
        tlb_lookup_paddr = Signal(64)
        tlb_lookup_perm_read = Signal()
        tlb_lookup_perm_write = Signal()
        tlb_lookup_perm_execute = Signal()
        tlb_lookup_perm_user = Signal()
        tlb_perm_ok = Signal()
        tlb_user_ok = Signal()
        tlb_hit_ok = Signal()
        walk_index = Signal(9)
        walk_pte_addr = Signal(64)
        walk_pte = Signal(64)
        walk_is_leaf = Signal()
        walk_permission_ok = Signal()
        walk_user_ok = Signal()
        walk_reserved = Signal()
        walk_table_next = Signal(64)
        walk_page_shift = Signal(6)
        walk_page_mask = Signal(64)
        walk_page_base = Signal(64)
        walk_result_phys = Signal(64)

        current_interrupt_vector = Signal(64)
        irq_line_pending_mask = Signal(64)
        pending_irq_high = Signal(64)
        pending_irq_available = Signal()
        pending_irq_vector = Signal(64)
        can_preempt_pending_irq = Signal()

        lsu_request_valid = Signal()
        lsu_request_addr = Signal(64)
        lsu_request_width = Signal(4)
        lsu_request_write = Signal()
        lsu_request_store_value = Signal(64)

        reservation_end = Signal(64)
        write_end = Signal(64)
        store_overlaps_reservation = Signal()

        mem_byte_offset = Signal(3)
        mem_base_sel = Signal(8)
        mem_shifted_sel = Signal(8)
        mem_shifted_store_data = Signal(64)
        mem_single_line_access = Signal()
        dcache_lookup_hit = Signal()
        dcache_lookup_data = Signal(64)
        dcache_shifted_read = Signal(64)
        dcache_load_result = Signal(64)
        dcache_cacheable_load = Signal()
        dcache_cacheable_fill = Signal()
        dcache_store_update_valid = Signal()
        dcache_store_update_addr = Signal(64)
        dcache_store_update_sel = Signal(8)
        dcache_store_update_data = Signal(64)
        dcache_fill_valid = Signal()
        dcache_fill_addr = Signal(64)
        dcache_fill_data = Signal(64)
        dcache_flush_all = Signal()
        dcache_invalidate_valid = Signal()
        dcache_invalidate_addr = Signal(64)

        memory_response_result = Signal(64)
        memory_response_post_value = Signal(64)
        memory_response_next_pc = Signal(64)
        line_match = Signal()
        unified_line_update_value = Signal(64)

        sll_results = Array([
            operand_a if amount == 0 else Const(0, 64) if amount == 64 else (operand_a << amount)[:64]
            for amount in range(65)
        ])
        sll_carries = Array([
            Const(0, 1) if amount in (0, 64) else ((operand_a >> (64 - amount)) != 0)
            for amount in range(65)
        ])
        srl_results = Array([
            operand_a if amount == 0 else Const(0, 64) if amount == 64 else operand_a >> amount
            for amount in range(65)
        ])
        srl_carries = Array([
            Const(0, 1) if amount in (0, 64) else (((operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])
        sra_results = Array([
            operand_a if amount == 0 else
            Mux(operand_a[63], Const(0xFFFFFFFFFFFFFFFF, 64), Const(0, 64)) if amount == 64 else
            (operand_a.as_signed() >> amount).as_unsigned()
            for amount in range(65)
        ])
        sra_carries = Array([
            Const(0, 1) if amount in (0, 64) else (((operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])
        slli_results = Array([
            operand_a if amount == 0 else (operand_a << amount)[:64]
            for amount in range(16)
        ])
        slli_carries = Array([
            Const(0, 1) if amount == 0 else ((operand_a >> (64 - amount)) != 0)
            for amount in range(16)
        ])
        srli_results = Array([
            operand_a if amount == 0 else operand_a >> amount
            for amount in range(16)
        ])
        srli_carries = Array([
            Const(0, 1) if amount == 0 else (((operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])
        srai_results = Array([
            operand_a if amount == 0 else (operand_a.as_signed() >> amount).as_unsigned()
            for amount in range(16)
        ])
        srai_carries = Array([
            Const(0, 1) if amount == 0 else (((operand_a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])

        if self.tlb is not None:
            m.d.comb += [
                self.tlb.lookup_vaddr.eq(tlb_lookup_vaddr),
                self.tlb.flush_all.eq(self.special_regs.tlb_flush),
                self.tlb.fill_valid.eq(0),
                self.tlb.fill_vpage.eq(self.walk_virtual_addr[self.tlb.page_offset_bits:]),
                self.tlb.fill_ppage.eq(walk_result_phys[self.tlb.page_offset_bits:]),
                self.tlb.fill_perm_read.eq((walk_pte & PTE_R) != 0),
                self.tlb.fill_perm_write.eq((walk_pte & PTE_W) != 0),
                self.tlb.fill_perm_execute.eq((walk_pte & PTE_X) != 0),
                self.tlb.fill_perm_user.eq((walk_pte & PTE_U) != 0),
                tlb_lookup_hit.eq(self.tlb.lookup_hit),
                tlb_lookup_paddr.eq(self.tlb.lookup_paddr),
                tlb_lookup_perm_read.eq(self.tlb.lookup_perm_read),
                tlb_lookup_perm_write.eq(self.tlb.lookup_perm_write),
                tlb_lookup_perm_execute.eq(self.tlb.lookup_perm_execute),
                tlb_lookup_perm_user.eq(self.tlb.lookup_perm_user),
            ]
        else:
            m.d.comb += [
                tlb_lookup_hit.eq(0),
                tlb_lookup_paddr.eq(0),
                tlb_lookup_perm_read.eq(0),
                tlb_lookup_perm_write.eq(0),
                tlb_lookup_perm_execute.eq(0),
                tlb_lookup_perm_user.eq(0),
            ]

        if self.dcache is not None:
            m.d.comb += [
                self.dcache.lookup_addr.eq(self.mem_addr),
                self.dcache.fill_valid.eq(dcache_fill_valid),
                self.dcache.fill_addr.eq(dcache_fill_addr),
                self.dcache.fill_data.eq(dcache_fill_data),
                self.dcache.flush_all.eq(dcache_flush_all),
                self.dcache.invalidate_valid.eq(dcache_invalidate_valid),
                self.dcache.invalidate_addr.eq(dcache_invalidate_addr),
                self.dcache.store_update_valid.eq(dcache_store_update_valid),
                self.dcache.store_update_addr.eq(dcache_store_update_addr),
                self.dcache.store_update_sel.eq(dcache_store_update_sel),
                self.dcache.store_update_data.eq(dcache_store_update_data),
                dcache_lookup_hit.eq(self.dcache.lookup_hit),
                dcache_lookup_data.eq(self.dcache.lookup_data),
            ]
        else:
            m.d.comb += [
                dcache_lookup_hit.eq(0),
                dcache_lookup_data.eq(0),
            ]

        m.d.comb += [
            operand_a.eq(self.execute_operand_a),
            operand_b.eq(self.execute_operand_b),
            ls_rd_value.eq(Mux(execute_rd == 15, execute_post_increment_pc, operand_a)),
            ls_rs1_value.eq(Mux(execute_rs1 == 15, execute_post_increment_pc, operand_b)),
            ls_addr.eq(ls_rs1_value + (execute_ls_offset2 << 1)),
            ls_push_addr.eq(ls_rd_value - 8),
            ls_pc_rel6.eq(sign_extend(self.execute_instruction[4:10], 6, 64)),
            shift_index.eq(Mux(operand_b >= 64, 64, operand_b[:7])),
            execute_post_increment_pc.eq(self.execute_pc + 2),
            execute_jump_rel10.eq(sign_extend(self.execute_instruction[:10], 10, 64) << 1),
            execute_jump_rel13.eq(sign_extend(self.execute_instruction[:13], 13, 64) << 1),
            execute_ls_pc_effective.eq(execute_post_increment_pc + (ls_pc_rel6 << 1)),
            execute_ls_jump_target.eq(execute_post_increment_pc + execute_jump_rel10),
            execute_ls_pc_push_addr.eq(operand_a - 8),
            execute_ujump_target.eq(execute_post_increment_pc + execute_jump_rel13),
            execute_ls_jump_taken.eq(ls_condition(self.flags, execute_ls_opcode)),
            sum_value.eq(operand_a + operand_b),
            sub_value.eq(operand_a - operand_b),
            sign_extended_ldi.eq(sign_extend(Cat(Const(0, 24), execute_ldi_imm8), 32, 64)),
            ldi_value.eq(operand_a),
            load_width.eq(Mux(execute_ls_opcode == LSOpcode.BYTE_LOAD, 1,
                          Mux(execute_ls_opcode == LSOpcode.SHORT_LOAD, 2,
                          Mux(execute_ls_opcode == LSOpcode.WORD_LOAD, 4, 8)))),
            store_width.eq(Mux(execute_ls_opcode == LSOpcode.BYTE_STORE, 1,
                           Mux(execute_ls_opcode == LSOpcode.SHORT_STORE, 2,
                           Mux(execute_ls_opcode == LSOpcode.WORD_STORE, 4, 8)))),
            paging_enabled.eq(self.special_regs.cpu_control[16]),
            self.frontend.pc.eq(self.fetch_phys_addr),
            self.frontend.update_line_valid.eq(0),
            self.frontend.update_line_data.eq(unified_line_update_value),
            self.halted.eq(self.state == V2PipelineState.HALTED),
            self.commit_valid.eq(0),
            self.commit_pc.eq(self.writeback_commit_pc),
            self.lsu.request_valid.eq(lsu_request_valid & ~self.lsu_started),
            self.lsu.request_addr.eq(lsu_request_addr),
            self.lsu.request_width_bytes.eq(lsu_request_width),
            self.lsu.request_write.eq(lsu_request_write),
            self.lsu.request_store_value.eq(lsu_request_store_value),
            special_write_active.eq((self.state == V2PipelineState.EXECUTE) & (execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.SSR)),
            current_interrupt_vector.eq((self.special_regs.cpu_control & CPU_CONTROL_CUR_INT_MASK) >> CPU_CONTROL_CUR_INT_SHIFT),
            irq_line_pending_mask.eq(Cat(Const(0, 1), self.irq_lines, Const(0, 63 - self.config.irq_input_count))),
            pending_irq_high.eq(self.special_regs.interrupt_states_high | irq_line_pending_mask),
            pending_irq_available.eq(0),
            pending_irq_vector.eq(0),
            can_preempt_pending_irq.eq((~self.special_regs.cpu_control[1]) |
                                       (current_interrupt_vector == 0) |
                                       (current_interrupt_vector > pending_irq_vector)),
            tlb_lookup_vaddr.eq(self.translate_virtual_addr),
            tlb_perm_ok.eq(Mux(self.translate_access == ACCESS_EXECUTE,
                               tlb_lookup_perm_execute,
                               Mux(self.translate_access == ACCESS_WRITE,
                                   tlb_lookup_perm_write,
                                   tlb_lookup_perm_read))),
            tlb_user_ok.eq((~self.special_regs.cpu_control[17]) | tlb_lookup_perm_user),
            tlb_hit_ok.eq(tlb_lookup_hit & tlb_perm_ok & tlb_user_ok),
            walk_index.eq(Mux(self.walk_level == 2, self.walk_virtual_addr[30:39],
                          Mux(self.walk_level == 1, self.walk_virtual_addr[21:30],
                          self.walk_virtual_addr[12:21]))),
            walk_pte_addr.eq(self.walk_table_addr + (walk_index << 3)),
            walk_pte.eq(self.walk_pte_latched),
            walk_is_leaf.eq((walk_pte & (PTE_R | PTE_W | PTE_X)) != 0),
            walk_permission_ok.eq(Mux(self.walk_access == ACCESS_READ, (walk_pte & PTE_R) != 0,
                                  Mux(self.walk_access == ACCESS_WRITE, (walk_pte & PTE_W) != 0,
                                  (walk_pte & PTE_X) != 0))),
            walk_user_ok.eq((~self.special_regs.cpu_control[17]) | ((walk_pte & PTE_U) != 0)),
            walk_reserved.eq((walk_pte & PTE_RESERVED_MASK) != 0),
            walk_table_next.eq((walk_pte >> 10) << 12),
            walk_page_shift.eq(Mux(self.walk_level == 2, 30,
                               Mux(self.walk_level == 1, 21, 12))),
            walk_page_mask.eq((Const(1, 64) << walk_page_shift) - 1),
            walk_page_base.eq((walk_pte >> 10) << 12),
            walk_result_phys.eq(walk_page_base + (self.walk_virtual_addr & walk_page_mask)),
            reservation_end.eq(self.ll_reservation_addr + 7),
            write_end.eq(self.mem_virtual_addr + self.mem_width_bytes - 1),
            store_overlaps_reservation.eq(
                self.ll_reservation_valid &
                self.mem_write &
                (self.mem_width_bytes != 0) &
                (self.mem_virtual_addr <= reservation_end) &
                (self.ll_reservation_addr <= write_end)
            ),
            mem_byte_offset.eq(self.mem_addr[0:3]),
            mem_base_sel.eq(Mux(self.mem_width_bytes == 1, 0x01,
                            Mux(self.mem_width_bytes == 2, 0x03,
                            Mux(self.mem_width_bytes == 4, 0x0F,
                            Mux(self.mem_width_bytes == 8, 0xFF, 0x00))))),
            mem_single_line_access.eq((self.mem_addr[0:3] + self.mem_width_bytes) <= 8),
            dcache_cacheable_load.eq(Const(1 if self.dcache is not None else 0, 1) & ~self.mem_write & mem_single_line_access),
            dcache_cacheable_fill.eq(Const(1 if self.dcache is not None else 0, 1) & ~self.mem_write & (self.mem_width_bytes == 8) & (self.mem_addr[0:3] == 0)),
            dcache_store_update_valid.eq(0),
            dcache_store_update_addr.eq(self.mem_addr),
            dcache_store_update_sel.eq(mem_shifted_sel),
            dcache_store_update_data.eq(mem_shifted_store_data),
            dcache_fill_valid.eq(0),
            dcache_fill_addr.eq(self.mem_addr),
            dcache_fill_data.eq(self.lsu.response_load_value),
            dcache_flush_all.eq(0),
            dcache_invalidate_valid.eq(0),
            dcache_invalidate_addr.eq(self.mem_addr),
            memory_response_result.eq(Mux(dcache_cacheable_load & dcache_lookup_hit & ~self.lsu_started,
                                          dcache_load_result,
                                          Mux(self.mem_write, self.mem_result_value, self.lsu.response_load_value))),
            memory_response_post_value.eq(Mux(self.mem_post_reg_use_load_result,
                                          memory_response_result + self.mem_post_reg_delta,
                                          self.mem_post_reg_value)),
            memory_response_next_pc.eq(
                Mux(self.mem_post_reg_write & (self.mem_post_reg_index == 15),
                    memory_response_post_value,
                    Mux(self.mem_rd == 15, memory_response_result, self.mem_next_pc))
            ),
            line_match.eq(self.frontend.line_valid & ((self.mem_addr & Const(0xFFFFFFFFFFFFFFF8, 64)) == self.frontend.line_base)),
            unified_line_update_value.eq(self.frontend.line_data),
            lsu_request_valid.eq((self.state == V2PipelineState.MEMORY) |
                                 (self.state == V2PipelineState.WALK) |
                                 (self.state == V2PipelineState.INTERRUPT_VECTOR_LOAD)),
            lsu_request_addr.eq(Mux(self.state == V2PipelineState.WALK,
                               walk_pte_addr,
                               Mux(self.state == V2PipelineState.INTERRUPT_VECTOR_LOAD,
                                   self.interrupt_vector_phys,
                                   self.mem_addr))),
            lsu_request_width.eq(Mux((self.state == V2PipelineState.WALK) |
                                 (self.state == V2PipelineState.INTERRUPT_VECTOR_LOAD),
                                 8,
                                 self.mem_width_bytes)),
            lsu_request_write.eq((self.state == V2PipelineState.MEMORY) & self.mem_write),
            lsu_request_store_value.eq(self.mem_store_value),
            next_reg_write.eq(0),
            next_reg_index.eq(execute_rd),
            next_reg_value.eq(0),
            next_flags_write.eq(0),
            next_flags_value.eq(self.flags),
            next_pc.eq(execute_post_increment_pc),
            next_lockup.eq(0),
            next_mem_start.eq(0),
            next_mem_addr.eq(0),
            next_mem_virtual_addr.eq(0),
            next_mem_width_bytes.eq(0),
            next_mem_write.eq(0),
            next_mem_store_value.eq(0),
            next_mem_rd.eq(0),
            next_mem_next_pc.eq(execute_post_increment_pc),
            next_mem_fault_pc.eq(self.execute_pc),
            next_mem_flags_write.eq(0),
            next_mem_flags_value.eq(self.flags),
            next_mem_set_reservation.eq(0),
            next_mem_reservation_addr.eq(0),
            next_mem_post_reg_write.eq(0),
            next_mem_post_reg_index.eq(0),
            next_mem_post_reg_value.eq(0),
            next_mem_post_reg_delta.eq(0),
            next_mem_post_reg_use_load_result.eq(0),
            next_mem_chain_store.eq(0),
            next_mem_chain_store_addr.eq(0),
            next_mem_chain_store_use_load_result.eq(0),
            next_mem_chain_store_value.eq(0),
            execute_starts_memory.eq(0),
            gp_alu_valid.eq(0),
            gp_alu_reg_write.eq(0),
            gp_alu_result_value.eq(0),
            gp_alu_flags_write.eq(0),
            gp_alu_flag_result.eq(0),
            gp_alu_flag_carry.eq(0),
            gp_alu_flags_value.eq(self.flags),
            self.special_regs.user_mode.eq(self.special_regs.cpu_control[17]),
            self.special_regs.read_selector.eq(operand_b[:16]),
            self.special_regs.write_stb.eq(special_write_active),
            self.special_regs.write_selector.eq(operand_b[:16]),
            self.special_regs.write_data.eq(operand_a),
            self.special_regs.core_cpu_control_write.eq(core_cpu_control_write),
            self.special_regs.core_cpu_control_data.eq(core_cpu_control_data),
            self.special_regs.core_interrupt_cpu_control_write.eq(core_interrupt_cpu_control_write),
            self.special_regs.core_interrupt_cpu_control_data.eq(core_interrupt_cpu_control_data),
            self.special_regs.core_interrupt_epc_write.eq(core_interrupt_epc_write),
            self.special_regs.core_interrupt_epc_data.eq(core_interrupt_epc_data),
            self.special_regs.core_interrupt_eflags_write.eq(core_interrupt_eflags_write),
            self.special_regs.core_interrupt_eflags_data.eq(core_interrupt_eflags_data),
            self.special_regs.core_trap_write.eq(core_trap_write),
            self.special_regs.core_trap_cause_data.eq(core_trap_cause_data),
            self.special_regs.core_trap_fault_addr_data.eq(core_trap_fault_addr_data),
            self.special_regs.core_trap_access_data.eq(core_trap_access_data),
            self.special_regs.core_trap_pc_data.eq(core_trap_pc_data),
            self.special_regs.core_trap_aux_data.eq(core_trap_aux_data),
            self.special_regs.interrupt_states_high_set.eq(Mux(
                (irq_line_pending_mask != 0) & ~(special_write_active & (operand_b[:16] == SpecialRegister.INTERRUPT_STATES_HIGH)),
                irq_line_pending_mask,
                0,
            )),
            core_cpu_control_write.eq(0),
            core_cpu_control_data.eq(0),
            core_interrupt_cpu_control_write.eq(0),
            core_interrupt_cpu_control_data.eq(0),
            core_interrupt_epc_write.eq(0),
            core_interrupt_epc_data.eq(0),
            core_interrupt_eflags_write.eq(0),
            core_interrupt_eflags_data.eq(0),
            core_trap_write.eq(0),
            core_trap_cause_data.eq(0),
            core_trap_fault_addr_data.eq(0),
            core_trap_access_data.eq(0),
            core_trap_pc_data.eq(0),
            core_trap_aux_data.eq(0),
            self.frontend.invalidate.eq(0),
        ]

        with m.If(execute_top3 == Const(0b110, 3)):
            with m.Switch(execute_gp_opcode):
                with m.Case(GPOpcode.ADD):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(sum_value[:64]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(sum_value[:64]),
                        gp_alu_flag_carry.eq(sum_value[64]),
                    ]
                with m.Case(GPOpcode.SUB):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(sub_value),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(sub_value),
                        gp_alu_flag_carry.eq(operand_b > operand_a),
                    ]
                with m.Case(GPOpcode.TEST):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(sub_value),
                        gp_alu_flag_carry.eq(operand_b > operand_a),
                    ]
                with m.Case(GPOpcode.AND):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(operand_a & operand_b),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(operand_a & operand_b),
                    ]
                with m.Case(GPOpcode.OR):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(operand_a | operand_b),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(operand_a | operand_b),
                    ]
                with m.Case(GPOpcode.XOR):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(operand_a ^ operand_b),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(operand_a ^ operand_b),
                    ]
                with m.Case(GPOpcode.SLL):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(sll_results[shift_index]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(sll_results[shift_index]),
                        gp_alu_flag_carry.eq(sll_carries[shift_index]),
                    ]
                with m.Case(GPOpcode.SRL):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(srl_results[shift_index]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(srl_results[shift_index]),
                        gp_alu_flag_carry.eq(srl_carries[shift_index]),
                    ]
                with m.Case(GPOpcode.SRA):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(sra_results[shift_index]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(sra_results[shift_index]),
                        gp_alu_flag_carry.eq(sra_carries[shift_index]),
                    ]
                with m.Case(GPOpcode.SLLI):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(slli_results[execute_imm4]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(slli_results[execute_imm4]),
                        gp_alu_flag_carry.eq(slli_carries[execute_imm4]),
                    ]
                with m.Case(GPOpcode.SRLI):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(srli_results[execute_imm4]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(srli_results[execute_imm4]),
                        gp_alu_flag_carry.eq(srli_carries[execute_imm4]),
                    ]
                with m.Case(GPOpcode.SRAI):
                    m.d.comb += [
                        gp_alu_valid.eq(1),
                        gp_alu_reg_write.eq(1),
                        gp_alu_result_value.eq(srai_results[execute_imm4]),
                        gp_alu_flags_write.eq(1),
                        gp_alu_flag_result.eq(srai_results[execute_imm4]),
                        gp_alu_flag_carry.eq(srai_carries[execute_imm4]),
                    ]

        with m.If(gp_alu_flags_write):
            m.d.comb += gp_alu_flags_value.eq(flag_value(gp_alu_flag_result, gp_alu_flag_carry))

        with m.Switch(mem_byte_offset):
            for offset in range(8):
                with m.Case(offset):
                    if offset == 0:
                        m.d.comb += [
                            mem_shifted_sel.eq(mem_base_sel),
                            mem_shifted_store_data.eq(self.mem_store_value),
                            dcache_shifted_read.eq(dcache_lookup_data),
                        ]
                    else:
                        m.d.comb += [
                            mem_shifted_sel.eq(mem_base_sel << offset),
                            mem_shifted_store_data.eq(self.mem_store_value << (offset * 8)),
                            dcache_shifted_read.eq(Cat(dcache_lookup_data[offset * 8:64], Const(0, offset * 8))),
                        ]

        m.d.comb += dcache_load_result.eq(Mux(self.mem_width_bytes == 1, dcache_shifted_read & 0xFF,
                                          Mux(self.mem_width_bytes == 2, dcache_shifted_read & 0xFFFF,
                                          Mux(self.mem_width_bytes == 4, dcache_shifted_read & 0xFFFFFFFF,
                                          dcache_shifted_read))))

        m.d.comb += unified_line_update_value.eq(Cat(*[
            Mux(
                mem_shifted_sel[byte_index],
                mem_shifted_store_data[byte_index * 8:(byte_index + 1) * 8],
                self.frontend.line_data[byte_index * 8:(byte_index + 1) * 8],
            )
            for byte_index in range(8)
        ]))

        with m.Switch(execute_ldi_shift):
            with m.Case(0):
                m.d.comb += ldi_value.eq(execute_ldi_imm8)
            with m.Case(1):
                m.d.comb += ldi_value.eq(operand_a | (execute_ldi_imm8 << 8))
            with m.Case(2):
                m.d.comb += ldi_value.eq(operand_a | (execute_ldi_imm8 << 16))
            with m.Case(3):
                m.d.comb += ldi_value.eq(operand_a | sign_extended_ldi)

        for bit_index in range(self.config.irq_input_count, 0, -1):
            with m.If((pending_irq_high & self.special_regs.interrupt_mask_high)[bit_index]):
                m.d.comb += [
                    pending_irq_available.eq(1),
                    pending_irq_vector.eq(64 + bit_index),
                ]

        def write_reg(index_signal, value):
            with m.Switch(index_signal):
                for index in range(1, 16):
                    with m.Case(index):
                        m.d.sync += self.register_file[index].eq(value)

        def enter_lockup():
            m.d.sync += [
                self.locked_up.eq(1),
                self.state.eq(V2PipelineState.STALLED),
            ]

        def begin_interrupt_entry(vector, epc):
            m.d.comb += [
                core_interrupt_cpu_control_write.eq(1),
                core_interrupt_cpu_control_data.eq(self.special_regs.cpu_control),
                core_cpu_control_write.eq(1),
                core_cpu_control_data.eq(
                    (self.special_regs.cpu_control & Const((1 << 64) - 1 - (CPU_CONTROL_INT_ENABLE | CPU_CONTROL_IN_INTERRUPT | CPU_CONTROL_CUR_INT_MASK | CPU_CONTROL_USER_MODE), 64)) |
                    Const(CPU_CONTROL_IN_INTERRUPT, 64) |
                    (vector << CPU_CONTROL_CUR_INT_SHIFT)
                ),
            ]
            m.d.sync += [
                self.interrupt_entry_vector.eq(vector),
                self.interrupt_entry_epc.eq(epc),
                self.translate_virtual_addr.eq(self.special_regs.interrupt_table_base + (vector << 3)),
                self.translate_access.eq(ACCESS_READ),
                self.lsu_started.eq(0),
                self.state.eq(V2PipelineState.INTERRUPT_VECTOR_TRANSLATE),
            ]

        def raise_sync_trap(vector, trap_pc, *, fault_addr=0, access=0, aux=0):
            with m.If(self.special_regs.cpu_control[1] & (current_interrupt_vector != 0) & (current_interrupt_vector < TrapVector.FIRST_HW_IRQ) & (current_interrupt_vector <= vector)):
                enter_lockup()
            with m.Else():
                m.d.comb += [
                    core_trap_write.eq(1),
                    core_trap_cause_data.eq(Mux(self.special_regs.trap_cause == 0, vector, self.special_regs.trap_cause)),
                    core_trap_fault_addr_data.eq(fault_addr),
                    core_trap_access_data.eq(access),
                    core_trap_pc_data.eq(trap_pc),
                    core_trap_aux_data.eq(aux),
                ]
                begin_interrupt_entry(vector, trap_pc)

        m.d.sync += self.register_file[0].eq(0)

        with m.Switch(self.state):
            with m.Case(V2PipelineState.RESET):
                m.d.comb += [
                    core_trap_write.eq(1),
                    core_trap_cause_data.eq(0),
                    core_trap_fault_addr_data.eq(0),
                    core_trap_access_data.eq(0),
                    core_trap_pc_data.eq(0),
                    core_trap_aux_data.eq(0),
                ]
                m.d.sync += [
                    self.register_file[1].eq(self.boot_r1),
                    self.register_file[13].eq(self.boot_r13),
                    self.register_file[15].eq(self.config.reset_vector),
                    self.flags.eq(0),
                    self.ll_reservation_addr.eq(0),
                    self.ll_reservation_valid.eq(0),
                    self.fetch_pc.eq(self.config.reset_vector),
                    self.fetch_phys_addr.eq(self.config.reset_vector),
                    self.current_instruction.eq(0),
                    self.execute_instruction.eq(0),
                    self.execute_operand_a.eq(0),
                    self.execute_operand_b.eq(0),
                    self.decode_pc.eq(0),
                    self.execute_complete_reg_write.eq(0),
                    self.execute_complete_reg_index.eq(0),
                    self.execute_complete_reg_value.eq(0),
                    self.execute_complete_flags_write.eq(0),
                    self.execute_complete_flag_result.eq(0),
                    self.execute_complete_flag_carry.eq(0),
                    self.execute_complete_next_pc.eq(0),
                    self.execute_complete_lockup.eq(0),
                    self.execute_complete_commit_pc.eq(0),
                    self.execute_pc.eq(0),
                    self.writeback_reg_write.eq(0),
                    self.writeback_reg_index.eq(0),
                    self.writeback_reg_value.eq(0),
                    self.writeback_aux_reg_write.eq(0),
                    self.writeback_aux_reg_index.eq(0),
                    self.writeback_aux_reg_value.eq(0),
                    self.writeback_flags_write.eq(0),
                    self.writeback_flags_value.eq(0),
                    self.writeback_next_pc.eq(self.config.reset_vector),
                    self.writeback_halt.eq(0),
                    self.writeback_lockup.eq(0),
                    self.writeback_commit_pc.eq(0),
                    self.lsu_started.eq(0),
                    self.mem_addr.eq(0),
                    self.mem_virtual_addr.eq(0),
                    self.mem_width_bytes.eq(0),
                    self.mem_write.eq(0),
                    self.mem_store_value.eq(0),
                    self.mem_rd.eq(0),
                    self.mem_next_pc.eq(self.config.reset_vector),
                    self.mem_fault_pc.eq(0),
                    self.mem_flags_write.eq(0),
                    self.mem_flags_value.eq(0),
                    self.mem_set_reservation.eq(0),
                    self.mem_reservation_addr.eq(0),
                    self.mem_post_reg_write.eq(0),
                    self.mem_post_reg_index.eq(0),
                    self.mem_post_reg_value.eq(0),
                    self.mem_post_reg_delta.eq(0),
                    self.mem_post_reg_use_load_result.eq(0),
                    self.mem_chain_store.eq(0),
                    self.mem_chain_store_addr.eq(0),
                    self.mem_chain_store_use_load_result.eq(0),
                    self.mem_chain_store_value.eq(0),
                    self.mem_result_value.eq(0),
                    self.translate_virtual_addr.eq(self.config.reset_vector),
                    self.translate_access.eq(ACCESS_EXECUTE),
                    self.walk_virtual_addr.eq(0),
                    self.walk_table_addr.eq(0),
                    self.walk_level.eq(0),
                    self.walk_access.eq(0),
                    self.walk_resume_kind.eq(WalkResumeKind.FETCH),
                    self.walk_pte_latched.eq(0),
                    self.interrupt_entry_vector.eq(0),
                    self.interrupt_entry_epc.eq(0),
                    self.interrupt_vector_phys.eq(0),
                    self.locked_up.eq(0),
                    self.state.eq(V2PipelineState.FETCH_TRANSLATE),
                ]

            with m.Case(V2PipelineState.FETCH_TRANSLATE):
                with m.If(self.translate_virtual_addr[0]):
                    raise_sync_trap(TrapVector.EXEC_ALIGN, self.translate_virtual_addr, fault_addr=self.translate_virtual_addr, access=ACCESS_EXECUTE, aux=encode_aux(AUX_SUBTYPE_NONE, 0))
                with m.Elif(paging_enabled & ~Const(1 if self.config.enable_mmu else 0, 1)):
                    enter_lockup()
                with m.Elif(pending_irq_available & self.special_regs.cpu_control[0] & can_preempt_pending_irq):
                    begin_interrupt_entry(pending_irq_vector, self.translate_virtual_addr)
                with m.Elif(~paging_enabled):
                    m.d.sync += [
                        self.fetch_phys_addr.eq(self.translate_virtual_addr),
                        self.state.eq(V2PipelineState.FETCH_REQUEST),
                    ]
                with m.Elif(~is_canonical39(self.translate_virtual_addr)):
                    raise_sync_trap(TrapVector.PAGE_FAULT_CANONICAL, self.translate_virtual_addr, fault_addr=self.translate_virtual_addr, access=ACCESS_EXECUTE, aux=encode_aux(AUX_SUBTYPE_CANONICAL, 2))
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.translate_virtual_addr, fault_addr=self.translate_virtual_addr, access=ACCESS_EXECUTE, aux=encode_aux(AUX_SUBTYPE_RESERVED_BIT, 2))
                with m.Elif(tlb_hit_ok):
                    m.d.sync += [
                        self.fetch_phys_addr.eq(tlb_lookup_paddr),
                        self.state.eq(V2PipelineState.FETCH_REQUEST),
                    ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(self.translate_virtual_addr),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(ACCESS_EXECUTE),
                        self.walk_resume_kind.eq(WalkResumeKind.FETCH),
                        self.mem_fault_pc.eq(self.translate_virtual_addr),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.WALK),
                    ]

            with m.Case(V2PipelineState.FETCH_REQUEST):
                with m.If(self.frontend.fetch_error):
                    enter_lockup()
                with m.Elif(self.frontend.instruction_valid):
                    m.d.sync += [
                        self.fetch_pc.eq(current_pc),
                        self.current_instruction.eq(self.frontend.instruction_word),
                        self.decode_pc.eq(current_pc),
                        self.state.eq(V2PipelineState.DECODE),
                    ]

            with m.Case(V2PipelineState.DECODE):
                m.d.sync += [
                    self.execute_instruction.eq(self.current_instruction),
                    self.execute_operand_a.eq(self.regs[decode_rd]),
                    self.execute_operand_b.eq(self.regs[decode_rs1]),
                    self.execute_pc.eq(self.decode_pc),
                    self.state.eq(V2PipelineState.EXECUTE),
                ]

            with m.Case(V2PipelineState.EXECUTE):
                with m.If(execute_top2 == 0b10):
                    m.d.sync += [
                        self.writeback_reg_write.eq(1),
                        self.writeback_reg_index.eq(execute_rd),
                        self.writeback_reg_value.eq(ldi_value),
                        self.writeback_aux_reg_write.eq(0),
                        self.writeback_aux_reg_index.eq(0),
                        self.writeback_aux_reg_value.eq(0),
                        self.writeback_flags_write.eq(0),
                        self.writeback_flags_value.eq(0),
                        self.writeback_next_pc.eq(execute_post_increment_pc),
                        self.writeback_halt.eq(0),
                        self.writeback_lockup.eq(0),
                        self.writeback_commit_pc.eq(self.execute_pc),
                        self.state.eq(V2PipelineState.WRITEBACK),
                    ]
                with m.Elif((execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.LSR)):
                    with m.If(self.special_regs.read_access_fault):
                        raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.execute_pc)
                    with m.Else():
                        m.d.sync += [
                            self.writeback_reg_write.eq(1),
                            self.writeback_reg_index.eq(execute_rd),
                            self.writeback_reg_value.eq(self.special_regs.read_data),
                            self.writeback_aux_reg_write.eq(0),
                            self.writeback_aux_reg_index.eq(0),
                            self.writeback_aux_reg_value.eq(0),
                            self.writeback_flags_write.eq(0),
                            self.writeback_flags_value.eq(0),
                            self.writeback_next_pc.eq(execute_post_increment_pc),
                            self.writeback_halt.eq(0),
                            self.writeback_lockup.eq(0),
                            self.writeback_commit_pc.eq(self.execute_pc),
                            self.state.eq(V2PipelineState.WRITEBACK),
                        ]
                with m.Elif((execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.SSR)):
                    with m.If(self.special_regs.write_access_fault):
                        raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.execute_pc)
                    with m.Else():
                        m.d.sync += [
                            self.writeback_reg_write.eq(0),
                            self.writeback_reg_index.eq(0),
                            self.writeback_reg_value.eq(0),
                            self.writeback_aux_reg_write.eq(0),
                            self.writeback_aux_reg_index.eq(0),
                            self.writeback_aux_reg_value.eq(0),
                            self.writeback_flags_write.eq(0),
                            self.writeback_flags_value.eq(0),
                            self.writeback_next_pc.eq(execute_post_increment_pc),
                            self.writeback_halt.eq(0),
                            self.writeback_lockup.eq(0),
                            self.writeback_commit_pc.eq(self.execute_pc),
                            self.state.eq(V2PipelineState.WRITEBACK),
                        ]
                with m.Elif((execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.SYSCALL)):
                    raise_sync_trap(Mux(self.special_regs.cpu_control[17], TrapVector.SYSCALL, TrapVector.SYSCALL_FROM_SUPERVISOR), self.execute_pc)
                with m.Elif((execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.IRET)):
                    with m.If(self.special_regs.cpu_control[17]):
                        raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.execute_pc)
                    with m.Else():
                        m.d.comb += [
                            core_cpu_control_write.eq(1),
                            core_cpu_control_data.eq(self.special_regs.interrupt_cpu_control),
                        ]
                        m.d.sync += [
                            self.register_file[15].eq(self.special_regs.interrupt_epc),
                            self.fetch_pc.eq(self.special_regs.interrupt_epc),
                            self.flags.eq(self.special_regs.interrupt_eflags[:3]),
                            self.translate_virtual_addr.eq(self.special_regs.interrupt_epc),
                            self.translate_access.eq(ACCESS_EXECUTE),
                            self.state.eq(V2PipelineState.FETCH_TRANSLATE),
                        ]
                with m.Elif((execute_top3 == 0b110) & (execute_gp_opcode == GPOpcode.STOP)):
                    with m.If(self.special_regs.cpu_control[17]):
                        raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.execute_pc)
                    with m.Else():
                        m.d.sync += [
                            self.register_file[15].eq(execute_post_increment_pc),
                            self.fetch_pc.eq(self.execute_pc),
                            self.state.eq(V2PipelineState.HALTED),
                        ]
                with m.Elif((execute_top3 == 0b110) & ~((execute_gp_opcode == GPOpcode.ADD) |
                                                       (execute_gp_opcode == GPOpcode.SUB) |
                                                       (execute_gp_opcode == GPOpcode.TEST) |
                                                       (execute_gp_opcode == GPOpcode.LLR) |
                                                       (execute_gp_opcode == GPOpcode.SCR) |
                                                       (execute_gp_opcode == GPOpcode.AND) |
                                                       (execute_gp_opcode == GPOpcode.OR) |
                                                       (execute_gp_opcode == GPOpcode.XOR) |
                                                       (execute_gp_opcode == GPOpcode.SLL) |
                                                       (execute_gp_opcode == GPOpcode.SRL) |
                                                       (execute_gp_opcode == GPOpcode.SRA) |
                                                       (execute_gp_opcode == GPOpcode.SLLI) |
                                                       (execute_gp_opcode == GPOpcode.SRLI) |
                                                       (execute_gp_opcode == GPOpcode.SRAI))):
                    raise_sync_trap(TrapVector.INVALID_INSTRUCTION, self.execute_pc)
                with m.Else():
                    with m.If(execute_top2 == 0b00):
                        with m.Switch(execute_ls_opcode):
                            with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(ls_addr),
                                    next_mem_virtual_addr.eq(ls_addr),
                                    next_mem_width_bytes.eq(load_width),
                                    next_mem_write.eq(0),
                                    next_mem_rd.eq(execute_rd),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                ]
                            with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(ls_addr),
                                    next_mem_virtual_addr.eq(ls_addr),
                                    next_mem_width_bytes.eq(store_width),
                                    next_mem_write.eq(1),
                                    next_mem_store_value.eq(ls_rd_value),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                ]
                            with m.Case(LSOpcode.PUSH):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(ls_push_addr),
                                    next_mem_virtual_addr.eq(ls_push_addr),
                                    next_mem_width_bytes.eq(8),
                                    next_mem_write.eq(1),
                                    next_mem_store_value.eq(ls_rs1_value),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                    next_mem_post_reg_write.eq(1),
                                    next_mem_post_reg_index.eq(execute_rd),
                                    next_mem_post_reg_value.eq(ls_push_addr),
                                ]
                            with m.Case(LSOpcode.POP):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(ls_rd_value),
                                    next_mem_virtual_addr.eq(ls_rd_value),
                                    next_mem_width_bytes.eq(8),
                                    next_mem_write.eq(0),
                                    next_mem_rd.eq(execute_rs1),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                    next_mem_post_reg_write.eq(1),
                                    next_mem_post_reg_index.eq(execute_rd),
                                    next_mem_post_reg_value.eq(ls_rd_value + 8),
                                    next_mem_post_reg_delta.eq(8),
                                    next_mem_post_reg_use_load_result.eq(execute_rd == execute_rs1),
                                ]
                            with m.Case(LSOpcode.MOVE):
                                m.d.comb += [
                                    next_reg_write.eq(1),
                                    next_reg_index.eq(execute_rd),
                                    next_reg_value.eq(ls_addr),
                                    next_pc.eq(Mux(execute_rd == 15, ls_addr, execute_post_increment_pc)),
                                ]
                            with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                                m.d.comb += [
                                    next_reg_write.eq(execute_ls_jump_taken),
                                    next_reg_index.eq(execute_rd),
                                    next_reg_value.eq(ls_addr),
                                    next_pc.eq(Mux(execute_ls_jump_taken & (execute_rd == 15), ls_addr, execute_post_increment_pc)),
                                ]
                            with m.Default():
                                m.d.comb += next_lockup.eq(1)
                    with m.Elif(execute_top2 == 0b01):
                        with m.Switch(execute_ls_opcode):
                            with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(execute_ls_pc_effective),
                                    next_mem_virtual_addr.eq(execute_ls_pc_effective),
                                    next_mem_width_bytes.eq(load_width),
                                    next_mem_write.eq(0),
                                    next_mem_rd.eq(execute_rd),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                ]
                            with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(execute_ls_pc_effective),
                                    next_mem_virtual_addr.eq(execute_ls_pc_effective),
                                    next_mem_width_bytes.eq(store_width),
                                    next_mem_write.eq(1),
                                    next_mem_store_value.eq(operand_a),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                ]
                            with m.Case(LSOpcode.PUSH):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(execute_ls_pc_effective),
                                    next_mem_virtual_addr.eq(execute_ls_pc_effective),
                                    next_mem_width_bytes.eq(8),
                                    next_mem_write.eq(0),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                    next_mem_post_reg_write.eq(1),
                                    next_mem_post_reg_index.eq(execute_rd),
                                    next_mem_post_reg_value.eq(execute_ls_pc_push_addr),
                                    next_mem_chain_store.eq(1),
                                    next_mem_chain_store_addr.eq(execute_ls_pc_push_addr),
                                    next_mem_chain_store_use_load_result.eq(1),
                                ]
                            with m.Case(LSOpcode.POP):
                                m.d.comb += [
                                    execute_starts_memory.eq(1),
                                    next_mem_start.eq(1),
                                    next_mem_addr.eq(operand_a),
                                    next_mem_virtual_addr.eq(operand_a),
                                    next_mem_width_bytes.eq(8),
                                    next_mem_write.eq(0),
                                    next_mem_next_pc.eq(execute_post_increment_pc),
                                    next_mem_fault_pc.eq(self.execute_pc),
                                    next_mem_post_reg_write.eq(1),
                                    next_mem_post_reg_index.eq(execute_rd),
                                    next_mem_post_reg_value.eq(operand_a + 8),
                                    next_mem_chain_store.eq(1),
                                    next_mem_chain_store_addr.eq(execute_ls_pc_effective),
                                    next_mem_chain_store_use_load_result.eq(1),
                                ]
                            with m.Case(LSOpcode.MOVE):
                                m.d.comb += [
                                    next_reg_write.eq(1),
                                    next_reg_index.eq(execute_rd),
                                    next_reg_value.eq(execute_ls_pc_effective),
                                    next_pc.eq(Mux(execute_rd == 15, execute_ls_pc_effective, execute_post_increment_pc)),
                                ]
                            with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                                m.d.comb += next_pc.eq(Mux(execute_ls_jump_taken, execute_ls_jump_target, execute_post_increment_pc))
                            with m.Default():
                                m.d.comb += next_lockup.eq(1)
                    with m.Else():
                        with m.Switch(execute_top3):
                            with m.Case(0b111):
                                m.d.comb += next_pc.eq(execute_ujump_target)
                            with m.Case(0b110):
                                with m.If(gp_alu_valid):
                                    m.d.comb += [
                                        next_reg_write.eq(gp_alu_reg_write),
                                        next_reg_value.eq(gp_alu_result_value),
                                        next_flags_write.eq(gp_alu_flags_write),
                                        next_flags_value.eq(gp_alu_flags_value),
                                    ]
                                with m.Elif(execute_gp_opcode == GPOpcode.LLR):
                                    m.d.comb += [
                                        execute_starts_memory.eq(1),
                                        next_mem_start.eq(1),
                                        next_mem_addr.eq(operand_b),
                                        next_mem_virtual_addr.eq(operand_b),
                                        next_mem_width_bytes.eq(8),
                                        next_mem_write.eq(0),
                                        next_mem_rd.eq(execute_rd),
                                        next_mem_next_pc.eq(execute_post_increment_pc),
                                        next_mem_fault_pc.eq(self.execute_pc),
                                        next_mem_set_reservation.eq(1),
                                        next_mem_reservation_addr.eq(operand_b),
                                    ]
                                with m.Elif(execute_gp_opcode == GPOpcode.SCR):
                                    with m.If(self.ll_reservation_valid & (self.ll_reservation_addr == operand_b)):
                                        m.d.comb += [
                                            execute_starts_memory.eq(1),
                                            next_mem_start.eq(1),
                                            next_mem_addr.eq(operand_b),
                                            next_mem_virtual_addr.eq(operand_b),
                                            next_mem_width_bytes.eq(8),
                                            next_mem_write.eq(1),
                                            next_mem_store_value.eq(operand_a),
                                            next_mem_next_pc.eq(execute_post_increment_pc),
                                            next_mem_fault_pc.eq(self.execute_pc),
                                            next_mem_flags_write.eq(1),
                                            next_mem_flags_value.eq(Cat(Const(1, 1), self.flags[1], self.flags[2])),
                                        ]
                                    with m.Else():
                                        m.d.comb += [
                                            next_flags_write.eq(1),
                                            next_flags_value.eq(Cat(Const(0, 1), self.flags[1], self.flags[2])),
                                        ]
                                with m.Else():
                                    m.d.comb += next_lockup.eq(1)
                            with m.Default():
                                m.d.comb += next_lockup.eq(1)

                    with m.If(gp_alu_valid):
                        m.d.sync += [
                            self.execute_complete_reg_write.eq(next_reg_write),
                            self.execute_complete_reg_index.eq(next_reg_index),
                            self.execute_complete_reg_value.eq(next_reg_value),
                            self.execute_complete_flags_write.eq(next_flags_write),
                            self.execute_complete_flag_result.eq(gp_alu_flag_result),
                            self.execute_complete_flag_carry.eq(gp_alu_flag_carry),
                            self.execute_complete_next_pc.eq(next_pc),
                            self.execute_complete_lockup.eq(next_lockup),
                            self.execute_complete_commit_pc.eq(self.execute_pc),
                            self.lsu_started.eq(0),
                            self.mem_addr.eq(next_mem_addr),
                            self.mem_virtual_addr.eq(next_mem_virtual_addr),
                            self.translate_virtual_addr.eq(next_mem_virtual_addr),
                            self.translate_access.eq(Mux(next_mem_write, ACCESS_WRITE, ACCESS_READ)),
                            self.mem_width_bytes.eq(next_mem_width_bytes),
                            self.mem_write.eq(next_mem_write),
                            self.mem_store_value.eq(next_mem_store_value),
                            self.mem_rd.eq(next_mem_rd),
                            self.mem_next_pc.eq(next_mem_next_pc),
                            self.mem_fault_pc.eq(next_mem_fault_pc),
                            self.mem_flags_write.eq(next_mem_flags_write),
                            self.mem_flags_value.eq(next_mem_flags_value),
                            self.mem_set_reservation.eq(next_mem_set_reservation),
                            self.mem_reservation_addr.eq(next_mem_reservation_addr),
                            self.mem_post_reg_write.eq(next_mem_post_reg_write),
                            self.mem_post_reg_index.eq(next_mem_post_reg_index),
                            self.mem_post_reg_value.eq(next_mem_post_reg_value),
                            self.mem_post_reg_delta.eq(next_mem_post_reg_delta),
                            self.mem_post_reg_use_load_result.eq(next_mem_post_reg_use_load_result),
                            self.mem_chain_store.eq(next_mem_chain_store),
                            self.mem_chain_store_addr.eq(next_mem_chain_store_addr),
                            self.mem_chain_store_use_load_result.eq(next_mem_chain_store_use_load_result),
                            self.mem_chain_store_value.eq(next_mem_chain_store_value),
                            self.mem_result_value.eq(0),
                            self.state.eq(V2PipelineState.EXECUTE_COMPLETE),
                        ]
                    with m.Else():
                        m.d.sync += [
                            self.writeback_reg_write.eq(next_reg_write),
                            self.writeback_reg_index.eq(next_reg_index),
                            self.writeback_reg_value.eq(next_reg_value),
                            self.writeback_aux_reg_write.eq(0),
                            self.writeback_aux_reg_index.eq(0),
                            self.writeback_aux_reg_value.eq(0),
                            self.writeback_flags_write.eq(next_flags_write),
                            self.writeback_flags_value.eq(next_flags_value),
                            self.writeback_next_pc.eq(next_pc),
                            self.writeback_halt.eq(0),
                            self.writeback_lockup.eq(next_lockup),
                            self.writeback_commit_pc.eq(self.execute_pc),
                            self.lsu_started.eq(0),
                            self.mem_addr.eq(next_mem_addr),
                            self.mem_virtual_addr.eq(next_mem_virtual_addr),
                            self.translate_virtual_addr.eq(next_mem_virtual_addr),
                            self.translate_access.eq(Mux(next_mem_write, ACCESS_WRITE, ACCESS_READ)),
                            self.mem_width_bytes.eq(next_mem_width_bytes),
                            self.mem_write.eq(next_mem_write),
                            self.mem_store_value.eq(next_mem_store_value),
                            self.mem_rd.eq(next_mem_rd),
                            self.mem_next_pc.eq(next_mem_next_pc),
                            self.mem_fault_pc.eq(next_mem_fault_pc),
                            self.mem_flags_write.eq(next_mem_flags_write),
                            self.mem_flags_value.eq(next_mem_flags_value),
                            self.mem_set_reservation.eq(next_mem_set_reservation),
                            self.mem_reservation_addr.eq(next_mem_reservation_addr),
                            self.mem_post_reg_write.eq(next_mem_post_reg_write),
                            self.mem_post_reg_index.eq(next_mem_post_reg_index),
                            self.mem_post_reg_value.eq(next_mem_post_reg_value),
                            self.mem_post_reg_delta.eq(next_mem_post_reg_delta),
                            self.mem_post_reg_use_load_result.eq(next_mem_post_reg_use_load_result),
                            self.mem_chain_store.eq(next_mem_chain_store),
                            self.mem_chain_store_addr.eq(next_mem_chain_store_addr),
                            self.mem_chain_store_use_load_result.eq(next_mem_chain_store_use_load_result),
                            self.mem_chain_store_value.eq(next_mem_chain_store_value),
                            self.mem_result_value.eq(0),
                            self.state.eq(Mux(execute_starts_memory, V2PipelineState.MEM_TRANSLATE, V2PipelineState.WRITEBACK)),
                        ]

            with m.Case(V2PipelineState.MEM_TRANSLATE):
                with m.If(paging_enabled & ~Const(1 if self.config.enable_mmu else 0, 1)):
                    enter_lockup()
                with m.Elif(~paging_enabled):
                    m.d.sync += [
                        self.mem_addr.eq(self.mem_virtual_addr),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.MEMORY),
                    ]
                with m.Elif(~is_canonical39(self.mem_virtual_addr)):
                    raise_sync_trap(TrapVector.PAGE_FAULT_CANONICAL, self.mem_fault_pc, fault_addr=self.mem_virtual_addr, access=Mux(self.mem_write, ACCESS_WRITE, ACCESS_READ), aux=encode_aux(AUX_SUBTYPE_CANONICAL, 2))
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.mem_fault_pc, fault_addr=self.mem_virtual_addr, access=Mux(self.mem_write, ACCESS_WRITE, ACCESS_READ), aux=encode_aux(AUX_SUBTYPE_RESERVED_BIT, 2))
                with m.Elif(tlb_hit_ok):
                    m.d.sync += [
                        self.mem_addr.eq(tlb_lookup_paddr),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.MEMORY),
                    ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(self.translate_virtual_addr),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(Mux(self.mem_write, ACCESS_WRITE, ACCESS_READ)),
                        self.walk_resume_kind.eq(WalkResumeKind.MEMORY),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.WALK),
                    ]

            with m.Case(V2PipelineState.MEMORY):
                with m.If(dcache_cacheable_load & dcache_lookup_hit & ~self.lsu_started):
                    with m.If(self.mem_set_reservation):
                        m.d.sync += [
                            self.ll_reservation_addr.eq(self.mem_reservation_addr),
                            self.ll_reservation_valid.eq(1),
                        ]
                    m.d.sync += [
                        self.writeback_reg_write.eq(self.mem_rd != 0),
                        self.writeback_reg_index.eq(self.mem_rd),
                        self.writeback_reg_value.eq(dcache_load_result),
                        self.writeback_aux_reg_write.eq(self.mem_post_reg_write & (self.mem_post_reg_index != 0)),
                        self.writeback_aux_reg_index.eq(self.mem_post_reg_index),
                        self.writeback_aux_reg_value.eq(Mux(self.mem_post_reg_use_load_result, dcache_load_result + self.mem_post_reg_delta, self.mem_post_reg_value)),
                        self.writeback_flags_write.eq(self.mem_flags_write),
                        self.writeback_flags_value.eq(self.mem_flags_value),
                        self.writeback_next_pc.eq(
                            Mux(self.mem_post_reg_write & (self.mem_post_reg_index == 15),
                                Mux(self.mem_post_reg_use_load_result, dcache_load_result + self.mem_post_reg_delta, self.mem_post_reg_value),
                                Mux(self.mem_rd == 15, dcache_load_result, self.mem_next_pc))
                        ),
                        self.writeback_halt.eq(0),
                        self.writeback_lockup.eq(0),
                        self.writeback_commit_pc.eq(self.execute_pc),
                        self.state.eq(V2PipelineState.WRITEBACK),
                    ]
                with m.Elif(~self.lsu_started):
                    m.d.sync += self.lsu_started.eq(1)
                with m.If(self.lsu.response_valid):
                    with m.If(self.lsu.response_error):
                        enter_lockup()
                    with m.Else():
                        with m.If(dcache_cacheable_fill):
                            m.d.comb += dcache_fill_valid.eq(1)
                        with m.If(self.mem_write & mem_single_line_access):
                            m.d.comb += dcache_store_update_valid.eq(Const(1 if self.dcache is not None else 0, 1))
                        with m.If(self.mem_write & ~mem_single_line_access):
                            m.d.comb += [
                                dcache_flush_all.eq(Const(1 if self.dcache is not None else 0, 1)),
                                dcache_invalidate_addr.eq(self.mem_addr),
                            ]

                        with m.If(self.mem_write & line_match):
                            with m.If((self.config.cache_topology == 'unified') & mem_single_line_access):
                                m.d.comb += self.frontend.update_line_valid.eq(1)
                            with m.Else():
                                m.d.comb += self.frontend.invalidate.eq(1)

                        with m.If(self.mem_set_reservation):
                            m.d.sync += [
                                self.ll_reservation_addr.eq(self.mem_reservation_addr),
                                self.ll_reservation_valid.eq(1),
                            ]
                        with m.If(store_overlaps_reservation):
                            m.d.sync += self.ll_reservation_valid.eq(0)
                        with m.If(self.mem_chain_store):
                            m.d.sync += [
                                self.lsu_started.eq(0),
                                self.mem_addr.eq(self.mem_chain_store_addr),
                                self.mem_virtual_addr.eq(self.mem_chain_store_addr),
                                self.translate_virtual_addr.eq(self.mem_chain_store_addr),
                                self.translate_access.eq(ACCESS_WRITE),
                                self.mem_width_bytes.eq(8),
                                self.mem_write.eq(1),
                                self.mem_store_value.eq(Mux(self.mem_chain_store_use_load_result, self.lsu.response_load_value, self.mem_chain_store_value)),
                                self.mem_rd.eq(0),
                                self.mem_set_reservation.eq(0),
                                self.mem_chain_store.eq(0),
                                self.mem_chain_store_use_load_result.eq(0),
                                self.mem_chain_store_value.eq(0),
                                self.mem_result_value.eq(self.lsu.response_load_value),
                                self.state.eq(V2PipelineState.MEM_TRANSLATE),
                            ]
                        with m.Else():
                            m.d.sync += [
                                self.writeback_reg_write.eq((self.mem_rd != 0) & ~self.mem_write),
                                self.writeback_reg_index.eq(self.mem_rd),
                                self.writeback_reg_value.eq(memory_response_result),
                                self.writeback_aux_reg_write.eq(self.mem_post_reg_write & (self.mem_post_reg_index != 0)),
                                self.writeback_aux_reg_index.eq(self.mem_post_reg_index),
                                self.writeback_aux_reg_value.eq(memory_response_post_value),
                                self.writeback_flags_write.eq(self.mem_flags_write),
                                self.writeback_flags_value.eq(self.mem_flags_value),
                                self.writeback_next_pc.eq(memory_response_next_pc),
                                self.writeback_halt.eq(0),
                                self.writeback_lockup.eq(0),
                                self.writeback_commit_pc.eq(self.execute_pc),
                                self.state.eq(V2PipelineState.WRITEBACK),
                            ]

            with m.Case(V2PipelineState.EXECUTE_COMPLETE):
                m.d.sync += [
                    self.writeback_reg_write.eq(self.execute_complete_reg_write),
                    self.writeback_reg_index.eq(self.execute_complete_reg_index),
                    self.writeback_reg_value.eq(self.execute_complete_reg_value),
                    self.writeback_aux_reg_write.eq(0),
                    self.writeback_aux_reg_index.eq(0),
                    self.writeback_aux_reg_value.eq(0),
                    self.writeback_flags_write.eq(self.execute_complete_flags_write),
                    self.writeback_flags_value.eq(flag_value(self.execute_complete_flag_result, self.execute_complete_flag_carry)),
                    self.writeback_next_pc.eq(self.execute_complete_next_pc),
                    self.writeback_halt.eq(0),
                    self.writeback_lockup.eq(self.execute_complete_lockup),
                    self.writeback_commit_pc.eq(self.execute_complete_commit_pc),
                    self.state.eq(V2PipelineState.WRITEBACK),
                ]

            with m.Case(V2PipelineState.WRITEBACK):
                m.d.comb += [
                    self.commit_valid.eq(1),
                    self.commit_pc.eq(self.writeback_commit_pc),
                ]
                with m.If(self.writeback_reg_write):
                    write_reg(self.writeback_reg_index, self.writeback_reg_value)
                with m.If(self.writeback_aux_reg_write):
                    write_reg(self.writeback_aux_reg_index, self.writeback_aux_reg_value)
                with m.If(self.writeback_flags_write):
                    m.d.sync += self.flags.eq(self.writeback_flags_value)
                m.d.sync += [
                    self.register_file[15].eq(self.writeback_next_pc),
                    self.fetch_pc.eq(self.writeback_next_pc),
                    self.translate_virtual_addr.eq(self.writeback_next_pc),
                    self.translate_access.eq(ACCESS_EXECUTE),
                ]
                with m.If(self.writeback_lockup):
                    enter_lockup()
                with m.Else():
                    m.d.sync += self.state.eq(V2PipelineState.FETCH_TRANSLATE)

            with m.Case(V2PipelineState.WALK):
                with m.If(~self.lsu_started):
                    m.d.sync += self.lsu_started.eq(1)
                with m.If(self.lsu.response_valid):
                    with m.If(self.lsu.response_error):
                        enter_lockup()
                    with m.Else():
                        m.d.sync += [
                            self.walk_pte_latched.eq(self.lsu.response_load_value),
                            self.state.eq(V2PipelineState.WALK_PROCESS),
                        ]

            with m.Case(V2PipelineState.WALK_PROCESS):
                with m.If((walk_pte & PTE_V) == 0):
                    with m.If(self.walk_resume_kind == WalkResumeKind.VECTOR):
                        enter_lockup()
                    with m.Else():
                        raise_sync_trap(TrapVector.PAGE_FAULT_NOT_PRESENT, self.mem_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=encode_aux(AUX_SUBTYPE_NO_VALID_PTE, self.walk_level))
                with m.Elif(walk_reserved):
                    with m.If(self.walk_resume_kind == WalkResumeKind.VECTOR):
                        enter_lockup()
                    with m.Else():
                        raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.mem_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=encode_aux(AUX_SUBTYPE_RESERVED_BIT, self.walk_level))
                with m.Elif((self.walk_level > 0) & walk_is_leaf):
                    with m.If(~walk_permission_ok | ~walk_user_ok):
                        with m.If(self.walk_resume_kind == WalkResumeKind.VECTOR):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_PERMISSION, self.mem_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=encode_aux(AUX_SUBTYPE_PERMISSION, self.walk_level))
                    with m.Else():
                        if self.tlb is not None:
                            m.d.comb += self.tlb.fill_valid.eq(1)
                        with m.If(self.walk_resume_kind == WalkResumeKind.FETCH):
                            m.d.sync += [
                                self.fetch_phys_addr.eq(walk_result_phys),
                                self.state.eq(V2PipelineState.FETCH_REQUEST),
                            ]
                        with m.Elif(self.walk_resume_kind == WalkResumeKind.VECTOR):
                            m.d.sync += [
                                self.interrupt_vector_phys.eq(walk_result_phys),
                                self.lsu_started.eq(0),
                                self.state.eq(V2PipelineState.INTERRUPT_VECTOR_LOAD),
                            ]
                        with m.Else():
                            m.d.sync += [
                                self.mem_addr.eq(walk_result_phys),
                                self.lsu_started.eq(0),
                                self.state.eq(V2PipelineState.MEMORY),
                            ]
                with m.Elif(self.walk_level == 0):
                    with m.If(~walk_is_leaf):
                        with m.If(self.walk_resume_kind == WalkResumeKind.VECTOR):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.mem_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=encode_aux(AUX_SUBTYPE_INVALID_NONLEAF, 0))
                    with m.Elif(~walk_permission_ok | ~walk_user_ok):
                        with m.If(self.walk_resume_kind == WalkResumeKind.VECTOR):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_PERMISSION, self.mem_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=encode_aux(AUX_SUBTYPE_PERMISSION, 0))
                    with m.Else():
                        if self.tlb is not None:
                            m.d.comb += self.tlb.fill_valid.eq(1)
                        with m.If(self.walk_resume_kind == WalkResumeKind.FETCH):
                            m.d.sync += [
                                self.fetch_phys_addr.eq(walk_result_phys),
                                self.state.eq(V2PipelineState.FETCH_REQUEST),
                            ]
                        with m.Elif(self.walk_resume_kind == WalkResumeKind.VECTOR):
                            m.d.sync += [
                                self.interrupt_vector_phys.eq(walk_result_phys),
                                self.lsu_started.eq(0),
                                self.state.eq(V2PipelineState.INTERRUPT_VECTOR_LOAD),
                            ]
                        with m.Else():
                            m.d.sync += [
                                self.mem_addr.eq(walk_result_phys),
                                self.lsu_started.eq(0),
                                self.state.eq(V2PipelineState.MEMORY),
                            ]
                with m.Else():
                    m.d.sync += [
                        self.walk_table_addr.eq(walk_table_next),
                        self.walk_level.eq(self.walk_level - 1),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.WALK),
                    ]

            with m.Case(V2PipelineState.INTERRUPT_VECTOR_TRANSLATE):
                with m.If(paging_enabled & ~Const(1 if self.config.enable_mmu else 0, 1)):
                    enter_lockup()
                with m.Elif(~paging_enabled):
                    m.d.sync += [
                        self.interrupt_vector_phys.eq(self.translate_virtual_addr),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.INTERRUPT_VECTOR_LOAD),
                    ]
                with m.Elif(~is_canonical39(self.translate_virtual_addr)):
                    enter_lockup()
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    enter_lockup()
                with m.Elif(tlb_hit_ok):
                    m.d.sync += [
                        self.interrupt_vector_phys.eq(tlb_lookup_paddr),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.INTERRUPT_VECTOR_LOAD),
                    ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(self.translate_virtual_addr),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(ACCESS_READ),
                        self.walk_resume_kind.eq(WalkResumeKind.VECTOR),
                        self.lsu_started.eq(0),
                        self.state.eq(V2PipelineState.WALK),
                    ]

            with m.Case(V2PipelineState.INTERRUPT_VECTOR_LOAD):
                with m.If(~self.lsu_started):
                    m.d.sync += self.lsu_started.eq(1)
                with m.If(self.lsu.response_valid):
                    with m.If(self.lsu.response_error | (self.lsu.response_load_value == 0)):
                        enter_lockup()
                    with m.Else():
                        m.d.comb += [
                            core_interrupt_epc_write.eq(1),
                            core_interrupt_epc_data.eq(self.interrupt_entry_epc),
                            core_interrupt_eflags_write.eq(1),
                            core_interrupt_eflags_data.eq(self.flags),
                        ]
                        m.d.sync += [
                            self.register_file[15].eq(self.lsu.response_load_value),
                            self.fetch_pc.eq(self.lsu.response_load_value),
                            self.translate_virtual_addr.eq(self.lsu.response_load_value),
                            self.translate_access.eq(ACCESS_EXECUTE),
                            self.state.eq(V2PipelineState.FETCH_TRANSLATE),
                        ]

            with m.Case(V2PipelineState.STALLED):
                m.d.sync += self.state.eq(V2PipelineState.STALLED)

            with m.Case(V2PipelineState.HALTED):
                m.d.sync += self.state.eq(V2PipelineState.HALTED)

        return m


__all__ = ['Little64V2Core', 'V2PipelineState']
