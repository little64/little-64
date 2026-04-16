from __future__ import annotations

from enum import IntEnum

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from .config import Little64CoreConfig
from .isa import (
    CPU_CONTROL_CUR_INT_MASK,
    CPU_CONTROL_CUR_INT_SHIFT,
    CPU_CONTROL_IN_INTERRUPT,
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_PAGING_ENABLE,
    CPU_CONTROL_USER_MODE,
    GPOpcode,
    LSOpcode,
    SpecialRegister,
    TrapVector,
)
from .special_registers import Little64SpecialRegisterFile
from .tlb import Little64TLB
from .wishbone import WishboneMasterInterface


class CoreState(IntEnum):
    RESET = 0
    FETCH_TRANSLATE = 1
    FETCH = 2
    EXECUTE = 3
    MEM_TRANSLATE = 4
    MEM_LOAD = 5
    MEM_STORE = 6
    WALK = 7
    WALK_PROCESS = 8
    HALTED = 9
    INTERRUPT_VECTOR_TRANSLATE = 10
    INTERRUPT_VECTOR_LOAD = 11
    MEM_LOAD_SPLIT = 12
    MEM_STORE_SPLIT = 13


PTE_V = 1 << 0
PTE_R = 1 << 1
PTE_W = 1 << 2
PTE_X = 1 << 3
PTE_U = 1 << 4
PTE_RESERVED_MASK = 0xFFC0000000000000

ACCESS_READ = 0
ACCESS_WRITE = 1
ACCESS_EXECUTE = 2

AUX_SUBTYPE_NONE = 0
AUX_SUBTYPE_NO_VALID_PTE = 1
AUX_SUBTYPE_INVALID_NONLEAF = 2
AUX_SUBTYPE_PERMISSION = 3
AUX_SUBTYPE_RESERVED_BIT = 4
AUX_SUBTYPE_CANONICAL = 5


def _sign_extend(value, width: int, target_width: int):
    extension_width = target_width - width
    if extension_width <= 0:
        return value
    return Cat(
        value,
        Mux(value[width - 1], Const((1 << extension_width) - 1, extension_width), Const(0, extension_width)),
    )


def _flag_value(result, carry):
    return Cat(result == 0, carry, result[63])


def _is_canonical39(addr):
    sign_bit = addr[38]
    upper = addr[39:64]
    return Mux(sign_bit, upper == Const((1 << 25) - 1, 25), upper == 0)


def _encode_aux(subtype: int, level):
    return Const(subtype, 64) | (level << 8)


def _ls_condition(flags, opcode):
    z = flags[0]
    c = flags[1]
    s = flags[2]
    return Mux(opcode == LSOpcode.JUMP_Z, z,
        Mux(opcode == LSOpcode.JUMP_C, c,
        Mux(opcode == LSOpcode.JUMP_S, s,
        Mux(opcode == LSOpcode.JUMP_GT, (~z) & (~s),
        Mux(opcode == LSOpcode.JUMP_LT, s, Const(0, 1))))))


class Little64Core(Elaboratable):
    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.config = config or Little64CoreConfig()

        self.i_bus = WishboneMasterInterface(
            data_width=self.config.instruction_bus_width,
            address_width=self.config.address_width,
            name='i_bus',
        )
        self.d_bus = WishboneMasterInterface(
            data_width=self.config.data_bus_width,
            address_width=self.config.address_width,
            name='d_bus',
        )
        self.irq_lines = Signal(self.config.irq_input_count)
        self.halted = Signal()
        self.locked_up = Signal()
        self.state = Signal(4, init=CoreState.RESET)
        self.current_instruction = Signal(16)
        self.fetch_pc = Signal(64)
        self.fetch_phys_addr = Signal(64)
        self.commit_valid = Signal()
        self.commit_pc = Signal(64)
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)
        self.pending_addr = Signal(64)
        self.pending_virtual_addr = Signal(64)
        self.pending_width_bytes = Signal(4)
        self.pending_rd = Signal(4)
        self.pending_store_value = Signal(64)
        self.pending_next_pc = Signal(64)
        self.pending_fault_pc = Signal(64)
        self.pending_mem_write = Signal()
        self.pending_set_reservation = Signal()
        self.pending_reservation_addr = Signal(64)
        self.pending_post_mem_reg = Signal(4)
        self.pending_post_mem_value = Signal(64)
        self.pending_post_mem_delta = Signal(64)
        self.pending_post_mem_write = Signal()
        self.pending_post_mem_use_load_result = Signal()
        self.pending_chain_store = Signal()
        self.pending_chain_store_addr = Signal(64)
        self.pending_chain_store_use_load_result = Signal()
        self.pending_chain_store_value = Signal(64)
        self.walk_virtual_addr = Signal(64)
        self.walk_table_addr = Signal(64)
        self.walk_level = Signal(2)
        self.walk_access = Signal(2)
        self.walk_resume_state = Signal(4)
        self.walk_pte_latched = Signal(64)
        self.interrupt_entry_vector = Signal(64)
        self.interrupt_entry_epc = Signal(64)
        self.interrupt_vector_phys = Signal(64)

        self.register_file = [
            Signal(64, name=f'r{index}', init=self.config.reset_vector if index == 15 else 0)
            for index in range(16)
        ]
        self.regs = Array(self.register_file)
        self.flags = Signal(3)
        self.ll_reservation_addr = Signal(64)
        self.ll_reservation_valid = Signal()

        self.special_regs = Little64SpecialRegisterFile(self.config)
        self.tlb = Little64TLB(entries=self.config.tlb_entries) if self.config.enable_tlb else None

    def elaborate(self, platform):
        m = Module()
        m.submodules.special_regs = self.special_regs
        if self.tlb is not None:
            m.submodules.tlb = self.tlb

        instruction_words = Array([self.i_bus.dat_r.word_select(index, 16) for index in range(4)])
        current_pc = self.register_file[15]
        post_increment_pc = Signal(64)
        m.d.comb += post_increment_pc.eq(self.fetch_pc + 2)

        paging_enabled = Signal()
        translation_access = Signal(2)
        tlb_lookup_vaddr = Signal(64)
        tlb_hit_ok = Signal()
        tlb_perm_ok = Signal()
        tlb_user_ok = Signal()
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
        current_interrupt_vector = Signal(64)
        irq_line_pending_mask = Signal(64)
        pending_irq_high = Signal(64)
        pending_irq_available = Signal()
        pending_irq_vector = Signal(64)
        can_preempt_pending_irq = Signal()
        interrupt_vector_table_addr = Signal(64)
        reservation_end = Signal(64)
        write_end = Signal(64)
        store_overlaps_reservation = Signal()

        byte_offset = Signal(3)
        base_sel = Signal(8)
        shifted_sel = Signal(16)
        split_needed = Signal()
        first_beat_sel = Signal(8)
        second_beat_sel = Signal(8)
        shifted_dat_w = Signal(128)
        first_beat_dat_w = Signal(64)
        second_beat_dat_w = Signal(64)
        word_aligned_addr = Signal(self.config.address_width)
        next_word_addr = Signal(self.config.address_width)
        single_read_data = Signal(64)
        combined_read_data = Signal(64)
        split_first_data = Signal(64)
        split_first_cycle = Signal()

        irq_valid_mask_high = ((1 << (self.config.irq_input_count + 1)) - 1) & ~1
        cpu_control_entry_clear_mask = (
            CPU_CONTROL_INT_ENABLE |
            CPU_CONTROL_IN_INTERRUPT |
            CPU_CONTROL_CUR_INT_MASK |
            CPU_CONTROL_USER_MODE
        )

        a = Signal(64)
        b = Signal(64)
        rd = self.current_instruction[0:4]
        rs1 = self.current_instruction[4:8]
        gp_opcode = self.current_instruction[8:13]
        top2 = self.current_instruction[14:16]
        top3 = self.current_instruction[13:16]
        ls_opcode = self.current_instruction[10:14]
        ls_offset2 = self.current_instruction[8:10]

        ls_rd_value = Signal(64)
        ls_rs1_value = Signal(64)
        ls_addr = Signal(64)
        ls_push_addr = Signal(64)
        m.d.comb += [
            ls_rd_value.eq(Mux(rd == 15, post_increment_pc, a)),
            ls_rs1_value.eq(Mux(rs1 == 15, post_increment_pc, b)),
            ls_addr.eq(ls_rs1_value + (ls_offset2 << 1)),
            ls_push_addr.eq(ls_rd_value - 8),
        ]

        ls_pc_rel6 = _sign_extend(self.current_instruction[4:10], 6, 64)
        ls_pc_rel10 = _sign_extend(self.current_instruction[:10], 10, 64)
        ls_pc_effective = Signal(64)
        ls_jump_effective = Signal(64)
        ls_pc_push_addr = Signal(64)
        m.d.comb += [
            ls_pc_effective.eq(post_increment_pc + (ls_pc_rel6 << 1)),
            ls_jump_effective.eq(post_increment_pc + (ls_pc_rel10 << 1)),
            ls_pc_push_addr.eq(a - 8),
        ]

        m.d.comb += [
            a.eq(self.regs[rd]),
            b.eq(self.regs[rs1]),
        ]

        shift_index = Signal(7)
        m.d.comb += shift_index.eq(Mux(b >= 64, 64, b[:7]))

        sll_results = Array([
            a if amount == 0 else Const(0, 64) if amount == 64 else (a << amount)[:64]
            for amount in range(65)
        ])
        sll_carries = Array([
            Const(0, 1)
            if amount in (0, 64) else ((a >> (64 - amount)) != 0)
            for amount in range(65)
        ])

        srl_results = Array([
            a if amount == 0 else Const(0, 64) if amount == 64 else a >> amount
            for amount in range(65)
        ])
        srl_carries = Array([
            Const(0, 1)
            if amount in (0, 64) else (((a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])

        sra_results = Array([
            a if amount == 0 else
            Mux(a[63], Const(0xFFFFFFFFFFFFFFFF, 64), Const(0, 64)) if amount == 64 else
            (a.as_signed() >> amount).as_unsigned()
            for amount in range(65)
        ])
        sra_carries = Array([
            Const(0, 1)
            if amount in (0, 64) else (((a >> (amount - 1)) & 1) != 0)
            for amount in range(65)
        ])

        slli_results = Array([
            a if amount == 0 else (a << amount)[:64]
            for amount in range(16)
        ])
        slli_carries = Array([
            Const(0, 1)
            if amount == 0 else ((a >> (64 - amount)) != 0)
            for amount in range(16)
        ])

        srli_results = Array([
            a if amount == 0 else a >> amount
            for amount in range(16)
        ])
        srli_carries = Array([
            Const(0, 1)
            if amount == 0 else (((a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])

        srai_results = Array([
            a if amount == 0 else (a.as_signed() >> amount).as_unsigned()
            for amount in range(16)
        ])
        srai_carries = Array([
            Const(0, 1)
            if amount == 0 else (((a >> (amount - 1)) & 1) != 0)
            for amount in range(16)
        ])

        if self.tlb is not None:
            m.d.comb += [
                self.tlb.lookup_vaddr.eq(tlb_lookup_vaddr),
                self.tlb.flush_all.eq(self.special_regs.tlb_flush),
                self.tlb.fill_valid.eq(0),
                self.tlb.fill_vaddr.eq(self.walk_virtual_addr),
                self.tlb.fill_paddr.eq(walk_result_phys & Const(~0xFFF & ((1 << self.config.address_width) - 1), self.config.address_width)),
                self.tlb.fill_perm_read.eq((walk_pte & PTE_R) != 0),
                self.tlb.fill_perm_write.eq((walk_pte & PTE_W) != 0),
                self.tlb.fill_perm_execute.eq((walk_pte & PTE_X) != 0),
                self.tlb.fill_perm_user.eq((walk_pte & PTE_U) != 0),
            ]

        m.d.comb += [
            paging_enabled.eq(self.special_regs.cpu_control[16]),
            translation_access.eq(Mux(self.state == CoreState.FETCH_TRANSLATE,
                                      ACCESS_EXECUTE,
                                      Mux(self.state == CoreState.INTERRUPT_VECTOR_TRANSLATE,
                                          ACCESS_READ,
                                          Mux(self.pending_mem_write, ACCESS_WRITE, ACCESS_READ)))),
            special_write_active.eq((self.state == CoreState.EXECUTE) & (top3 == 0b110) & (gp_opcode == GPOpcode.SSR)),
            current_interrupt_vector.eq((self.special_regs.cpu_control & CPU_CONTROL_CUR_INT_MASK) >> CPU_CONTROL_CUR_INT_SHIFT),
            irq_line_pending_mask.eq(Cat(Const(0, 1), self.irq_lines, Const(0, 63 - self.config.irq_input_count))),
            pending_irq_high.eq((self.special_regs.interrupt_states_high | irq_line_pending_mask) & self.special_regs.interrupt_mask_high & Const(irq_valid_mask_high, 64)),
            pending_irq_available.eq(0),
            pending_irq_vector.eq(0),
            can_preempt_pending_irq.eq((~self.special_regs.cpu_control[1]) |
                                       (current_interrupt_vector == 0) |
                                       (current_interrupt_vector > pending_irq_vector)),
            interrupt_vector_table_addr.eq(self.special_regs.interrupt_table_base + (self.interrupt_entry_vector << 3)),
            tlb_lookup_vaddr.eq(Mux(self.state == CoreState.FETCH_TRANSLATE,
                               current_pc,
                               Mux(self.state == CoreState.INTERRUPT_VECTOR_TRANSLATE,
                                   interrupt_vector_table_addr,
                                   self.pending_addr))),
            tlb_perm_ok.eq(Mux(translation_access == ACCESS_READ,
                               self.tlb.lookup_perm_read if self.tlb is not None else Const(0, 1),
                               Mux(translation_access == ACCESS_WRITE,
                                   self.tlb.lookup_perm_write if self.tlb is not None else Const(0, 1),
                                   self.tlb.lookup_perm_execute if self.tlb is not None else Const(0, 1)))),
            tlb_user_ok.eq((~self.special_regs.cpu_control[17]) |
                           (self.tlb.lookup_perm_user if self.tlb is not None else Const(0, 1))),
            tlb_hit_ok.eq((self.tlb.lookup_hit if self.tlb is not None else Const(0, 1)) & tlb_perm_ok & tlb_user_ok),
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
            write_end.eq(self.pending_virtual_addr + self.pending_width_bytes - 1),
            store_overlaps_reservation.eq(
                self.ll_reservation_valid &
                (self.pending_width_bytes != 0) &
                (self.pending_virtual_addr <= reservation_end) &
                (self.ll_reservation_addr <= write_end)
            ),
        ]

        m.d.comb += [
            byte_offset.eq(self.pending_addr[0:3]),
            base_sel.eq(Mux(self.pending_width_bytes == 1, 0x01,
                        Mux(self.pending_width_bytes == 2, 0x03,
                        Mux(self.pending_width_bytes == 4, 0x0F,
                        Mux(self.pending_width_bytes == 8, 0xFF, 0x00))))),
            word_aligned_addr.eq(self.pending_addr & Const(~0x7 & ((1 << self.config.address_width) - 1), self.config.address_width)),
            next_word_addr.eq(word_aligned_addr + 8),
            first_beat_sel.eq(shifted_sel[0:8]),
            second_beat_sel.eq(shifted_sel[8:16]),
            first_beat_dat_w.eq(shifted_dat_w[0:64]),
            second_beat_dat_w.eq(shifted_dat_w[64:128]),
            split_needed.eq(shifted_sel[8:16] != 0),
        ]

        with m.Switch(byte_offset):
            for i in range(8):
                with m.Case(i):
                    m.d.comb += [
                        shifted_sel.eq(base_sel << i),
                        shifted_dat_w.eq(self.pending_store_value << (i * 8)),
                    ]

        with m.Switch(byte_offset):
            for i in range(8):
                with m.Case(i):
                    if i == 0:
                        m.d.comb += single_read_data.eq(self.d_bus.dat_r)
                    else:
                        m.d.comb += single_read_data.eq(Cat(self.d_bus.dat_r[i * 8:64], Const(0, i * 8)))

        with m.Switch(byte_offset):
            for i in range(8):
                with m.Case(i):
                    if i == 0:
                        m.d.comb += combined_read_data.eq(split_first_data)
                    else:
                        m.d.comb += combined_read_data.eq(Cat(split_first_data[i * 8:64], self.d_bus.dat_r[0:i * 8]))

        m.d.comb += [
            self.special_regs.user_mode.eq(self.special_regs.cpu_control[17]),
            self.special_regs.read_selector.eq(b[:16]),
            self.special_regs.write_stb.eq(special_write_active),
            self.special_regs.write_selector.eq(b[:16]),
            self.special_regs.write_data.eq(a),
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
                (irq_line_pending_mask != 0) & ~(special_write_active & (b[:16] == SpecialRegister.INTERRUPT_STATES_HIGH)),
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
            self.commit_valid.eq(0),
            self.commit_pc.eq(self.fetch_pc),
            self.i_bus.adr.eq(self.fetch_phys_addr & Const(~0x7 & ((1 << self.config.address_width) - 1), self.config.address_width)),
            self.i_bus.dat_w.eq(0),
            self.i_bus.sel.eq((1 << self.i_bus.sel_width) - 1),
            self.i_bus.cyc.eq(self.state == CoreState.FETCH),
            self.i_bus.stb.eq(self.state == CoreState.FETCH),
            self.i_bus.we.eq(0),
            self.i_bus.cti.eq(0),
            self.i_bus.bte.eq(0),
            self.d_bus.adr.eq(Mux(self.state == CoreState.WALK, walk_pte_addr,
                              Mux(self.state == CoreState.INTERRUPT_VECTOR_LOAD, self.interrupt_vector_phys,
                              Mux((self.state == CoreState.MEM_LOAD_SPLIT) | (self.state == CoreState.MEM_STORE_SPLIT), next_word_addr,
                              word_aligned_addr)))),
            self.d_bus.dat_w.eq(Mux((self.state == CoreState.WALK) | (self.state == CoreState.INTERRUPT_VECTOR_LOAD), 0,
                              Mux((self.state == CoreState.MEM_STORE_SPLIT), second_beat_dat_w,
                              first_beat_dat_w))),
            self.d_bus.sel.eq(Mux((self.state == CoreState.WALK) | (self.state == CoreState.INTERRUPT_VECTOR_LOAD), 0xFF,
                              Mux((self.state == CoreState.MEM_LOAD_SPLIT) | (self.state == CoreState.MEM_STORE_SPLIT), second_beat_sel,
                              first_beat_sel))),
            self.d_bus.cyc.eq((self.state == CoreState.MEM_LOAD) | (self.state == CoreState.MEM_STORE) | (self.state == CoreState.WALK) | (self.state == CoreState.INTERRUPT_VECTOR_LOAD)
                              | (((self.state == CoreState.MEM_LOAD_SPLIT) | (self.state == CoreState.MEM_STORE_SPLIT)) & ~split_first_cycle)),
            self.d_bus.stb.eq((self.state == CoreState.MEM_LOAD) | (self.state == CoreState.MEM_STORE) | (self.state == CoreState.WALK) | (self.state == CoreState.INTERRUPT_VECTOR_LOAD)
                              | (((self.state == CoreState.MEM_LOAD_SPLIT) | (self.state == CoreState.MEM_STORE_SPLIT)) & ~split_first_cycle)),
            self.d_bus.we.eq((self.state == CoreState.MEM_STORE) | ((self.state == CoreState.MEM_STORE_SPLIT) & ~split_first_cycle)),
            self.d_bus.cti.eq(0),
            self.d_bus.bte.eq(0),
        ]

        for bit_index in range(self.config.irq_input_count, 0, -1):
            with m.If(pending_irq_high[bit_index]):
                m.d.comb += [
                    pending_irq_available.eq(1),
                    pending_irq_vector.eq(64 + bit_index),
                ]

        m.d.sync += self.register_file[0].eq(0)

        def write_reg(index_signal, value):
            with m.Switch(index_signal):
                for index in range(1, 16):
                    with m.Case(index):
                        m.d.sync += self.register_file[index].eq(value)

        def enter_lockup():
            m.d.sync += [
                self.locked_up.eq(1),
                self.state.eq(CoreState.HALTED),
            ]

        def begin_interrupt_entry(vector, epc):
            m.d.comb += [
                core_interrupt_cpu_control_write.eq(1),
                core_interrupt_cpu_control_data.eq(self.special_regs.cpu_control),
                core_cpu_control_write.eq(1),
                core_cpu_control_data.eq(
                    (self.special_regs.cpu_control & Const((1 << 64) - 1 - cpu_control_entry_clear_mask, 64)) |
                    Const(CPU_CONTROL_IN_INTERRUPT, 64) |
                    (vector << CPU_CONTROL_CUR_INT_SHIFT)
                ),
            ]
            m.d.sync += [
                self.interrupt_entry_vector.eq(vector),
                self.interrupt_entry_epc.eq(epc),
                self.state.eq(CoreState.INTERRUPT_VECTOR_TRANSLATE),
            ]

        def raise_sync_trap(vector, trap_pc, *, fault_addr=0, access=0, aux=0):
            m.d.comb += self.commit_valid.eq(0)
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

        with m.Switch(self.state):
            with m.Case(CoreState.RESET):
                m.d.sync += [
                    self.register_file[1].eq(self.boot_r1),
                    self.register_file[13].eq(self.boot_r13),
                    self.register_file[15].eq(self.config.reset_vector),
                    self.flags.eq(0),
                    self.ll_reservation_addr.eq(0),
                    self.ll_reservation_valid.eq(0),
                    self.halted.eq(0),
                    self.locked_up.eq(0),
                    self.state.eq(CoreState.FETCH_TRANSLATE),
                ]
                m.d.comb += [
                    core_trap_write.eq(1),
                    core_trap_cause_data.eq(0),
                    core_trap_fault_addr_data.eq(0),
                    core_trap_access_data.eq(0),
                    core_trap_pc_data.eq(0),
                    core_trap_aux_data.eq(0),
                ]

            with m.Case(CoreState.FETCH_TRANSLATE):
                with m.If(current_pc[0]):
                    raise_sync_trap(TrapVector.EXEC_ALIGN, current_pc, fault_addr=current_pc, access=ACCESS_EXECUTE, aux=_encode_aux(AUX_SUBTYPE_NONE, Const(0, 64)))
                with m.Elif(paging_enabled & ~Const(int(self.config.enable_mmu), 1)):
                    enter_lockup()
                with m.Elif(pending_irq_available & self.special_regs.cpu_control[0] & can_preempt_pending_irq):
                    begin_interrupt_entry(pending_irq_vector, current_pc)
                with m.Elif(~paging_enabled):
                    m.d.sync += [
                        self.fetch_phys_addr.eq(current_pc),
                        self.state.eq(CoreState.FETCH),
                    ]
                with m.Elif(~_is_canonical39(current_pc)):
                    raise_sync_trap(TrapVector.PAGE_FAULT_CANONICAL, current_pc, fault_addr=current_pc, access=ACCESS_EXECUTE, aux=_encode_aux(AUX_SUBTYPE_CANONICAL, Const(2, 64)))
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, current_pc, fault_addr=current_pc, access=ACCESS_EXECUTE, aux=_encode_aux(AUX_SUBTYPE_RESERVED_BIT, Const(2, 64)))
                with m.Elif(self.tlb is not None):
                    with m.If(tlb_hit_ok):
                        m.d.sync += [
                            self.fetch_phys_addr.eq(self.tlb.lookup_paddr),
                            self.state.eq(CoreState.FETCH),
                        ]
                    with m.Else():
                        m.d.sync += [
                            self.walk_virtual_addr.eq(current_pc),
                            self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                            self.walk_level.eq(2),
                            self.walk_access.eq(ACCESS_EXECUTE),
                            self.walk_resume_state.eq(CoreState.FETCH),
                            self.pending_fault_pc.eq(current_pc),
                            self.state.eq(CoreState.WALK),
                        ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(current_pc),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(ACCESS_EXECUTE),
                        self.walk_resume_state.eq(CoreState.FETCH),
                        self.pending_fault_pc.eq(current_pc),
                        self.state.eq(CoreState.WALK),
                    ]

            with m.Case(CoreState.FETCH):
                with m.If(self.i_bus.err):
                    m.d.sync += [
                        self.locked_up.eq(1),
                        self.state.eq(CoreState.HALTED),
                    ]
                with m.Elif(self.i_bus.ack):
                    m.d.sync += [
                        self.fetch_pc.eq(current_pc),
                        self.current_instruction.eq(instruction_words[self.fetch_phys_addr[1:3]]),
                        self.state.eq(CoreState.EXECUTE),
                    ]

            with m.Case(CoreState.EXECUTE):
                with m.If(top2 == 0b10):
                    shift = self.current_instruction[12:14]
                    imm8 = self.current_instruction[4:12]
                    rd_value = self.regs[rd]
                    ldi_value = Signal(64)
                    m.d.comb += ldi_value.eq(rd_value)

                    with m.Switch(shift):
                        with m.Case(0):
                            m.d.comb += ldi_value.eq(imm8)
                        with m.Case(1):
                            m.d.comb += ldi_value.eq(rd_value | (imm8 << 8))
                        with m.Case(2):
                            m.d.comb += ldi_value.eq(rd_value | (imm8 << 16))
                        with m.Case(3):
                            sign_extended_imm = _sign_extend(Cat(Const(0, 24), imm8), 32, 64)
                            m.d.comb += ldi_value.eq(rd_value | sign_extended_imm)

                    write_reg(rd, ldi_value)
                    m.d.comb += self.commit_valid.eq(1)
                    m.d.sync += [
                        self.register_file[15].eq(post_increment_pc),
                        self.state.eq(CoreState.FETCH_TRANSLATE),
                    ]
                with m.Elif(top2 == 0b00):
                    push_addr = Signal(64)
                    m.d.comb += push_addr.eq(a - 8)

                    with m.Switch(ls_opcode):
                        with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                            load_width = Signal(4)
                            m.d.comb += load_width.eq(Mux(ls_opcode == LSOpcode.BYTE_LOAD, 1,
                                                      Mux(ls_opcode == LSOpcode.SHORT_LOAD, 2,
                                                      Mux(ls_opcode == LSOpcode.WORD_LOAD, 4, 8))))
                            m.d.sync += [
                                self.pending_addr.eq(ls_addr),
                                self.pending_virtual_addr.eq(ls_addr),
                                self.pending_width_bytes.eq(load_width),
                                self.pending_rd.eq(rd),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                            store_width = Signal(4)
                            m.d.comb += store_width.eq(Mux(ls_opcode == LSOpcode.BYTE_STORE, 1,
                                                       Mux(ls_opcode == LSOpcode.SHORT_STORE, 2,
                                                       Mux(ls_opcode == LSOpcode.WORD_STORE, 4, 8))))
                            m.d.sync += [
                                self.pending_addr.eq(ls_addr),
                                self.pending_virtual_addr.eq(ls_addr),
                                self.pending_width_bytes.eq(store_width),
                                self.pending_store_value.eq(ls_rd_value),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(1),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.PUSH):
                            write_reg(rd, ls_push_addr)
                            m.d.sync += [
                                self.pending_addr.eq(ls_push_addr),
                                self.pending_virtual_addr.eq(ls_push_addr),
                                self.pending_width_bytes.eq(8),
                                self.pending_store_value.eq(ls_rs1_value),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(1),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.POP):
                            m.d.sync += [
                                self.pending_addr.eq(ls_rd_value),
                                self.pending_virtual_addr.eq(ls_rd_value),
                                self.pending_width_bytes.eq(8),
                                self.pending_rd.eq(rs1),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_reg.eq(rd),
                                self.pending_post_mem_value.eq(ls_rd_value + 8),
                                self.pending_post_mem_delta.eq(8),
                                self.pending_post_mem_write.eq(1),
                                self.pending_post_mem_use_load_result.eq(rd == rs1),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.MOVE):
                            write_reg(rd, ls_addr)
                            m.d.comb += self.commit_valid.eq(1)
                            m.d.sync += [
                                self.register_file[15].eq(Mux(rd == 15, ls_addr, post_increment_pc)),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                            with m.If(_ls_condition(self.flags, ls_opcode)):
                                write_reg(rd, ls_addr)
                            m.d.comb += self.commit_valid.eq(1)
                            m.d.sync += [
                                self.register_file[15].eq(Mux(_ls_condition(self.flags, ls_opcode) & (rd == 15), ls_addr, post_increment_pc)),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Default():
                            m.d.sync += [
                                self.locked_up.eq(1),
                                self.state.eq(CoreState.HALTED),
                            ]
                with m.Elif(top2 == 0b01):
                    with m.Switch(ls_opcode):
                        with m.Case(LSOpcode.LOAD, LSOpcode.BYTE_LOAD, LSOpcode.SHORT_LOAD, LSOpcode.WORD_LOAD):
                            load_width = Signal(4)
                            m.d.comb += load_width.eq(Mux(ls_opcode == LSOpcode.BYTE_LOAD, 1,
                                                      Mux(ls_opcode == LSOpcode.SHORT_LOAD, 2,
                                                      Mux(ls_opcode == LSOpcode.WORD_LOAD, 4, 8))))
                            m.d.sync += [
                                self.pending_addr.eq(ls_pc_effective),
                                self.pending_virtual_addr.eq(ls_pc_effective),
                                self.pending_width_bytes.eq(load_width),
                                self.pending_rd.eq(rd),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.STORE, LSOpcode.BYTE_STORE, LSOpcode.SHORT_STORE, LSOpcode.WORD_STORE):
                            store_width = Signal(4)
                            m.d.comb += store_width.eq(Mux(ls_opcode == LSOpcode.BYTE_STORE, 1,
                                                       Mux(ls_opcode == LSOpcode.SHORT_STORE, 2,
                                                       Mux(ls_opcode == LSOpcode.WORD_STORE, 4, 8))))
                            m.d.sync += [
                                self.pending_addr.eq(ls_pc_effective),
                                self.pending_virtual_addr.eq(ls_pc_effective),
                                self.pending_width_bytes.eq(store_width),
                                self.pending_store_value.eq(a),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(1),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.PUSH):
                            m.d.sync += [
                                self.pending_addr.eq(ls_pc_effective),
                                self.pending_virtual_addr.eq(ls_pc_effective),
                                self.pending_width_bytes.eq(8),
                                self.pending_rd.eq(0),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_reg.eq(rd),
                                self.pending_post_mem_value.eq(ls_pc_push_addr),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_post_mem_write.eq(1),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_chain_store.eq(1),
                                self.pending_chain_store_addr.eq(ls_pc_push_addr),
                                self.pending_chain_store_use_load_result.eq(1),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.POP):
                            m.d.sync += [
                                self.pending_addr.eq(a),
                                self.pending_virtual_addr.eq(a),
                                self.pending_width_bytes.eq(8),
                                self.pending_rd.eq(0),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_reg.eq(rd),
                                self.pending_post_mem_value.eq(a + 8),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_post_mem_write.eq(1),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_chain_store.eq(1),
                                self.pending_chain_store_addr.eq(ls_pc_effective),
                                self.pending_chain_store_use_load_result.eq(1),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.MOVE):
                            write_reg(rd, ls_pc_effective)
                            m.d.comb += self.commit_valid.eq(1)
                            m.d.sync += [
                                self.register_file[15].eq(Mux(rd == 15, ls_pc_effective, post_increment_pc)),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(LSOpcode.JUMP_Z, LSOpcode.JUMP_C, LSOpcode.JUMP_S, LSOpcode.JUMP_GT, LSOpcode.JUMP_LT):
                            with m.If(_ls_condition(self.flags, ls_opcode)):
                                m.d.sync += self.register_file[15].eq(ls_jump_effective)
                            with m.Else():
                                m.d.sync += self.register_file[15].eq(post_increment_pc)
                            m.d.comb += self.commit_valid.eq(1)
                            m.d.sync += self.state.eq(CoreState.FETCH_TRANSLATE)
                        with m.Default():
                            m.d.sync += [
                                self.locked_up.eq(1),
                                self.state.eq(CoreState.HALTED),
                            ]
                with m.Elif(top3 == 0b110):
                    m.d.comb += self.commit_valid.eq(1)
                    sum_value = Signal(65)
                    sub_value = Signal(64)
                    imm4 = self.current_instruction[4:8]
                    m.d.comb += [
                        sum_value.eq(a + b),
                        sub_value.eq(a - b),
                    ]

                    with m.Switch(gp_opcode):
                        with m.Case(GPOpcode.ADD):
                            write_reg(rd, sum_value[:64])
                            m.d.sync += [
                                self.flags.eq(_flag_value(sum_value[:64], sum_value[64])),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SUB):
                            write_reg(rd, sub_value)
                            m.d.sync += [
                                self.flags.eq(_flag_value(sub_value, b > a)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.TEST):
                            m.d.sync += [
                                self.flags.eq(_flag_value(sub_value, b > a)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.LLR):
                            m.d.comb += self.commit_valid.eq(0)
                            m.d.sync += [
                                self.pending_addr.eq(b),
                                self.pending_virtual_addr.eq(b),
                                self.pending_width_bytes.eq(8),
                                self.pending_rd.eq(rd),
                                self.pending_next_pc.eq(post_increment_pc),
                                self.pending_fault_pc.eq(self.fetch_pc),
                                self.pending_mem_write.eq(0),
                                self.pending_set_reservation.eq(1),
                                self.pending_reservation_addr.eq(b),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SCR):
                            with m.If(self.ll_reservation_valid & (self.ll_reservation_addr == b)):
                                m.d.comb += self.commit_valid.eq(0)
                                m.d.sync += [
                                    self.ll_reservation_valid.eq(0),
                                    self.flags.eq(Cat(Const(1, 1), self.flags[1], self.flags[2])),
                                    self.pending_addr.eq(b),
                                    self.pending_virtual_addr.eq(b),
                                    self.pending_width_bytes.eq(8),
                                    self.pending_store_value.eq(a),
                                    self.pending_next_pc.eq(post_increment_pc),
                                    self.pending_fault_pc.eq(self.fetch_pc),
                                    self.pending_mem_write.eq(1),
                                    self.pending_set_reservation.eq(0),
                                    self.pending_post_mem_write.eq(0),
                                    self.pending_post_mem_use_load_result.eq(0),
                                    self.pending_post_mem_delta.eq(0),
                                    self.pending_chain_store.eq(0),
                                    self.pending_chain_store_use_load_result.eq(0),
                                    self.pending_chain_store_value.eq(0),
                                    self.state.eq(CoreState.MEM_TRANSLATE),
                                ]
                            with m.Else():
                                m.d.sync += [
                                    self.ll_reservation_valid.eq(0),
                                    self.flags.eq(Cat(Const(0, 1), self.flags[1], self.flags[2])),
                                    self.register_file[15].eq(post_increment_pc),
                                    self.state.eq(CoreState.FETCH_TRANSLATE),
                                ]
                        with m.Case(GPOpcode.AND):
                            result = a & b
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, Const(0, 1))),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.OR):
                            result = a | b
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, Const(0, 1))),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.XOR):
                            result = a ^ b
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, Const(0, 1))),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SLL):
                            result = sll_results[shift_index]
                            carry = sll_carries[shift_index]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SRL):
                            result = srl_results[shift_index]
                            carry = srl_carries[shift_index]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SRA):
                            result = sra_results[shift_index]
                            carry = sra_carries[shift_index]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SLLI):
                            imm = imm4
                            result = slli_results[imm]
                            carry = slli_carries[imm]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SRLI):
                            imm = imm4
                            result = srli_results[imm]
                            carry = srli_carries[imm]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.SRAI):
                            imm = imm4
                            result = srai_results[imm]
                            carry = srai_carries[imm]
                            write_reg(rd, result)
                            m.d.sync += [
                                self.flags.eq(_flag_value(result, carry)),
                                self.register_file[15].eq(post_increment_pc),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]
                        with m.Case(GPOpcode.LSR):
                            with m.If(self.special_regs.read_access_fault):
                                raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.fetch_pc)
                            with m.Else():
                                write_reg(rd, self.special_regs.read_data)
                                m.d.sync += [
                                    self.register_file[15].eq(post_increment_pc),
                                    self.state.eq(CoreState.FETCH_TRANSLATE),
                                ]
                        with m.Case(GPOpcode.SSR):
                            with m.If(self.special_regs.write_access_fault):
                                raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.fetch_pc)
                            with m.Else():
                                m.d.sync += [
                                    self.register_file[15].eq(post_increment_pc),
                                    self.state.eq(CoreState.FETCH_TRANSLATE),
                                ]
                        with m.Case(GPOpcode.SYSCALL):
                            raise_sync_trap(Mux(self.special_regs.cpu_control[17], TrapVector.SYSCALL, TrapVector.SYSCALL_FROM_SUPERVISOR), self.fetch_pc)
                        with m.Case(GPOpcode.IRET):
                            with m.If(self.special_regs.cpu_control[17]):
                                raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.fetch_pc)
                            with m.Else():
                                m.d.comb += [
                                    core_cpu_control_write.eq(1),
                                    core_cpu_control_data.eq(self.special_regs.interrupt_cpu_control),
                                ]
                                m.d.sync += [
                                    self.register_file[15].eq(self.special_regs.interrupt_epc),
                                    self.flags.eq(self.special_regs.interrupt_eflags[:3]),
                                    self.state.eq(CoreState.FETCH_TRANSLATE),
                                ]
                        with m.Case(GPOpcode.STOP):
                            with m.If(self.special_regs.cpu_control[17]):
                                raise_sync_trap(TrapVector.PRIVILEGED_INSTRUCTION, self.fetch_pc)
                            with m.Else():
                                m.d.sync += [
                                    self.register_file[15].eq(post_increment_pc),
                                    self.halted.eq(1),
                                    self.state.eq(CoreState.HALTED),
                                ]
                        with m.Default():
                            raise_sync_trap(TrapVector.INVALID_INSTRUCTION, self.fetch_pc)
                with m.Elif(top3 == 0b111):
                    jump_offset = _sign_extend(self.current_instruction[:13], 13, 64) << 1
                    m.d.comb += self.commit_valid.eq(1)
                    m.d.sync += [
                        self.register_file[15].eq(post_increment_pc + jump_offset),
                        self.state.eq(CoreState.FETCH_TRANSLATE),
                    ]
                with m.Else():
                    m.d.sync += [
                        self.locked_up.eq(1),
                        self.state.eq(CoreState.HALTED),
                    ]

            with m.Case(CoreState.MEM_TRANSLATE):
                with m.If(paging_enabled & ~Const(int(self.config.enable_mmu), 1)):
                    enter_lockup()
                with m.Elif(~paging_enabled):
                    m.d.sync += self.state.eq(Mux(self.pending_mem_write, CoreState.MEM_STORE, CoreState.MEM_LOAD))
                with m.Elif(~_is_canonical39(self.pending_addr)):
                    raise_sync_trap(TrapVector.PAGE_FAULT_CANONICAL, self.pending_fault_pc, fault_addr=self.pending_virtual_addr, access=Mux(self.pending_mem_write, ACCESS_WRITE, ACCESS_READ), aux=_encode_aux(AUX_SUBTYPE_CANONICAL, Const(2, 64)))
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.pending_fault_pc, fault_addr=self.pending_virtual_addr, access=Mux(self.pending_mem_write, ACCESS_WRITE, ACCESS_READ), aux=_encode_aux(AUX_SUBTYPE_RESERVED_BIT, Const(2, 64)))
                with m.Elif(self.tlb is not None):
                    with m.If(tlb_hit_ok):
                        m.d.sync += [
                            self.pending_addr.eq(self.tlb.lookup_paddr),
                            self.state.eq(Mux(self.pending_mem_write, CoreState.MEM_STORE, CoreState.MEM_LOAD)),
                        ]
                    with m.Else():
                        m.d.sync += [
                            self.walk_virtual_addr.eq(self.pending_virtual_addr),
                            self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                            self.walk_level.eq(2),
                            self.walk_access.eq(Mux(self.pending_mem_write, ACCESS_WRITE, ACCESS_READ)),
                            self.walk_resume_state.eq(Mux(self.pending_mem_write, CoreState.MEM_STORE, CoreState.MEM_LOAD)),
                            self.state.eq(CoreState.WALK),
                        ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(self.pending_virtual_addr),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(Mux(self.pending_mem_write, ACCESS_WRITE, ACCESS_READ)),
                        self.walk_resume_state.eq(Mux(self.pending_mem_write, CoreState.MEM_STORE, CoreState.MEM_LOAD)),
                        self.state.eq(CoreState.WALK),
                    ]

            with m.Case(CoreState.MEM_LOAD):
                with m.If(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    with m.If(split_needed):
                        m.d.sync += [
                            split_first_data.eq(self.d_bus.dat_r),
                            split_first_cycle.eq(1),
                            self.state.eq(CoreState.MEM_LOAD_SPLIT),
                        ]
                    with m.Else():
                        load_result = Signal(64, name='load_result_single')
                        post_mem_value = Signal(64, name='post_mem_value_single')
                        next_pc_after_load = Signal(64, name='next_pc_after_load_single')
                        m.d.comb += load_result.eq(Mux(self.pending_width_bytes == 1, single_read_data & 0xFF,
                                                   Mux(self.pending_width_bytes == 2, single_read_data & 0xFFFF,
                                                   Mux(self.pending_width_bytes == 4, single_read_data & 0xFFFFFFFF,
                                                   single_read_data))))
                        m.d.comb += post_mem_value.eq(Mux(self.pending_post_mem_use_load_result,
                                                      load_result + self.pending_post_mem_delta,
                                                      self.pending_post_mem_value))
                        m.d.comb += next_pc_after_load.eq(
                            Mux(self.pending_post_mem_write & (self.pending_post_mem_reg == 15),
                                post_mem_value,
                                Mux(self.pending_rd == 15, load_result, self.pending_next_pc))
                        )
                        write_reg(self.pending_rd, load_result)
                        with m.If(self.pending_post_mem_write):
                            write_reg(self.pending_post_mem_reg, post_mem_value)
                        with m.If(self.pending_set_reservation):
                            m.d.sync += [
                                self.ll_reservation_addr.eq(self.pending_reservation_addr),
                                self.ll_reservation_valid.eq(1),
                            ]
                        with m.If(self.pending_chain_store):
                            m.d.sync += [
                                self.pending_addr.eq(self.pending_chain_store_addr),
                                self.pending_virtual_addr.eq(self.pending_chain_store_addr),
                                self.pending_width_bytes.eq(8),
                                self.pending_store_value.eq(Mux(self.pending_chain_store_use_load_result, load_result, self.pending_chain_store_value)),
                                self.pending_mem_write.eq(1),
                                self.pending_set_reservation.eq(0),
                                self.pending_post_mem_write.eq(0),
                                self.pending_post_mem_use_load_result.eq(0),
                                self.pending_post_mem_delta.eq(0),
                                self.pending_chain_store.eq(0),
                                self.pending_chain_store_use_load_result.eq(0),
                                self.pending_chain_store_value.eq(0),
                                self.state.eq(CoreState.MEM_TRANSLATE),
                            ]
                        with m.Else():
                            m.d.comb += self.commit_valid.eq(1)
                            m.d.sync += [
                                self.register_file[15].eq(next_pc_after_load),
                                self.state.eq(CoreState.FETCH_TRANSLATE),
                            ]

            with m.Case(CoreState.MEM_LOAD_SPLIT):
                with m.If(split_first_cycle):
                    m.d.sync += split_first_cycle.eq(0)
                with m.Elif(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    load_result_split = Signal(64, name='load_result_split')
                    post_mem_value_split = Signal(64, name='post_mem_value_split')
                    next_pc_after_load_split = Signal(64, name='next_pc_after_load_split')
                    m.d.comb += load_result_split.eq(Mux(self.pending_width_bytes == 1, combined_read_data & 0xFF,
                                                     Mux(self.pending_width_bytes == 2, combined_read_data & 0xFFFF,
                                                     Mux(self.pending_width_bytes == 4, combined_read_data & 0xFFFFFFFF,
                                                     combined_read_data))))
                    m.d.comb += post_mem_value_split.eq(Mux(self.pending_post_mem_use_load_result,
                                                        load_result_split + self.pending_post_mem_delta,
                                                        self.pending_post_mem_value))
                    m.d.comb += next_pc_after_load_split.eq(
                        Mux(self.pending_post_mem_write & (self.pending_post_mem_reg == 15),
                            post_mem_value_split,
                            Mux(self.pending_rd == 15, load_result_split, self.pending_next_pc))
                    )
                    write_reg(self.pending_rd, load_result_split)
                    with m.If(self.pending_post_mem_write):
                        write_reg(self.pending_post_mem_reg, post_mem_value_split)
                    with m.If(self.pending_set_reservation):
                        m.d.sync += [
                            self.ll_reservation_addr.eq(self.pending_reservation_addr),
                            self.ll_reservation_valid.eq(1),
                        ]
                    with m.If(self.pending_chain_store):
                        m.d.sync += [
                            self.pending_addr.eq(self.pending_chain_store_addr),
                            self.pending_virtual_addr.eq(self.pending_chain_store_addr),
                            self.pending_width_bytes.eq(8),
                            self.pending_store_value.eq(Mux(self.pending_chain_store_use_load_result, load_result_split, self.pending_chain_store_value)),
                            self.pending_mem_write.eq(1),
                            self.pending_set_reservation.eq(0),
                            self.pending_post_mem_write.eq(0),
                            self.pending_post_mem_use_load_result.eq(0),
                            self.pending_post_mem_delta.eq(0),
                            self.pending_chain_store.eq(0),
                            self.pending_chain_store_use_load_result.eq(0),
                            self.pending_chain_store_value.eq(0),
                            self.state.eq(CoreState.MEM_TRANSLATE),
                        ]
                    with m.Else():
                        m.d.comb += self.commit_valid.eq(1)
                        m.d.sync += [
                            self.register_file[15].eq(next_pc_after_load_split),
                            self.state.eq(CoreState.FETCH_TRANSLATE),
                        ]

            with m.Case(CoreState.MEM_STORE):
                with m.If(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    with m.If(split_needed):
                        m.d.sync += [
                            split_first_cycle.eq(1),
                            self.state.eq(CoreState.MEM_STORE_SPLIT),
                        ]
                    with m.Else():
                        with m.If(store_overlaps_reservation):
                            m.d.sync += self.ll_reservation_valid.eq(0)
                        with m.If(self.pending_post_mem_write):
                            write_reg(self.pending_post_mem_reg, self.pending_post_mem_value)
                        m.d.comb += self.commit_valid.eq(1)
                        m.d.sync += [
                            self.register_file[15].eq(Mux(self.pending_post_mem_write & (self.pending_post_mem_reg == 15), self.pending_post_mem_value, self.pending_next_pc)),
                            self.state.eq(CoreState.FETCH_TRANSLATE),
                        ]

            with m.Case(CoreState.MEM_STORE_SPLIT):
                with m.If(split_first_cycle):
                    m.d.sync += split_first_cycle.eq(0)
                with m.Elif(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    with m.If(store_overlaps_reservation):
                        m.d.sync += self.ll_reservation_valid.eq(0)
                    with m.If(self.pending_post_mem_write):
                        write_reg(self.pending_post_mem_reg, self.pending_post_mem_value)
                    m.d.comb += self.commit_valid.eq(1)
                    m.d.sync += [
                        self.register_file[15].eq(Mux(self.pending_post_mem_write & (self.pending_post_mem_reg == 15), self.pending_post_mem_value, self.pending_next_pc)),
                        self.state.eq(CoreState.FETCH_TRANSLATE),
                    ]

            with m.Case(CoreState.INTERRUPT_VECTOR_TRANSLATE):
                with m.If(paging_enabled & ~Const(int(self.config.enable_mmu), 1)):
                    enter_lockup()
                with m.Elif(~paging_enabled):
                    m.d.sync += [
                        self.interrupt_vector_phys.eq(interrupt_vector_table_addr),
                        self.state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                    ]
                with m.Elif(~_is_canonical39(interrupt_vector_table_addr)):
                    enter_lockup()
                with m.Elif((self.special_regs.page_table_root_physical & 0xFFF) != 0):
                    enter_lockup()
                with m.Elif(self.tlb is not None):
                    with m.If(tlb_hit_ok):
                        m.d.sync += [
                            self.interrupt_vector_phys.eq(self.tlb.lookup_paddr),
                            self.state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                        ]
                    with m.Else():
                        m.d.sync += [
                            self.walk_virtual_addr.eq(interrupt_vector_table_addr),
                            self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                            self.walk_level.eq(2),
                            self.walk_access.eq(ACCESS_READ),
                            self.walk_resume_state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                            self.state.eq(CoreState.WALK),
                        ]
                with m.Else():
                    m.d.sync += [
                        self.walk_virtual_addr.eq(interrupt_vector_table_addr),
                        self.walk_table_addr.eq(self.special_regs.page_table_root_physical),
                        self.walk_level.eq(2),
                        self.walk_access.eq(ACCESS_READ),
                        self.walk_resume_state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                        self.state.eq(CoreState.WALK),
                    ]

            with m.Case(CoreState.INTERRUPT_VECTOR_LOAD):
                with m.If(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    with m.If(self.d_bus.dat_r == 0):
                        enter_lockup()
                    with m.Else():
                        m.d.comb += [
                            core_interrupt_epc_write.eq(1),
                            core_interrupt_epc_data.eq(self.interrupt_entry_epc),
                            core_interrupt_eflags_write.eq(1),
                            core_interrupt_eflags_data.eq(self.flags),
                        ]
                        m.d.sync += [
                            self.register_file[15].eq(self.d_bus.dat_r),
                            self.state.eq(CoreState.FETCH_TRANSLATE),
                        ]

            with m.Case(CoreState.WALK):
                with m.If(self.d_bus.err):
                    enter_lockup()
                with m.Elif(self.d_bus.ack):
                    m.d.sync += [
                        self.walk_pte_latched.eq(self.d_bus.dat_r),
                        self.state.eq(CoreState.WALK_PROCESS),
                    ]

            with m.Case(CoreState.WALK_PROCESS):
                with m.If((walk_pte & PTE_V) == 0):
                    with m.If(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                        enter_lockup()
                    with m.Else():
                        raise_sync_trap(TrapVector.PAGE_FAULT_NOT_PRESENT, self.pending_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=_encode_aux(AUX_SUBTYPE_NO_VALID_PTE, self.walk_level))
                with m.Elif((self.walk_level > 0) & walk_is_leaf):
                    with m.If(~walk_permission_ok | ~walk_user_ok):
                        with m.If(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_PERMISSION, self.pending_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=_encode_aux(AUX_SUBTYPE_PERMISSION, self.walk_level))
                    with m.Else():
                        if self.tlb is not None:
                            m.d.comb += self.tlb.fill_valid.eq(1)
                        with m.If(self.walk_resume_state == CoreState.FETCH):
                            m.d.sync += [
                                self.fetch_phys_addr.eq(walk_result_phys),
                                self.state.eq(CoreState.FETCH),
                            ]
                        with m.Elif(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                            m.d.sync += [
                                self.interrupt_vector_phys.eq(walk_result_phys),
                                self.state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                            ]
                        with m.Else():
                            m.d.sync += [
                                self.pending_addr.eq(walk_result_phys),
                                self.state.eq(self.walk_resume_state),
                            ]
                with m.Elif(walk_reserved):
                    with m.If(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                        enter_lockup()
                    with m.Else():
                        raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.pending_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=_encode_aux(AUX_SUBTYPE_RESERVED_BIT, self.walk_level))
                with m.Elif(self.walk_level == 0):
                    with m.If(~walk_is_leaf):
                        with m.If(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_RESERVED, self.pending_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=_encode_aux(AUX_SUBTYPE_INVALID_NONLEAF, Const(0, 64)))
                    with m.Elif(~walk_permission_ok | ~walk_user_ok):
                        with m.If(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                            enter_lockup()
                        with m.Else():
                            raise_sync_trap(TrapVector.PAGE_FAULT_PERMISSION, self.pending_fault_pc, fault_addr=self.walk_virtual_addr, access=self.walk_access, aux=_encode_aux(AUX_SUBTYPE_PERMISSION, Const(0, 64)))
                    with m.Else():
                        if self.tlb is not None:
                            m.d.comb += self.tlb.fill_valid.eq(1)
                        with m.If(self.walk_resume_state == CoreState.FETCH):
                            m.d.sync += [
                                self.fetch_phys_addr.eq(walk_result_phys),
                                self.state.eq(CoreState.FETCH),
                            ]
                        with m.Elif(self.walk_resume_state == CoreState.INTERRUPT_VECTOR_LOAD):
                            m.d.sync += [
                                self.interrupt_vector_phys.eq(walk_result_phys),
                                self.state.eq(CoreState.INTERRUPT_VECTOR_LOAD),
                            ]
                        with m.Else():
                            m.d.sync += [
                                self.pending_addr.eq(walk_result_phys),
                                self.state.eq(self.walk_resume_state),
                            ]
                with m.Else():
                    m.d.sync += [
                        self.walk_table_addr.eq(walk_table_next),
                        self.walk_level.eq(self.walk_level - 1),
                        self.state.eq(CoreState.WALK),
                    ]

            with m.Case(CoreState.HALTED):
                m.d.sync += self.halted.eq(self.halted | ~self.locked_up)

        return m
