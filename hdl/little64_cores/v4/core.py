"""V4 in-order pipelined Little64 core.

Architecture
------------
Five pipeline stages flowing through three inter-stage latches:

  Frontend → [FD latch] → Decode → [DE latch] → Execute → [XM latch] → Memory
                                                         ↘               ↓
                                                      (ALU) → [MR latch] → Retire

Pipeline control
~~~~~~~~~~~~~~~~
Stage advancement is driven purely by per-stage *valid* bits and event
signals.  There is no state-machine enum: the core has no equivalent of
V3PipelineState.  Exceptional conditions (page-table walks, trap entry,
vector load) are handled in small, focused sync sections each guarded by
their own condition.  The normal pipeline section runs when no exceptional
activity is pending.

Branch prediction
~~~~~~~~~~~~~~~~~
The V4 decode stage includes a branch predictor (default: static
backward-taken) that stores a *predicted_next_pc* in the DE latch.
Execute compares its actual computed next_pc against that prediction.
A mismatch triggers a one-cycle flush of the FD latch and a fetch
redirect, replacing V3's unconditional two-cycle taken-branch penalty
with (usually) a one-cycle penalty for correctly-predicted backward
branches.
"""
from __future__ import annotations

from amaranth import Array, Cat, Const, Elaboratable, Module, Mux, Signal

from ..config import Little64CoreConfig
from ..isa import (
    CPU_CONTROL_CUR_INT_MASK,
    CPU_CONTROL_CUR_INT_SHIFT,
    CPU_CONTROL_IN_INTERRUPT,
    CPU_CONTROL_INT_ENABLE,
    CPU_CONTROL_PAGING_ENABLE,
    CPU_CONTROL_USER_MODE,
    TrapVector,
)
from ..mmu import (
    ACCESS_EXECUTE,
    ACCESS_READ,
    ACCESS_WRITE,
    AUX_SUBTYPE_CANONICAL,
    AUX_SUBTYPE_INVALID_NONLEAF,
    AUX_SUBTYPE_NONE,
    AUX_SUBTYPE_NO_VALID_PTE,
    AUX_SUBTYPE_PERMISSION,
    AUX_SUBTYPE_RESERVED_BIT,
    PTE_R,
    PTE_RESERVED_MASK,
    PTE_U,
    PTE_V,
    PTE_W,
    PTE_X,
)
from ..isa import SpecialRegister
from ..v3.cache import Little64V3LineCache
from ..v3.execute_stage import Little64V3ExecuteStage
from .frontend import Little64V4FetchFrontend
from ..v3.helpers import encode_aux, is_canonical39
from .lsu import Little64V4LSU
from ..v3.memory_stage import Little64V3MemoryStage
from ..v3.retire_stage import Little64V3RetireStage
from ..v3.special_registers import Little64V3SpecialRegisterFile
from ..v3.tlb import Little64V3TLB
from .bundles import V4DecodeExecuteReg, V4FaultBundle, V4FetchDecodeReg, V4MemoryReg, V4RetireReg
from .decode_stage import Little64V4DecodeStage
from .predictor import Little64V4StaticBackwardTakenPredictor


class Little64V4Core(Elaboratable):
    """V4 in-order pipelined Little64 core.

    Provides the same architectural interface as V3 (same bus signals,
    register file, commit_valid, halted, locked_up, irq_lines) while
    replacing V3's single-slot serialised pipeline with a proper
    multi-stage pipeline driven by valid/stall signals.

    No state-machine enum.  Pipeline behaviour is determined entirely by
    per-stage valid bits and event signals.
    """

    def __init__(self, config: Little64CoreConfig | None = None) -> None:
        self.config = config or Little64CoreConfig(core_variant='v4')
        if self.config.core_variant != 'v4':
            raise ValueError('Little64V4Core requires Little64CoreConfig(core_variant="v4")')

        self.frontend = Little64V4FetchFrontend(
            data_width=self.config.instruction_bus_width,
            address_width=self.config.address_width,
            bus_timeout_cycles=self.config.bus_timeout_cycles,
        )
        self.lsu = Little64V4LSU(
            data_width=self.config.data_bus_width,
            address_width=self.config.address_width,
            bus_timeout_cycles=self.config.bus_timeout_cycles,
        )
        self.dcache = None
        if self.config.cache_topology != 'none':
            self.dcache = Little64V3LineCache(
                entries=4,
                data_width=self.config.data_bus_width,
                address_width=self.config.address_width,
            )
        self.special_regs = Little64V3SpecialRegisterFile(self.config)
        self.tlb = Little64V3TLB(entries=self.config.tlb_entries) if self.config.enable_tlb else None

        self.i_bus = self.frontend.i_bus
        self.d_bus = self.lsu.bus

        self.frontend_bus_watchdog_timeout = self.frontend.bus_watchdog_timeout
        self.lsu_bus_watchdog_timeout = self.lsu.bus_watchdog_timeout

        self.irq_lines = Signal(self.config.irq_input_count)
        self.halted = Signal()
        self.locked_up = Signal()
        # Exposed pipeline PCs for observability (mirrors V3 interface)
        self.fetch_pc = Signal(64, init=self.config.reset_vector)
        self.fetch_phys_addr = Signal(64, init=self.config.reset_vector)
        self.commit_valid = Signal()
        self.commit_pc = Signal(64)
        self.boot_r1 = Signal(64)
        self.boot_r13 = Signal(64)
        self.translate_virtual_addr = Signal(64, init=self.config.reset_vector)
        self.translate_access = Signal(2, init=ACCESS_EXECUTE)

        # Pipeline latches as instance attributes so they are accessible from tests.
        self.fd_reg = V4FetchDecodeReg()
        self.de_reg = V4DecodeExecuteReg()
        self.xm_reg = V4MemoryReg()

        # Observability aliases: point directly at latch fields (no comb drivers).
        self.current_instruction = self.fd_reg.instruction
        self.decode_pc = self.fd_reg.pc
        self.decode_post_increment_pc = self.fd_reg.post_increment_pc
        self.execute_instruction = self.de_reg.instruction
        self.execute_pc = self.de_reg.pc
        self.execute_post_increment_pc = self.de_reg.post_increment_pc
        self.execute_operand_a = self.de_reg.operand_a
        self.execute_operand_b = self.de_reg.operand_b
        self.execute_flags = self.de_reg.flags

        self.register_file = [
            Signal(64, name=f'r{i}', init=self.config.reset_vector if i == 15 else 0)
            for i in range(16)
        ]
        self.regs = Array(self.register_file)
        self.flags = Signal(3)

    # ------------------------------------------------------------------
    # elaborate
    # ------------------------------------------------------------------

    def elaborate(self, platform):  # noqa: C901  (complexity is inherent to a full CPU core)
        m = Module()

        # ---- Submodules ----
        m.submodules.frontend = self.frontend
        m.submodules.lsu = self.lsu
        m.submodules.special_regs = self.special_regs
        if self.dcache is not None:
            m.submodules.dcache = self.dcache
        if self.tlb is not None:
            m.submodules.tlb = self.tlb

        predictor = Little64V4StaticBackwardTakenPredictor()
        decode_stage = Little64V4DecodeStage(self.regs, self.flags, predictor=predictor)
        execute_stage = Little64V3ExecuteStage()
        memory_stage = Little64V3MemoryStage()
        retire_stage = Little64V3RetireStage()
        m.submodules.decode_stage = decode_stage
        m.submodules.execute_stage = execute_stage
        m.submodules.memory_stage = memory_stage
        m.submodules.retire_stage = retire_stage

        # ---- Pipeline latches (created in __init__ as instance attrs) ----
        fd_reg = self.fd_reg
        de_reg = self.de_reg
        xm_reg = self.xm_reg
        mr = V4RetireReg()
        retire = V4RetireReg()

        # ---- Internal state (replaces V3PipelineState enum + state signal) ----
        reset_pending = Signal(init=1)     # high on first cycle; no state machine needed

        next_fetch_pc = Signal(64)
        fetch_error = Signal()
        paging_without_mmu = Signal()
        pending_execute_load_valid = Signal()
        pending_memory_load_valid = Signal()
        execute_mispredict = Signal()      # V3 execute_redirect: actual_pc != predicted_pc
        execute_flush_younger = Signal()
        memory_error = Signal()
        memory_to_retire = Signal()
        memory_redirect = Signal()
        memory_chain_continue = Signal()
        execute_to_memory = Signal()
        execute_to_storebuf = Signal()
        execute_to_storebuf_load = Signal()
        execute_to_retire = Signal()
        execute_slot_available = Signal()
        decode_advance = Signal()
        predict_redirect_active = Signal()
        fetch_accept = Signal()
        mr_valid = Signal()
        mr_next_pc = Signal(64)
        mr_commit_next_pc = Signal(64)
        mr_reg_write = Signal()
        mr_reg_index = Signal(4)
        mr_reg_value = Signal(64)
        mr_aux_reg_write = Signal()
        mr_aux_reg_index = Signal(4)
        mr_aux_reg_value = Signal(64)
        mr_commit_pc = Signal(64)
        mr_flags_write = Signal()
        mr_flags_value = Signal(3)
        vector_load_active = Signal()
        vector_load_started = Signal()
        vector_virtual_addr = Signal(64)
        vector_load_addr = Signal(64)
        vector_phys_valid = Signal()
        vector_load_epc = Signal(64)
        vector_load_flags = Signal(3)
        vector_translate_ready = Signal()
        vector_translate_complete = Signal()
        vector_translate_phys = Signal(64)
        vector_translate_lockup = Signal()
        vector_request_valid = Signal()
        vector_request_start = Signal()
        vector_response_valid = Signal()
        vector_response_error = Signal()
        vector_handler_pc = Signal(64)
        current_interrupt_vector = Signal(7)
        trap_preempt_lockup = Signal()
        pending_fault = V4FaultBundle()
        trap_request = pending_fault.pending
        trap_cause = pending_fault.cause
        trap_pc = pending_fault.pc
        trap_fault_addr = pending_fault.fault_addr
        trap_access = pending_fault.access
        trap_aux = pending_fault.aux
        trap_request_next = Signal()
        trap_cause_next = Signal(64)
        trap_pc_next = Signal(64)
        trap_fault_addr_next = Signal(64)
        trap_access_next = Signal(64)
        trap_aux_next = Signal(64)
        trap_start = Signal()
        irq_line_pending_mask = Signal(64)
        pending_irq_high = Signal(64)
        pending_irq_available = Signal()
        pending_irq_vector = Signal(64)
        can_preempt_pending_irq = Signal()
        irq_start = Signal()
        entry_start = Signal()
        entry_vector = Signal(64)
        entry_epc = Signal(64)
        trap_cpu_control_value = Signal(64)
        execute_special_write_commit = Signal()
        paging_enabled = Signal()
        fetch_phys_valid = Signal()
        fetch_translate_ready = Signal()
        fetch_translate_complete = Signal()
        fetch_translate_phys = Signal(64)
        fetch_fault = Signal()
        fetch_fault_cause = Signal(64)
        fetch_fault_addr = Signal(64)
        fetch_fault_access = Signal(64)
        fetch_fault_pc = Signal(64)
        fetch_fault_aux = Signal(64)
        memory_translate_ready = Signal()
        memory_translate_complete = Signal()
        memory_translate_phys = Signal(64)
        memory_fault = Signal()
        memory_fault_cause = Signal(64)
        memory_fault_addr = Signal(64)
        memory_fault_access = Signal(64)
        memory_fault_pc = Signal(64)
        memory_fault_aux = Signal(64)
        walk_active = Signal()
        walk_processing = Signal()
        walk_started = Signal()
        walk_virtual_addr = Signal(64)
        walk_table_addr = Signal(64)
        walk_level = Signal(2)
        walk_access = Signal(2)
        walk_resume_kind = Signal(2)
        walk_pte_latched = Signal(64)
        walk_request_valid = Signal()
        walk_request_start = Signal()
        walk_response_valid = Signal()
        walk_response_error = Signal()
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
        walk_fault = Signal()
        walk_fault_cause = Signal(64)
        walk_fault_addr = Signal(64)
        walk_fault_access = Signal(64)
        walk_fault_pc = Signal(64)
        walk_fault_aux = Signal(64)
        tlb_lookup_hit = Signal()
        tlb_lookup_perm_read = Signal()
        tlb_lookup_perm_write = Signal()
        tlb_lookup_paddr = Signal(64)
        tlb_lookup_perm_execute = Signal()
        tlb_lookup_perm_user = Signal()
        tlb_perm_ok = Signal()
        tlb_hit_ok = Signal()
        walk_leaf_success = Signal()
        walk_fault_trap = Signal()
        walk_fault_lockup = Signal()
        ll_reservation_valid = Signal()
        ll_reservation_addr = Signal(64)
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
        line_match = Signal()
        unified_line_update_value = Signal(64)
        frontend_store_invalidate = Signal()
        frontend_line_update_valid = Signal()
        cached_memory_response = Signal()
        cached_memory_post_value = Signal(64)
        cached_memory_next_pc = Signal(64)
        cached_memory_reg_write = Signal()
        cached_memory_reg_index = Signal(4)
        cached_memory_reg_value = Signal(64)
        cached_memory_aux_reg_write = Signal()
        cached_memory_aux_reg_index = Signal(4)
        cached_memory_aux_reg_value = Signal(64)
        memory_result_reg_write = Signal()
        memory_result_reg_index = Signal(4)
        memory_result_reg_value = Signal(64)
        memory_result_aux_reg_write = Signal()
        memory_result_aux_reg_index = Signal(4)
        memory_result_aux_reg_value = Signal(64)
        memory_result_next_pc = Signal(64)
        chain_continue_store_value = Signal(64)
        sb0_valid = Signal()
        sb0_started = Signal()
        sb0_addr = Signal(64)
        sb0_width_bytes = Signal(4)
        sb0_store_value = Signal(64)
        sb1_valid = Signal()
        sb1_started = Signal()
        sb1_addr = Signal(64)
        sb1_width_bytes = Signal(4)
        sb1_store_value = Signal(64)
        storebuf_any_valid = Signal()
        storebuf_drain_sb1 = Signal()
        storebuf_active_started = Signal()
        storebuf_active_addr = Signal(64)
        storebuf_active_width_bytes = Signal(4)
        storebuf_active_store_value = Signal(64)
        storebuf_request_valid = Signal()
        storebuf_request_start = Signal()
        storebuf_response_valid = Signal()
        storebuf_response_error = Signal()
        storebuf_pop_sb1 = Signal()
        storebuf_load_match = Signal()
        storebuf_load_from_sb0 = Signal()
        storebuf_load_from_sb1 = Signal()
        storebuf_load_source_value = Signal(64)
        storebuf_load_value = Signal(64)

        # Expose pipeline register aliases for observability.
        # (Removed: these are now direct Signal aliases in __init__, no comb needed.)

        WALK_RESUME_FETCH = 0
        WALK_RESUME_MEMORY = 1
        WALK_RESUME_VECTOR = 2

        # ---- Helper: clear pipeline latches ----
        def clear_pipeline_sync():
            return [
                fd_reg.valid.eq(0),
                de_reg.valid.eq(0),
                xm_reg.valid.eq(0),
                xm_reg.request_started.eq(0),
                mr_valid.eq(0),
                retire.valid.eq(0),
            ]

        def clear_xm_sync():
            return [
                xm_reg.valid.eq(0),
                xm_reg.request_started.eq(0),
                xm_reg.virtual_addr.eq(0),
                xm_reg.addr.eq(0),
                xm_reg.phys_valid.eq(0),
                xm_reg.width_bytes.eq(0),
                xm_reg.write.eq(0),
                xm_reg.store_value.eq(0),
                xm_reg.reg_write.eq(0),
                xm_reg.reg_index.eq(0),
                xm_reg.next_pc.eq(0),
                xm_reg.commit_pc.eq(0),
                xm_reg.fault_pc.eq(0),
                xm_reg.post_reg_write.eq(0),
                xm_reg.post_reg_index.eq(0),
                xm_reg.post_reg_value.eq(0),
                xm_reg.post_reg_delta.eq(0),
                xm_reg.post_reg_use_load_result.eq(0),
                xm_reg.chain_store.eq(0),
                xm_reg.chain_store_addr.eq(0),
                xm_reg.chain_store_use_load_result.eq(0),
                xm_reg.chain_store_value.eq(0),
                xm_reg.flags_write.eq(0),
                xm_reg.flags_value.eq(self.flags),
                xm_reg.set_reservation.eq(0),
                xm_reg.reservation_addr.eq(0),
            ]

        def clear_retire_sync():
            return [
                retire.valid.eq(0),
                retire.reg_write.eq(0),
                retire.reg_index.eq(0),
                retire.reg_value.eq(0),
                retire.aux_reg_write.eq(0),
                retire.aux_reg_index.eq(0),
                retire.aux_reg_value.eq(0),
                retire.flags_write.eq(0),
                retire.flags_value.eq(self.flags),
                retire.cpu_control_write.eq(0),
                retire.cpu_control_value.eq(0),
                retire.next_pc.eq(self.regs[15]),
                retire.commit.eq(0),
                retire.commit_pc.eq(0),
                retire.halt.eq(0),
                retire.lockup.eq(0),
                retire.trap.eq(0),
                retire.trap_cause.eq(0),
            ]

        def redirect_fetch_sync(target_pc):
            return [
                self.fetch_pc.eq(target_pc),
                self.fetch_phys_addr.eq(Mux(paging_enabled, self.fetch_phys_addr, target_pc)),
                fetch_phys_valid.eq(~paging_enabled),
                self.translate_virtual_addr.eq(target_pc),
                self.translate_access.eq(ACCESS_EXECUTE),
            ]

        # ---- TLB ----
        if self.tlb is not None:
            m.d.comb += [
                self.tlb.lookup_vaddr.eq(self.translate_virtual_addr),
                self.tlb.flush_all.eq(self.special_regs.tlb_flush),
                self.tlb.fill_valid.eq(walk_leaf_success),
                self.tlb.fill_vpage.eq(walk_virtual_addr[self.tlb.page_offset_bits:]),
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

        # ---- D-cache ----
        if self.dcache is not None:
            m.d.comb += [
                self.dcache.lookup_addr.eq(xm_reg.addr),
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

        # ---- Decode stage wiring ----
        m.d.comb += [
            decode_stage.instruction.eq(fd_reg.instruction),
            decode_stage.pc.eq(fd_reg.pc),
            decode_stage.post_increment_pc.eq(fd_reg.post_increment_pc),
            # Forwarding from execute slot (de_reg)
            decode_stage.execute_valid.eq(de_reg.valid & ~execute_stage.outputs.memory_start),
            decode_stage.execute_reg_write.eq(execute_stage.outputs.reg_write),
            decode_stage.execute_reg_index.eq(execute_stage.outputs.reg_index),
            decode_stage.execute_reg_value.eq(execute_stage.outputs.reg_value),
            decode_stage.execute_flags_write.eq(execute_stage.outputs.flags_write),
            decode_stage.execute_flags_value.eq(execute_stage.outputs.flags_value),
            # Forwarding from memory-result buffer
            decode_stage.memory_final_valid.eq(mr_valid),
            decode_stage.memory_final_reg_write.eq(mr_reg_write),
            decode_stage.memory_final_reg_index.eq(mr_reg_index),
            decode_stage.memory_final_reg_value.eq(mr_reg_value),
            decode_stage.memory_final_aux_reg_write.eq(mr_aux_reg_write),
            decode_stage.memory_final_aux_reg_index.eq(mr_aux_reg_index),
            decode_stage.memory_final_aux_reg_value.eq(mr_aux_reg_value),
            decode_stage.memory_final_flags_write.eq(mr_flags_write),
            decode_stage.memory_final_flags_value.eq(mr_flags_value),
            # Forwarding from retire register
            decode_stage.retire_valid.eq(retire.valid),
            decode_stage.retire_reg_write.eq(retire.reg_write),
            decode_stage.retire_reg_index.eq(retire.reg_index),
            decode_stage.retire_reg_value.eq(retire.reg_value),
            decode_stage.retire_aux_reg_write.eq(retire.aux_reg_write),
            decode_stage.retire_aux_reg_index.eq(retire.aux_reg_index),
            decode_stage.retire_aux_reg_value.eq(retire.aux_reg_value),
            decode_stage.retire_flags_write.eq(retire.flags_write),
            decode_stage.retire_flags_value.eq(retire.flags_value),
            # Load-use hazard inputs
            decode_stage.pending_load_execute_valid.eq(pending_execute_load_valid),
            decode_stage.pending_load_execute_index.eq(execute_stage.outputs.memory_reg_index),
            decode_stage.pending_load_memory_valid.eq(pending_memory_load_valid),
            decode_stage.pending_load_memory_index.eq(xm_reg.reg_index),
            decode_stage.pending_write_execute_valid.eq(
                de_reg.valid &
                execute_stage.outputs.memory_start &
                execute_stage.outputs.memory_post_reg_write
            ),
            decode_stage.pending_write_execute_index.eq(execute_stage.outputs.memory_post_reg_index),
            decode_stage.pending_write_memory_valid.eq(xm_reg.valid & xm_reg.post_reg_write),
            decode_stage.pending_write_memory_index.eq(xm_reg.post_reg_index),
        ]

        # ---- Execute stage wiring ----
        m.d.comb += [
            execute_stage.valid.eq(de_reg.valid),
            execute_stage.instruction.eq(de_reg.instruction),
            execute_stage.pc.eq(de_reg.pc),
            execute_stage.pre_post_increment_pc.eq(de_reg.post_increment_pc),
            execute_stage.operand_a.eq(de_reg.operand_a),
            execute_stage.operand_b.eq(de_reg.operand_b),
            execute_stage.flags.eq(de_reg.flags),
            execute_stage.cpu_control.eq(self.special_regs.cpu_control),
            execute_stage.interrupt_epc.eq(self.special_regs.interrupt_epc),
            execute_stage.interrupt_eflags.eq(self.special_regs.interrupt_eflags),
            execute_stage.interrupt_cpu_control.eq(self.special_regs.interrupt_cpu_control),
            execute_stage.ll_reservation_valid.eq(ll_reservation_valid),
            execute_stage.ll_reservation_addr.eq(ll_reservation_addr),
            execute_stage.special_read_data.eq(self.special_regs.read_data),
            execute_stage.special_read_access_fault.eq(self.special_regs.read_access_fault),
            execute_stage.special_write_access_fault.eq(self.special_regs.write_access_fault),
        ]

        # ---- Memory stage wiring ----
        m.d.comb += [
            memory_stage.valid.eq(xm_reg.valid & xm_reg.phys_valid & ~cached_memory_response),
            memory_stage.request_started.eq(xm_reg.request_started),
            memory_stage.addr.eq(xm_reg.addr),
            memory_stage.width_bytes.eq(xm_reg.width_bytes),
            memory_stage.write.eq(xm_reg.write),
            memory_stage.store_value.eq(xm_reg.store_value),
            memory_stage.reg_write.eq(xm_reg.reg_write),
            memory_stage.reg_index.eq(xm_reg.reg_index),
            memory_stage.next_pc.eq(xm_reg.next_pc),
            memory_stage.commit_pc.eq(xm_reg.commit_pc),
            memory_stage.flags_write.eq(xm_reg.flags_write),
            memory_stage.flags_value.eq(xm_reg.flags_value),
            memory_stage.set_reservation.eq(xm_reg.set_reservation),
            memory_stage.reservation_addr.eq(xm_reg.reservation_addr),
            memory_stage.post_reg_write.eq(xm_reg.post_reg_write),
            memory_stage.post_reg_index.eq(xm_reg.post_reg_index),
            memory_stage.post_reg_value.eq(xm_reg.post_reg_value),
            memory_stage.post_reg_delta.eq(xm_reg.post_reg_delta),
            memory_stage.post_reg_use_load_result.eq(xm_reg.post_reg_use_load_result),
            memory_stage.chain_store.eq(xm_reg.chain_store),
            memory_stage.chain_store_addr.eq(xm_reg.chain_store_addr),
            memory_stage.chain_store_use_load_result.eq(xm_reg.chain_store_use_load_result),
            memory_stage.chain_store_value.eq(xm_reg.chain_store_value),
            memory_stage.lsu_request_ready.eq(self.lsu.request_ready & ~vector_load_active & ~walk_active & ~storebuf_any_valid),
            memory_stage.lsu_response_valid.eq(self.lsu.response_valid & ~vector_load_active & ~walk_active & ~storebuf_any_valid),
            memory_stage.lsu_response_error.eq(self.lsu.response_error),
            memory_stage.lsu_response_load_value.eq(self.lsu.response_load_value),
        ]

        # ---- Retire stage wiring ----
        m.d.comb += [
            retire_stage.valid.eq(retire.valid),
            retire_stage.reg_write.eq(retire.reg_write),
            retire_stage.reg_index.eq(retire.reg_index),
            retire_stage.reg_value.eq(retire.reg_value),
            retire_stage.aux_reg_write.eq(retire.aux_reg_write),
            retire_stage.aux_reg_index.eq(retire.aux_reg_index),
            retire_stage.aux_reg_value.eq(retire.aux_reg_value),
            retire_stage.flags_write.eq(retire.flags_write),
            retire_stage.flags_value.eq(retire.flags_value),
            retire_stage.cpu_control_write.eq(retire.cpu_control_write),
            retire_stage.cpu_control_value.eq(retire.cpu_control_value),
            retire_stage.next_pc.eq(retire.next_pc),
            retire_stage.commit.eq(retire.commit),
            retire_stage.commit_pc.eq(retire.commit_pc),
            retire_stage.halt.eq(retire.halt),
            retire_stage.lockup.eq(retire.lockup),
            retire_stage.trap.eq(retire.trap),
            retire_stage.trap_cause.eq(retire.trap_cause),
        ]

        # ====================================================================
        # Combinational control signals
        # ====================================================================

        m.d.comb += [
            paging_enabled.eq((self.special_regs.cpu_control & CPU_CONTROL_PAGING_ENABLE) != 0),
            irq_line_pending_mask.eq(Cat(Const(0, 1), self.irq_lines, Const(0, 63 - self.config.irq_input_count))),
            pending_irq_high.eq(self.special_regs.interrupt_states_high | irq_line_pending_mask),
            pending_irq_available.eq(0),
            pending_irq_vector.eq(0),
            self.frontend.pc.eq(self.fetch_phys_addr),
            self.frontend.invalidate.eq(
                execute_flush_younger |
                memory_redirect |
                trap_start |
                irq_start |
                ~fetch_phys_valid |
                (walk_active & (walk_resume_kind == WALK_RESUME_FETCH)) |
                frontend_store_invalidate
            ),
            self.frontend.update_line_valid.eq(frontend_line_update_valid),
            self.frontend.update_line_data.eq(unified_line_update_value),
            execute_special_write_commit.eq(execute_stage.special_write_stb & execute_to_retire),
            self.special_regs.user_mode.eq(self.special_regs.cpu_control[17]),
            self.special_regs.read_selector.eq(execute_stage.special_read_selector),
            self.special_regs.write_stb.eq(execute_special_write_commit),
            self.special_regs.write_selector.eq(execute_stage.special_write_selector),
            self.special_regs.write_data.eq(execute_stage.special_write_data),
            self.special_regs.interrupt_states_high_set.eq(Mux(
                (irq_line_pending_mask != 0) &
                ~(execute_special_write_commit & (execute_stage.special_write_selector == SpecialRegister.INTERRUPT_STATES_HIGH)),
                irq_line_pending_mask,
                0,
            )),
            next_fetch_pc.eq(self.fetch_pc + 2),
            pending_execute_load_valid.eq(
                de_reg.valid &
                execute_stage.outputs.memory_start &
                ~execute_stage.outputs.memory_write &
                execute_stage.outputs.memory_reg_write
            ),
            pending_memory_load_valid.eq(xm_reg.valid & ~xm_reg.write & xm_reg.reg_write),
            # execute_mispredict: actual computed PC differs from what the predictor told fetch to do
            execute_mispredict.eq(
                de_reg.valid &
                ~execute_stage.outputs.halt &
                ~execute_stage.outputs.lockup &
                ~execute_stage.outputs.trap &
                ~memory_redirect &
                (execute_stage.outputs.next_pc != de_reg.predicted_next_pc)
            ),
            execute_flush_younger.eq(
                de_reg.valid &
                (execute_mispredict | execute_stage.outputs.halt | execute_stage.outputs.trap | execute_stage.outputs.lockup)
            ),
            fetch_error.eq(self.frontend.fetch_error & ~execute_flush_younger),
            memory_error.eq(xm_reg.valid & ~cached_memory_response & memory_stage.complete & self.lsu.response_error),
            memory_to_retire.eq(
                xm_reg.valid &
                ((cached_memory_response & ~xm_reg.chain_store) | (memory_stage.final_response & ~self.lsu.response_error))
            ),
            memory_redirect.eq(mr_valid & (mr_next_pc != mr_commit_next_pc)),
            memory_chain_continue.eq(
                xm_reg.valid &
                ((cached_memory_response & xm_reg.chain_store) | (~cached_memory_response & memory_stage.chain_continue))
            ),
            storebuf_any_valid.eq(sb0_valid | sb1_valid),
            storebuf_drain_sb1.eq(~sb0_valid & sb1_valid),
            storebuf_active_started.eq(Mux(storebuf_drain_sb1, sb1_started, sb0_started)),
            storebuf_active_addr.eq(Mux(storebuf_drain_sb1, sb1_addr, sb0_addr)),
            storebuf_active_width_bytes.eq(Mux(storebuf_drain_sb1, sb1_width_bytes, sb0_width_bytes)),
            storebuf_active_store_value.eq(Mux(storebuf_drain_sb1, sb1_store_value, sb0_store_value)),
            storebuf_request_valid.eq(storebuf_any_valid & ~storebuf_active_started & ~walk_active & ~vector_load_active),
            storebuf_request_start.eq(storebuf_request_valid & self.lsu.request_ready),
            storebuf_response_valid.eq(storebuf_any_valid & storebuf_active_started & self.lsu.response_valid),
            storebuf_response_error.eq(storebuf_response_valid & self.lsu.response_error),
            storebuf_pop_sb1.eq(storebuf_response_valid & storebuf_drain_sb1),
            storebuf_load_from_sb1.eq(
                sb1_valid &
                (execute_stage.outputs.memory_addr[3:64] == sb1_addr[3:64]) &
                (execute_stage.outputs.memory_addr[0:3] == sb1_addr[0:3]) &
                (execute_stage.outputs.memory_width_bytes <= sb1_width_bytes)
            ),
            storebuf_load_from_sb0.eq(
                sb0_valid &
                (execute_stage.outputs.memory_addr[3:64] == sb0_addr[3:64]) &
                (execute_stage.outputs.memory_addr[0:3] == sb0_addr[0:3]) &
                (execute_stage.outputs.memory_width_bytes <= sb0_width_bytes)
            ),
            storebuf_load_match.eq(storebuf_load_from_sb1 | (~storebuf_load_from_sb1 & storebuf_load_from_sb0)),
            storebuf_load_source_value.eq(Mux(storebuf_load_from_sb1, sb1_store_value, sb0_store_value)),
            storebuf_load_value.eq(
                Mux(
                    execute_stage.outputs.memory_width_bytes == 1,
                    storebuf_load_source_value & 0xFF,
                    Mux(
                        execute_stage.outputs.memory_width_bytes == 2,
                        storebuf_load_source_value & 0xFFFF,
                        Mux(
                            execute_stage.outputs.memory_width_bytes == 4,
                            storebuf_load_source_value & 0xFFFFFFFF,
                            storebuf_load_source_value,
                        ),
                    ),
                )
            ),
            execute_to_storebuf.eq(
                de_reg.valid &
                execute_stage.outputs.memory_start &
                execute_stage.outputs.memory_write &
                ~execute_stage.outputs.memory_flags_write &
                ~execute_stage.outputs.memory_reg_write &
                ~execute_stage.outputs.memory_post_reg_write &
                ~execute_stage.outputs.memory_chain_store &
                ~execute_stage.outputs.memory_set_reservation &
                ~paging_enabled &
                ~walk_active &
                ~vector_load_active &
                ~sb1_valid &
                ~xm_reg.valid &
                ~mr_valid &
                ~memory_redirect
            ),
            execute_to_storebuf_load.eq(
                de_reg.valid &
                execute_stage.outputs.memory_start &
                ~execute_stage.outputs.memory_write &
                execute_stage.outputs.memory_reg_write &
                ~execute_stage.outputs.memory_post_reg_write &
                ~execute_stage.outputs.memory_chain_store &
                ~paging_enabled &
                storebuf_any_valid &
                storebuf_load_match &
                ~xm_reg.valid &
                ~mr_valid &
                ~memory_redirect
            ),
            execute_to_memory.eq(
                de_reg.valid &
                execute_stage.outputs.memory_start &
                ~execute_to_storebuf &
                ~execute_to_storebuf_load &
                ~storebuf_any_valid &
                ~xm_reg.valid &
                ~memory_redirect
            ),
            execute_to_retire.eq(de_reg.valid & ~execute_stage.outputs.memory_start & ~xm_reg.valid & ~mr_valid & ~memory_redirect),
            execute_slot_available.eq(~de_reg.valid | execute_to_memory | execute_to_storebuf | execute_to_storebuf_load | execute_to_retire),
            reservation_end.eq(ll_reservation_addr + 7),
            write_end.eq(xm_reg.virtual_addr + xm_reg.width_bytes - 1),
            store_overlaps_reservation.eq(
                ll_reservation_valid &
                memory_to_retire &
                xm_reg.write &
                (xm_reg.width_bytes != 0) &
                (xm_reg.virtual_addr <= reservation_end) &
                (ll_reservation_addr <= write_end)
            ),
            tlb_perm_ok.eq(
                Mux(
                    self.translate_access == ACCESS_EXECUTE,
                    tlb_lookup_perm_execute,
                    Mux(self.translate_access == ACCESS_WRITE, tlb_lookup_perm_write, tlb_lookup_perm_read),
                )
            ),
            tlb_hit_ok.eq(tlb_lookup_hit & tlb_perm_ok & ((~self.special_regs.cpu_control[17]) | tlb_lookup_perm_user)),
            memory_translate_ready.eq(xm_reg.valid & ~xm_reg.phys_valid & ~walk_active & ~vector_load_active & ~storebuf_any_valid & ~trap_request),
            memory_translate_complete.eq(
                memory_translate_ready &
                (~paging_enabled | (is_canonical39(xm_reg.virtual_addr) & ((self.special_regs.page_table_root_physical & 0xFFF) == 0) & tlb_hit_ok))
            ),
            memory_translate_phys.eq(Mux(paging_enabled, tlb_lookup_paddr, xm_reg.virtual_addr)),
            memory_fault.eq(
                memory_translate_ready &
                (paging_enabled & (~is_canonical39(xm_reg.virtual_addr) | ((self.special_regs.page_table_root_physical & 0xFFF) != 0)))
            ),
            memory_fault_cause.eq(Mux(~is_canonical39(xm_reg.virtual_addr), TrapVector.PAGE_FAULT_CANONICAL, TrapVector.PAGE_FAULT_RESERVED)),
            memory_fault_addr.eq(xm_reg.virtual_addr),
            memory_fault_access.eq(Mux(xm_reg.write, ACCESS_WRITE, ACCESS_READ)),
            memory_fault_pc.eq(xm_reg.fault_pc),
            memory_fault_aux.eq(
                Mux(
                    ~is_canonical39(xm_reg.virtual_addr),
                    encode_aux(AUX_SUBTYPE_CANONICAL, 2),
                    encode_aux(AUX_SUBTYPE_RESERVED_BIT, 2),
                )
            ),
            vector_translate_ready.eq(vector_load_active & ~vector_phys_valid & ~walk_active & ~storebuf_any_valid & ~trap_request),
            vector_translate_complete.eq(
                vector_translate_ready &
                (~paging_enabled | (is_canonical39(vector_virtual_addr) & ((self.special_regs.page_table_root_physical & 0xFFF) == 0) & tlb_hit_ok))
            ),
            vector_translate_phys.eq(Mux(paging_enabled, tlb_lookup_paddr, vector_virtual_addr)),
            vector_translate_lockup.eq(
                vector_translate_ready &
                (paging_enabled & (~is_canonical39(vector_virtual_addr) | ((self.special_regs.page_table_root_physical & 0xFFF) != 0)))
            ),
            walk_request_valid.eq(walk_active & ~walk_processing & ~walk_started),
            walk_request_start.eq(walk_request_valid & self.lsu.request_ready),
            walk_response_valid.eq(walk_active & ~walk_processing & self.lsu.response_valid),
            walk_response_error.eq(walk_response_valid & self.lsu.response_error),
            walk_index.eq(Mux(walk_level == 2, walk_virtual_addr[30:39], Mux(walk_level == 1, walk_virtual_addr[21:30], walk_virtual_addr[12:21]))),
            walk_pte_addr.eq(walk_table_addr + (walk_index << 3)),
            walk_pte.eq(walk_pte_latched),
            walk_is_leaf.eq((walk_pte & (PTE_R | PTE_W | PTE_X)) != 0),
            walk_permission_ok.eq(
                Mux(
                    walk_access == ACCESS_EXECUTE,
                    (walk_pte & PTE_X) != 0,
                    Mux(walk_access == ACCESS_WRITE, (walk_pte & PTE_W) != 0, (walk_pte & PTE_R) != 0),
                )
            ),
            walk_user_ok.eq((~self.special_regs.cpu_control[17]) | ((walk_pte & PTE_U) != 0)),
            walk_reserved.eq((walk_pte & PTE_RESERVED_MASK) != 0),
            walk_table_next.eq((walk_pte >> 10) << 12),
            walk_page_shift.eq(Mux(walk_level == 2, 30, Mux(walk_level == 1, 21, 12))),
            walk_page_mask.eq((Const(1, 64) << walk_page_shift) - 1),
            walk_page_base.eq((walk_pte >> 10) << 12),
            walk_result_phys.eq(walk_page_base + (walk_virtual_addr & walk_page_mask)),
            fetch_translate_ready.eq(
                ~fetch_phys_valid &
                ~walk_active &
                ~storebuf_any_valid &
                ~fd_reg.valid &
                ~de_reg.valid &
                ~xm_reg.valid &
                ~retire.valid &
                ~vector_load_active &
                ~trap_request
            ),
            fetch_translate_complete.eq(
                fetch_translate_ready &
                ~self.translate_virtual_addr[0] &
                (~paging_enabled | (is_canonical39(self.translate_virtual_addr) & ((self.special_regs.page_table_root_physical & 0xFFF) == 0) & tlb_hit_ok))
            ),
            fetch_translate_phys.eq(Mux(paging_enabled, tlb_lookup_paddr, self.translate_virtual_addr)),
            fetch_fault.eq(
                fetch_translate_ready &
                (self.translate_virtual_addr[0] |
                 (paging_enabled & ~is_canonical39(self.translate_virtual_addr)) |
                 (paging_enabled & ((self.special_regs.page_table_root_physical & 0xFFF) != 0)))
            ),
            fetch_fault_cause.eq(
                Mux(
                    self.translate_virtual_addr[0],
                    TrapVector.EXEC_ALIGN,
                    Mux(
                        ~is_canonical39(self.translate_virtual_addr),
                        TrapVector.PAGE_FAULT_CANONICAL,
                        TrapVector.PAGE_FAULT_RESERVED,
                    ),
                )
            ),
            fetch_fault_addr.eq(self.translate_virtual_addr),
            fetch_fault_access.eq(ACCESS_EXECUTE),
            fetch_fault_pc.eq(self.translate_virtual_addr),
            fetch_fault_aux.eq(
                Mux(
                    self.translate_virtual_addr[0],
                    encode_aux(AUX_SUBTYPE_NONE, 0),
                    Mux(
                        ~is_canonical39(self.translate_virtual_addr),
                        encode_aux(AUX_SUBTYPE_CANONICAL, 2),
                        encode_aux(AUX_SUBTYPE_RESERVED_BIT, 2),
                    ),
                )
            ),
            walk_fault.eq(
                walk_processing &
                (((walk_pte & PTE_V) == 0) |
                 walk_reserved |
                  ((walk_level > 0) & walk_is_leaf & ((~walk_permission_ok) | (~walk_user_ok))) |
                  ((walk_level == 0) & (~walk_is_leaf | (~walk_permission_ok) | (~walk_user_ok))))
            ),
            walk_fault_cause.eq(
                Mux(
                    (walk_pte & PTE_V) == 0,
                    TrapVector.PAGE_FAULT_NOT_PRESENT,
                    Mux(
                        walk_reserved | ((walk_level == 0) & ~walk_is_leaf),
                        TrapVector.PAGE_FAULT_RESERVED,
                        TrapVector.PAGE_FAULT_PERMISSION,
                    ),
                )
            ),
            walk_fault_addr.eq(walk_virtual_addr),
            walk_fault_access.eq(walk_access),
            walk_fault_pc.eq(Mux(walk_resume_kind == WALK_RESUME_MEMORY, xm_reg.fault_pc, walk_virtual_addr)),
            walk_fault_aux.eq(
                Mux(
                    (walk_pte & PTE_V) == 0,
                    encode_aux(AUX_SUBTYPE_NO_VALID_PTE, walk_level),
                    Mux(
                        walk_reserved,
                        encode_aux(AUX_SUBTYPE_RESERVED_BIT, walk_level),
                        Mux(
                            (walk_level == 0) & ~walk_is_leaf,
                            encode_aux(AUX_SUBTYPE_INVALID_NONLEAF, 0),
                            encode_aux(AUX_SUBTYPE_PERMISSION, walk_level),
                        ),
                    ),
                )
            ),
            walk_leaf_success.eq(
                walk_processing &
                ~walk_fault &
                (((walk_level > 0) & walk_is_leaf) | ((walk_level == 0) & walk_is_leaf & walk_permission_ok & walk_user_ok))
            ),
            walk_fault_trap.eq(walk_fault & (walk_resume_kind != WALK_RESUME_VECTOR)),
            walk_fault_lockup.eq(walk_fault & (walk_resume_kind == WALK_RESUME_VECTOR)),
            current_interrupt_vector.eq((self.special_regs.cpu_control & CPU_CONTROL_CUR_INT_MASK) >> CPU_CONTROL_CUR_INT_SHIFT),
            can_preempt_pending_irq.eq(
                (~self.special_regs.cpu_control[1]) |
                (current_interrupt_vector == 0) |
                (current_interrupt_vector > pending_irq_vector)
            ),
            trap_request_next.eq(retire_stage.trap_request | fetch_fault | memory_fault | walk_fault_trap),
            trap_cause_next.eq(Mux(retire_stage.trap_request, retire_stage.trap_cause_value, Mux(fetch_fault, fetch_fault_cause, Mux(memory_fault, memory_fault_cause, walk_fault_cause)))),
            trap_pc_next.eq(Mux(retire_stage.trap_request, retire_stage.trap_pc_value, Mux(fetch_fault, fetch_fault_pc, Mux(memory_fault, memory_fault_pc, walk_fault_pc)))),
            trap_fault_addr_next.eq(Mux(fetch_fault, fetch_fault_addr, Mux(memory_fault, memory_fault_addr, Mux(walk_fault_trap, walk_fault_addr, 0)))),
            trap_access_next.eq(Mux(fetch_fault, fetch_fault_access, Mux(memory_fault, memory_fault_access, Mux(walk_fault_trap, walk_fault_access, 0)))),
            trap_aux_next.eq(Mux(fetch_fault, fetch_fault_aux, Mux(memory_fault, memory_fault_aux, Mux(walk_fault_trap, walk_fault_aux, 0)))),
            trap_preempt_lockup.eq(
                trap_request &
                self.special_regs.cpu_control[1] &
                (current_interrupt_vector != 0) &
                (current_interrupt_vector < TrapVector.FIRST_HW_IRQ) &
                (current_interrupt_vector <= trap_cause)
            ),
            trap_start.eq(trap_request & ~trap_preempt_lockup & ~vector_load_active),
            irq_start.eq(
                ~trap_request &
                ~trap_request_next &
                ~vector_load_active &
                ~walk_active &
                ~storebuf_any_valid &
                ~fd_reg.valid &
                ~de_reg.valid &
                ~xm_reg.valid &
                ~mr_valid &
                ~retire.valid &
                pending_irq_available &
                self.special_regs.cpu_control[0] &
                can_preempt_pending_irq
            ),
            entry_start.eq(trap_start | irq_start),
            entry_vector.eq(Mux(trap_start, trap_cause, pending_irq_vector)),
            entry_epc.eq(Mux(trap_start, trap_pc, self.fetch_pc)),
            trap_cpu_control_value.eq(
                (self.special_regs.cpu_control & Const((1 << 64) - 1 - (CPU_CONTROL_INT_ENABLE | CPU_CONTROL_IN_INTERRUPT | CPU_CONTROL_CUR_INT_MASK | CPU_CONTROL_USER_MODE), 64)) |
                Const(CPU_CONTROL_IN_INTERRUPT, 64) |
                (entry_vector << CPU_CONTROL_CUR_INT_SHIFT)
            ),
            vector_request_valid.eq(vector_load_active & vector_phys_valid & ~vector_load_started),
            vector_request_start.eq(vector_request_valid & self.lsu.request_ready),
            vector_response_valid.eq(vector_load_active & vector_phys_valid & self.lsu.response_valid),
            vector_response_error.eq(vector_response_valid & self.lsu.response_error),
            vector_handler_pc.eq(self.lsu.response_load_value),
            # predict_redirect_active: predictor chose a non-sequential target AND decode is advancing
            predict_redirect_active.eq(
                fd_reg.valid &
                decode_stage.predict_redirect &
                decode_advance
            ),
            # fetch_accept: conditions identical to V3 plus suppress when predictor is redirecting
            fetch_accept.eq(
                fetch_phys_valid &
                self.frontend.instruction_valid &
                ~execute_flush_younger &
                ~memory_redirect &
                ~vector_load_active &
                ~trap_start &
                ~predict_redirect_active &
                (~fd_reg.valid | decode_advance)
            ),
            decode_advance.eq(
                fd_reg.valid &
                execute_slot_available &
                ~decode_stage.load_use_hazard &
                ~execute_flush_younger &
                ~memory_redirect
            ),
        ]

        m.d.comb += [
            mem_byte_offset.eq(xm_reg.addr[0:3]),
            mem_base_sel.eq(Mux(xm_reg.width_bytes == 1, 0x01,
                            Mux(xm_reg.width_bytes == 2, 0x03,
                            Mux(xm_reg.width_bytes == 4, 0x0F,
                            Mux(xm_reg.width_bytes == 8, 0xFF, 0x00))))),
            mem_single_line_access.eq((xm_reg.addr[0:3] + xm_reg.width_bytes) <= 8),
            dcache_cacheable_load.eq(Const(1 if self.dcache is not None else 0, 1) & xm_reg.valid & xm_reg.phys_valid & ~xm_reg.write & ~xm_reg.request_started & mem_single_line_access),
            dcache_cacheable_fill.eq(Const(1 if self.dcache is not None else 0, 1) & xm_reg.valid & xm_reg.phys_valid & ~xm_reg.write & (xm_reg.width_bytes == 8) & (xm_reg.addr[0:3] == 0)),
            dcache_store_update_valid.eq(0),
            dcache_store_update_addr.eq(xm_reg.addr),
            dcache_store_update_sel.eq(mem_shifted_sel),
            dcache_store_update_data.eq(mem_shifted_store_data),
            dcache_fill_valid.eq(0),
            dcache_fill_addr.eq(xm_reg.addr),
            dcache_fill_data.eq(self.lsu.response_load_value),
            dcache_flush_all.eq(0),
            dcache_invalidate_valid.eq(0),
            dcache_invalidate_addr.eq(xm_reg.addr),
            line_match.eq(self.frontend.line_valid & ((xm_reg.addr & Const(0xFFFFFFFFFFFFFFF8, 64)) == self.frontend.line_base)),
            frontend_store_invalidate.eq(0),
            frontend_line_update_valid.eq(0),
            cached_memory_response.eq(dcache_cacheable_load & dcache_lookup_hit),
            cached_memory_post_value.eq(Mux(xm_reg.post_reg_use_load_result, dcache_load_result + xm_reg.post_reg_delta, xm_reg.post_reg_value)),
            chain_continue_store_value.eq(
                Mux(
                    cached_memory_response,
                    Mux(xm_reg.chain_store_use_load_result, dcache_load_result, xm_reg.chain_store_value),
                    memory_stage.next_chain_store_value,
                )
            ),
            cached_memory_next_pc.eq(
                Mux(
                    xm_reg.post_reg_write & (xm_reg.post_reg_index == 15),
                    cached_memory_post_value,
                    Mux(xm_reg.reg_write & (xm_reg.reg_index == 15), dcache_load_result, xm_reg.next_pc),
                )
            ),
            memory_result_reg_write.eq(Mux(cached_memory_response, cached_memory_reg_write, memory_stage.result.reg_write)),
            memory_result_reg_index.eq(Mux(cached_memory_response, cached_memory_reg_index, memory_stage.result.reg_index)),
            memory_result_reg_value.eq(Mux(cached_memory_response, cached_memory_reg_value, memory_stage.result.reg_value)),
            memory_result_aux_reg_write.eq(Mux(cached_memory_response, cached_memory_aux_reg_write, memory_stage.result.aux_reg_write)),
            memory_result_aux_reg_index.eq(Mux(cached_memory_response, cached_memory_aux_reg_index, memory_stage.result.aux_reg_index)),
            memory_result_aux_reg_value.eq(Mux(cached_memory_response, cached_memory_aux_reg_value, memory_stage.result.aux_reg_value)),
            memory_result_next_pc.eq(Mux(cached_memory_response, cached_memory_next_pc, memory_stage.result.next_pc)),
        ]

        with m.Switch(mem_byte_offset):
            for offset in range(8):
                with m.Case(offset):
                    if offset == 0:
                        m.d.comb += [
                            mem_shifted_sel.eq(mem_base_sel),
                            mem_shifted_store_data.eq(xm_reg.store_value),
                            dcache_shifted_read.eq(dcache_lookup_data),
                        ]
                    else:
                        m.d.comb += [
                            mem_shifted_sel.eq(mem_base_sel << offset),
                            mem_shifted_store_data.eq(xm_reg.store_value << (offset * 8)),
                            dcache_shifted_read.eq(Cat(dcache_lookup_data[offset * 8:64], Const(0, offset * 8))),
                        ]

        m.d.comb += dcache_load_result.eq(Mux(xm_reg.width_bytes == 1, dcache_shifted_read & 0xFF,
                                          Mux(xm_reg.width_bytes == 2, dcache_shifted_read & 0xFFFF,
                                          Mux(xm_reg.width_bytes == 4, dcache_shifted_read & 0xFFFFFFFF,
                                          dcache_shifted_read))))

        m.d.comb += unified_line_update_value.eq(Cat(*[
            Mux(
                mem_shifted_sel[bi],
                mem_shifted_store_data[bi * 8:(bi + 1) * 8],
                self.frontend.line_data[bi * 8:(bi + 1) * 8],
            )
            for bi in range(8)
        ]))

        m.d.comb += [
            cached_memory_reg_write.eq(0),
            cached_memory_reg_index.eq(0),
            cached_memory_reg_value.eq(0),
            cached_memory_aux_reg_write.eq(0),
            cached_memory_aux_reg_index.eq(0),
            cached_memory_aux_reg_value.eq(0),
        ]

        with m.If(xm_reg.post_reg_write):
            with m.If(xm_reg.reg_write):
                with m.If(xm_reg.post_reg_index == xm_reg.reg_index):
                    m.d.comb += [
                        cached_memory_reg_write.eq(1),
                        cached_memory_reg_index.eq(xm_reg.reg_index),
                        cached_memory_reg_value.eq(cached_memory_post_value),
                    ]
                with m.Else():
                    m.d.comb += [
                        cached_memory_reg_write.eq(1),
                        cached_memory_reg_index.eq(xm_reg.reg_index),
                        cached_memory_reg_value.eq(dcache_load_result),
                        cached_memory_aux_reg_write.eq(1),
                        cached_memory_aux_reg_index.eq(xm_reg.post_reg_index),
                        cached_memory_aux_reg_value.eq(cached_memory_post_value),
                    ]
            with m.Else():
                m.d.comb += [
                    cached_memory_reg_write.eq(1),
                    cached_memory_reg_index.eq(xm_reg.post_reg_index),
                    cached_memory_reg_value.eq(cached_memory_post_value),
                ]
        with m.Else():
            m.d.comb += [
                cached_memory_reg_write.eq(xm_reg.reg_write),
                cached_memory_reg_index.eq(xm_reg.reg_index),
                cached_memory_reg_value.eq(dcache_load_result),
            ]

        for bit_index in range(self.config.irq_input_count, 0, -1):
            with m.If((pending_irq_high & self.special_regs.interrupt_mask_high)[bit_index]):
                m.d.comb += [
                    pending_irq_available.eq(1),
                    pending_irq_vector.eq(64 + bit_index),
                ]

        if self.config.enable_mmu:
            m.d.comb += paging_without_mmu.eq(0)
        else:
            m.d.comb += paging_without_mmu.eq((self.special_regs.cpu_control & CPU_CONTROL_PAGING_ENABLE) != 0)

        # ---- Special-register core writes ----
        m.d.comb += [
            self.special_regs.core_cpu_control_write.eq(retire_stage.write_cpu_control | entry_start),
            self.special_regs.core_cpu_control_data.eq(Mux(entry_start, trap_cpu_control_value, retire_stage.write_cpu_control_value)),
            self.special_regs.core_interrupt_cpu_control_write.eq(entry_start),
            self.special_regs.core_interrupt_cpu_control_data.eq(self.special_regs.cpu_control),
            self.special_regs.core_interrupt_epc_write.eq(vector_response_valid & ~vector_response_error & (vector_handler_pc != 0)),
            self.special_regs.core_interrupt_epc_data.eq(vector_load_epc),
            self.special_regs.core_interrupt_eflags_write.eq(vector_response_valid & ~vector_response_error & (vector_handler_pc != 0)),
            self.special_regs.core_interrupt_eflags_data.eq(vector_load_flags),
            self.special_regs.core_trap_write.eq(reset_pending | trap_request),
            self.special_regs.core_trap_cause_data.eq(
                Mux(
                    reset_pending,
                    0,
                    Mux(self.special_regs.trap_cause == 0, trap_cause, self.special_regs.trap_cause),
                )
            ),
            self.special_regs.core_trap_fault_addr_data.eq(trap_fault_addr),
            self.special_regs.core_trap_access_data.eq(trap_access),
            self.special_regs.core_trap_pc_data.eq(Mux(reset_pending, 0, trap_pc)),
            self.special_regs.core_trap_aux_data.eq(trap_aux),
            self.lsu.request_valid.eq(
                Mux(
                    walk_active,
                    walk_request_valid,
                    Mux(
                        vector_load_active & vector_phys_valid,
                        vector_request_valid,
                        Mux(storebuf_any_valid, storebuf_request_valid, memory_stage.lsu_request_valid),
                    ),
                )
            ),
            self.lsu.request_addr.eq(
                Mux(
                    walk_active,
                    walk_pte_addr,
                    Mux(
                        vector_load_active & vector_phys_valid,
                        vector_load_addr,
                        Mux(storebuf_any_valid, storebuf_active_addr, memory_stage.lsu_request_addr),
                    ),
                )
            ),
            self.lsu.request_width_bytes.eq(
                Mux(
                    walk_active | (vector_load_active & vector_phys_valid),
                    8,
                    Mux(storebuf_any_valid, storebuf_active_width_bytes, memory_stage.lsu_request_width_bytes),
                )
            ),
            self.lsu.request_write.eq(
                Mux(
                    walk_active | (vector_load_active & vector_phys_valid),
                    0,
                    Mux(storebuf_any_valid, 1, memory_stage.lsu_request_write),
                )
            ),
            self.lsu.request_store_value.eq(
                Mux(
                    walk_active | (vector_load_active & vector_phys_valid),
                    0,
                    Mux(storebuf_any_valid, storebuf_active_store_value, memory_stage.lsu_request_store_value),
                )
            ),
        ]

        # ====================================================================
        # Pending-fault registration
        # ====================================================================

        with m.If(entry_start):
            m.d.sync += pending_fault.pending.eq(0)
        with m.Else():
            m.d.sync += [
                pending_fault.pending.eq(trap_request_next),
                pending_fault.cause.eq(trap_cause_next),
                pending_fault.pc.eq(trap_pc_next),
                pending_fault.fault_addr.eq(trap_fault_addr_next),
                pending_fault.access.eq(trap_access_next),
                pending_fault.aux.eq(trap_aux_next),
            ]

        # ====================================================================
        # Synchronous pipeline logic
        # ====================================================================
        #
        # Structure:
        #
        #   reset_pending → load boot registers once.
        #
        #   All other cycles run every independent block concurrently.
        #   There is NO monolithic Elif chain.  Each concern has its own
        #   focused block:
        #
        #     1. Retire writeback  (unconditional architectural commits)
        #     2. Pipeline advancement  (FD/DE/XM/MR/Retire latches)
        #     3. Translate completions  (TLB-hit unblocking)
        #     4. Walk state machine  (multi-cycle Sv39 page-table walk)
        #     5. Vector load  (trap/IRQ handler-PC fetch)
        #     6. Terminal overrides  (trap entry, lockup, halt)
        #
        #   Because Amaranth uses last-write-wins semantics, placing the
        #   terminal overrides LAST guarantees they can squash pipeline
        #   state even when the pipeline advancement blocks also fire in
        #   the same cycle.  No Elif ordering is required for correctness.
        #

        with m.If(reset_pending):
            # ----------------------------------------------------------------
            # Boot: load reset values into architectural registers once.
            # No state enum; reset_pending is cleared on the first clock edge.
            # ----------------------------------------------------------------
            m.d.sync += [
                self.regs[1].eq(self.boot_r1),
                self.regs[13].eq(self.boot_r13),
                reset_pending.eq(0),
            ]

        with m.Else():
            m.d.sync += self.commit_valid.eq(0)

            # ================================================================
            # 1. Retire writeback — runs unconditionally every non-reset cycle.
            # ================================================================
            with m.If(retire_stage.write_reg & (retire_stage.write_reg_index != 0)):
                m.d.sync += self.regs[retire_stage.write_reg_index].eq(retire_stage.write_reg_value)
            with m.If(retire_stage.write_aux_reg & (retire_stage.write_aux_reg_index != 0)):
                m.d.sync += self.regs[retire_stage.write_aux_reg_index].eq(retire_stage.write_aux_reg_value)
            with m.If(retire_stage.write_flags):
                m.d.sync += self.flags.eq(retire_stage.write_flags_value)
            with m.If(execute_to_retire & execute_stage.outputs.clear_reservation):
                m.d.sync += ll_reservation_valid.eq(0)
            with m.If(retire_stage.commit_valid):
                m.d.sync += [
                    self.commit_valid.eq(1),
                    self.commit_pc.eq(retire_stage.commit_valid_pc),
                    self.regs[15].eq(retire.next_pc),
                ]
            with m.If(retire_stage.halt_request):
                m.d.sync += [
                    self.halted.eq(1),
                    self.regs[15].eq(retire.next_pc),
                ]
            with m.If(retire_stage.lockup_request):
                m.d.sync += self.locked_up.eq(1)

            # ================================================================
            # 2. Pipeline advancement — independent per-latch blocks.
            #
            # These blocks run every non-reset cycle and advance the pipeline
            # stages under their own valid/stall conditions.  Exceptional
            # conditions (section 5) come later in the sync block and use
            # last-write-wins to override individual signal assignments here.
            # ================================================================

            # Clear the retire latch; section 3 (MR→Retire) may re-fill it.
            m.d.sync += clear_retire_sync()

            # -- MR buffer → retire latch -----------------------------------
            with m.If(memory_to_retire):
                # Cache fill / store update / invalidation side-effects.
                with m.If(~cached_memory_response & dcache_cacheable_fill):
                    m.d.comb += dcache_fill_valid.eq(1)
                with m.If(~cached_memory_response & xm_reg.write & mem_single_line_access):
                    m.d.comb += dcache_store_update_valid.eq(Const(1 if self.dcache is not None else 0, 1))
                with m.If(~cached_memory_response & xm_reg.write & ~mem_single_line_access):
                    m.d.comb += [
                        dcache_flush_all.eq(Const(1 if self.dcache is not None else 0, 1)),
                        dcache_invalidate_valid.eq(Const(1 if self.dcache is not None else 0, 1)),
                    ]
                with m.If(~cached_memory_response & xm_reg.write & line_match):
                    with m.If((self.config.cache_topology == 'unified') & mem_single_line_access):
                        m.d.comb += frontend_line_update_valid.eq(1)
                    with m.Else():
                        m.d.comb += frontend_store_invalidate.eq(1)
                with m.If(xm_reg.set_reservation):
                    m.d.sync += [
                        ll_reservation_addr.eq(xm_reg.reservation_addr),
                        ll_reservation_valid.eq(1),
                    ]
                with m.If(store_overlaps_reservation):
                    m.d.sync += ll_reservation_valid.eq(0)
                m.d.sync += [
                    mr_valid.eq(1),
                    mr_next_pc.eq(memory_result_next_pc),
                    mr_commit_next_pc.eq(xm_reg.next_pc),
                    mr_reg_write.eq(memory_result_reg_write),
                    mr_reg_index.eq(memory_result_reg_index),
                    mr_reg_value.eq(memory_result_reg_value),
                    mr_aux_reg_write.eq(memory_result_aux_reg_write),
                    mr_aux_reg_index.eq(memory_result_aux_reg_index),
                    mr_aux_reg_value.eq(memory_result_aux_reg_value),
                    mr_commit_pc.eq(xm_reg.commit_pc),
                    mr_flags_write.eq(xm_reg.flags_write),
                    mr_flags_value.eq(xm_reg.flags_value),
                ]

            with m.If(mr_valid):
                m.d.sync += [
                    retire.valid.eq(1),
                    retire.reg_write.eq(mr_reg_write),
                    retire.reg_index.eq(mr_reg_index),
                    retire.reg_value.eq(mr_reg_value),
                    retire.aux_reg_write.eq(mr_aux_reg_write),
                    retire.aux_reg_index.eq(mr_aux_reg_index),
                    retire.aux_reg_value.eq(mr_aux_reg_value),
                    retire.flags_write.eq(mr_flags_write),
                    retire.flags_value.eq(mr_flags_value),
                    retire.cpu_control_write.eq(0),
                    retire.cpu_control_value.eq(0),
                    retire.next_pc.eq(mr_next_pc),
                    retire.commit.eq(1),
                    retire.commit_pc.eq(mr_commit_pc),
                    retire.halt.eq(0),
                    retire.lockup.eq(0),
                    retire.trap.eq(0),
                    retire.trap_cause.eq(0),
                ]
                with m.If(~memory_to_retire):
                    m.d.sync += mr_valid.eq(0)
                with m.If(memory_redirect):
                    m.d.sync += [
                        fd_reg.valid.eq(0),
                        de_reg.valid.eq(0),
                    ] + clear_xm_sync() + redirect_fetch_sync(mr_next_pc)

            with m.If(execute_to_retire):
                m.d.sync += [
                    retire.valid.eq(de_reg.valid),
                    retire.reg_write.eq(execute_stage.outputs.reg_write),
                    retire.reg_index.eq(execute_stage.outputs.reg_index),
                    retire.reg_value.eq(execute_stage.outputs.reg_value),
                    retire.aux_reg_write.eq(0),
                    retire.aux_reg_index.eq(0),
                    retire.aux_reg_value.eq(0),
                    retire.flags_write.eq(execute_stage.outputs.flags_write),
                    retire.flags_value.eq(execute_stage.outputs.flags_value),
                    retire.cpu_control_write.eq(execute_stage.outputs.cpu_control_write),
                    retire.cpu_control_value.eq(execute_stage.outputs.cpu_control_value),
                    retire.next_pc.eq(execute_stage.outputs.next_pc),
                    retire.commit.eq(~execute_stage.outputs.halt & ~execute_stage.outputs.lockup & ~execute_stage.outputs.trap),
                    retire.commit_pc.eq(de_reg.pc),
                    retire.halt.eq(execute_stage.outputs.halt),
                    retire.lockup.eq(execute_stage.outputs.lockup),
                    retire.trap.eq(execute_stage.outputs.trap),
                    retire.trap_cause.eq(execute_stage.outputs.trap_cause),
                ]

            with m.If(execute_to_storebuf_load):
                m.d.sync += [
                    retire.valid.eq(de_reg.valid),
                    retire.reg_write.eq(execute_stage.outputs.memory_reg_write),
                    retire.reg_index.eq(execute_stage.outputs.memory_reg_index),
                    retire.reg_value.eq(storebuf_load_value),
                    retire.aux_reg_write.eq(0),
                    retire.aux_reg_index.eq(0),
                    retire.aux_reg_value.eq(0),
                    retire.flags_write.eq(execute_stage.outputs.memory_flags_write),
                    retire.flags_value.eq(execute_stage.outputs.memory_flags_value),
                    retire.cpu_control_write.eq(0),
                    retire.cpu_control_value.eq(0),
                    retire.next_pc.eq(execute_stage.outputs.memory_next_pc),
                    retire.commit.eq(1),
                    retire.commit_pc.eq(de_reg.pc),
                    retire.halt.eq(0),
                    retire.lockup.eq(0),
                    retire.trap.eq(0),
                    retire.trap_cause.eq(0),
                ]

            with m.If(execute_to_storebuf):
                with m.If(~sb0_valid):
                    m.d.sync += [
                        sb0_valid.eq(1),
                        sb0_started.eq(0),
                        sb0_addr.eq(execute_stage.outputs.memory_addr),
                        sb0_width_bytes.eq(execute_stage.outputs.memory_width_bytes),
                        sb0_store_value.eq(execute_stage.outputs.memory_store_value),
                    ]
                with m.Else():
                    m.d.sync += [
                        sb1_valid.eq(1),
                        sb1_started.eq(0),
                        sb1_addr.eq(execute_stage.outputs.memory_addr),
                        sb1_width_bytes.eq(execute_stage.outputs.memory_width_bytes),
                        sb1_store_value.eq(execute_stage.outputs.memory_store_value),
                    ]
                m.d.sync += [
                    retire.valid.eq(de_reg.valid),
                    retire.reg_write.eq(0),
                    retire.reg_index.eq(0),
                    retire.reg_value.eq(0),
                    retire.aux_reg_write.eq(0),
                    retire.aux_reg_index.eq(0),
                    retire.aux_reg_value.eq(0),
                    retire.flags_write.eq(execute_stage.outputs.memory_flags_write),
                    retire.flags_value.eq(execute_stage.outputs.memory_flags_value),
                    retire.cpu_control_write.eq(0),
                    retire.cpu_control_value.eq(0),
                    retire.next_pc.eq(execute_stage.outputs.memory_next_pc),
                    retire.commit.eq(1),
                    retire.commit_pc.eq(de_reg.pc),
                    retire.halt.eq(0),
                    retire.lockup.eq(0),
                    retire.trap.eq(0),
                    retire.trap_cause.eq(0),
                ]

            with m.If(storebuf_request_start):
                with m.If(storebuf_drain_sb1):
                    m.d.sync += sb1_started.eq(1)
                with m.Else():
                    m.d.sync += sb0_started.eq(1)

            with m.If(storebuf_response_valid):
                with m.If(storebuf_pop_sb1):
                    m.d.sync += [
                        sb1_valid.eq(0),
                        sb1_started.eq(0),
                    ]
                with m.Elif(sb1_valid):
                    m.d.sync += [
                        sb0_valid.eq(1),
                        sb0_started.eq(sb1_started),
                        sb0_addr.eq(sb1_addr),
                        sb0_width_bytes.eq(sb1_width_bytes),
                        sb0_store_value.eq(sb1_store_value),
                        sb1_valid.eq(0),
                        sb1_started.eq(0),
                    ]
                with m.Else():
                    m.d.sync += [
                        sb0_valid.eq(0),
                        sb0_started.eq(0),
                    ]

            # -- XM latch management ----------------------------------------
            with m.If(memory_chain_continue):
                m.d.sync += [
                    xm_reg.request_started.eq(0),
                    xm_reg.virtual_addr.eq(xm_reg.chain_store_addr),
                    xm_reg.addr.eq(xm_reg.chain_store_addr),
                    xm_reg.phys_valid.eq(~paging_enabled),
                    xm_reg.width_bytes.eq(8),
                    xm_reg.write.eq(1),
                    xm_reg.store_value.eq(chain_continue_store_value),
                    xm_reg.reg_write.eq(0),
                    xm_reg.reg_index.eq(0),
                    xm_reg.chain_store.eq(0),
                    xm_reg.chain_store_addr.eq(0),
                    xm_reg.chain_store_use_load_result.eq(0),
                    xm_reg.chain_store_value.eq(0),
                    xm_reg.flags_write.eq(0),
                    xm_reg.flags_value.eq(self.flags),
                    xm_reg.set_reservation.eq(0),
                    xm_reg.reservation_addr.eq(0),
                    self.translate_virtual_addr.eq(xm_reg.chain_store_addr),
                    self.translate_access.eq(ACCESS_WRITE),
                ]
            with m.Elif(memory_to_retire | memory_error):
                m.d.sync += clear_xm_sync() + [
                    self.translate_virtual_addr.eq(self.fetch_pc),
                    self.translate_access.eq(ACCESS_EXECUTE),
                ]
            with m.Elif(execute_to_memory):
                m.d.sync += [
                    xm_reg.valid.eq(1),
                    xm_reg.request_started.eq(0),
                    xm_reg.virtual_addr.eq(execute_stage.outputs.memory_addr),
                    xm_reg.addr.eq(execute_stage.outputs.memory_addr),
                    xm_reg.phys_valid.eq(~paging_enabled),
                    xm_reg.width_bytes.eq(execute_stage.outputs.memory_width_bytes),
                    xm_reg.write.eq(execute_stage.outputs.memory_write),
                    xm_reg.store_value.eq(execute_stage.outputs.memory_store_value),
                    xm_reg.reg_write.eq(execute_stage.outputs.memory_reg_write),
                    xm_reg.reg_index.eq(execute_stage.outputs.memory_reg_index),
                    xm_reg.next_pc.eq(execute_stage.outputs.memory_next_pc),
                    xm_reg.commit_pc.eq(de_reg.pc),
                    xm_reg.fault_pc.eq(de_reg.pc),
                    xm_reg.flags_write.eq(execute_stage.outputs.memory_flags_write),
                    xm_reg.flags_value.eq(execute_stage.outputs.memory_flags_value),
                    xm_reg.set_reservation.eq(execute_stage.outputs.memory_set_reservation),
                    xm_reg.reservation_addr.eq(execute_stage.outputs.memory_reservation_addr),
                    xm_reg.post_reg_write.eq(execute_stage.outputs.memory_post_reg_write),
                    xm_reg.post_reg_index.eq(execute_stage.outputs.memory_post_reg_index),
                    xm_reg.post_reg_value.eq(execute_stage.outputs.memory_post_reg_value),
                    xm_reg.post_reg_delta.eq(execute_stage.outputs.memory_post_reg_delta),
                    xm_reg.post_reg_use_load_result.eq(execute_stage.outputs.memory_post_reg_use_load_result),
                    xm_reg.chain_store.eq(execute_stage.outputs.memory_chain_store),
                    xm_reg.chain_store_addr.eq(execute_stage.outputs.memory_chain_store_addr),
                    xm_reg.chain_store_use_load_result.eq(execute_stage.outputs.memory_chain_store_use_load_result),
                    xm_reg.chain_store_value.eq(execute_stage.outputs.memory_chain_store_value),
                    self.translate_virtual_addr.eq(execute_stage.outputs.memory_addr),
                    self.translate_access.eq(Mux(execute_stage.outputs.memory_write, ACCESS_WRITE, ACCESS_READ)),
                ]
            with m.Elif(xm_reg.valid & memory_stage.start_request):
                m.d.sync += xm_reg.request_started.eq(1)

            # -- Walk / vector bus-request tracking -------------------------
            with m.If(walk_request_start):
                m.d.sync += walk_started.eq(1)
            with m.If(vector_request_start):
                m.d.sync += vector_load_started.eq(1)

            # -- DE latch management ----------------------------------------
            with m.If(decode_advance):
                m.d.sync += [
                    de_reg.valid.eq(1),
                    de_reg.instruction.eq(fd_reg.instruction),
                    de_reg.pc.eq(fd_reg.pc),
                    de_reg.post_increment_pc.eq(fd_reg.post_increment_pc),
                    de_reg.operand_a.eq(decode_stage.outputs.operand_a),
                    de_reg.operand_b.eq(decode_stage.outputs.operand_b),
                    de_reg.flags.eq(decode_stage.outputs.flags),
                    de_reg.predicted_next_pc.eq(decode_stage.predicted_next_pc),
                ]
            with m.Elif(de_reg.valid & (execute_to_memory | execute_to_storebuf | execute_to_storebuf_load | execute_to_retire)):
                m.d.sync += de_reg.valid.eq(0)

            # -- FD latch management ----------------------------------------
            with m.If(execute_flush_younger):
                m.d.sync += fd_reg.valid.eq(0)
            with m.Elif(fetch_accept):
                m.d.sync += [
                    fd_reg.valid.eq(1),
                    fd_reg.instruction.eq(self.frontend.instruction_word),
                    fd_reg.pc.eq(self.fetch_pc),
                    fd_reg.post_increment_pc.eq(next_fetch_pc),
                ]
            with m.Elif(decode_advance):
                m.d.sync += fd_reg.valid.eq(0)

            # -- Fetch PC steering ------------------------------------------
            with m.If(execute_mispredict | trap_start | irq_start):
                m.d.sync += redirect_fetch_sync(execute_stage.outputs.next_pc)
            with m.Elif(memory_redirect):
                m.d.sync += redirect_fetch_sync(mr_next_pc)
            with m.Elif(predict_redirect_active):
                m.d.sync += [
                    self.fetch_pc.eq(decode_stage.predicted_next_pc),
                    self.fetch_phys_addr.eq(Mux(paging_enabled, self.fetch_phys_addr, decode_stage.predicted_next_pc)),
                    fetch_phys_valid.eq(~paging_enabled),
                    self.translate_virtual_addr.eq(decode_stage.predicted_next_pc),
                    self.translate_access.eq(ACCESS_EXECUTE),
                ]
            with m.Elif(fetch_accept):
                m.d.sync += [
                    self.fetch_pc.eq(next_fetch_pc),
                    self.fetch_phys_addr.eq(Mux(paging_enabled, self.fetch_phys_addr, next_fetch_pc)),
                    fetch_phys_valid.eq(~paging_enabled),
                    self.translate_virtual_addr.eq(next_fetch_pc),
                    self.translate_access.eq(ACCESS_EXECUTE),
                ]

            # ================================================================
            # 3. Translate completions — unblock stages on TLB hit.
            #
            # Independent of the pipeline advancement above: these fire
            # whenever the TLB provides a result, regardless of what the
            # pipeline stages are doing.
            # ================================================================
            with m.If(fetch_translate_complete):
                m.d.sync += [
                    self.fetch_phys_addr.eq(fetch_translate_phys),
                    fetch_phys_valid.eq(1),
                ]
            with m.If(memory_translate_complete):
                m.d.sync += [
                    xm_reg.addr.eq(memory_translate_phys),
                    xm_reg.phys_valid.eq(1),
                ]
            with m.If(vector_translate_complete):
                m.d.sync += [
                    vector_load_addr.eq(vector_translate_phys),
                    vector_phys_valid.eq(1),
                ]

            # ================================================================
            # 4. Page-table walk state machine.
            #
            # All walk handlers are mutually exclusive (guarded by
            # walk_processing / walk_leaf_success state).  They run
            # independent of the pipeline advancement blocks above.
            # ================================================================

            # Start a new walk when a translate misses the TLB.
            with m.If(vector_translate_ready & paging_enabled & ~vector_translate_lockup & ~vector_translate_complete):
                m.d.sync += [
                    walk_active.eq(1),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    walk_virtual_addr.eq(vector_virtual_addr),
                    walk_table_addr.eq(self.special_regs.page_table_root_physical),
                    walk_level.eq(2),
                    walk_access.eq(ACCESS_READ),
                    walk_resume_kind.eq(WALK_RESUME_VECTOR),
                    walk_pte_latched.eq(0),
                ]
            with m.If(memory_translate_ready & paging_enabled & ~memory_fault & ~memory_translate_complete):
                m.d.sync += [
                    walk_active.eq(1),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    walk_virtual_addr.eq(xm_reg.virtual_addr),
                    walk_table_addr.eq(self.special_regs.page_table_root_physical),
                    walk_level.eq(2),
                    walk_access.eq(Mux(xm_reg.write, ACCESS_WRITE, ACCESS_READ)),
                    walk_resume_kind.eq(WALK_RESUME_MEMORY),
                    walk_pte_latched.eq(0),
                ]
            with m.If(fetch_translate_ready & paging_enabled & ~fetch_fault & ~fetch_translate_complete):
                m.d.sync += [
                    walk_active.eq(1),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    walk_virtual_addr.eq(self.translate_virtual_addr),
                    walk_table_addr.eq(self.special_regs.page_table_root_physical),
                    walk_level.eq(2),
                    walk_access.eq(ACCESS_EXECUTE),
                    walk_resume_kind.eq(WALK_RESUME_FETCH),
                    walk_pte_latched.eq(0),
                ]

            # Process a good PTE bus response (latch PTE, mark processing=1).
            with m.If(walk_response_valid & ~walk_response_error):
                m.d.sync += [
                    walk_processing.eq(1),
                    walk_pte_latched.eq(self.lsu.response_load_value),
                ]

            # Leaf PTE: update the physical address of the waiting stage.
            with m.If(walk_leaf_success):
                m.d.sync += [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                ]
                with m.If(walk_resume_kind == WALK_RESUME_FETCH):
                    m.d.sync += [
                        self.fetch_phys_addr.eq(walk_result_phys),
                        fetch_phys_valid.eq(1),
                    ]
                with m.Elif(walk_resume_kind == WALK_RESUME_VECTOR):
                    m.d.sync += [
                        vector_load_addr.eq(walk_result_phys),
                        vector_phys_valid.eq(1),
                    ]
                with m.Else():
                    m.d.sync += [
                        xm_reg.addr.eq(walk_result_phys),
                        xm_reg.phys_valid.eq(1),
                    ]

            # Non-leaf PTE: step down to the next radix-tree level.
            with m.If(walk_processing & ~walk_fault & ~walk_leaf_success):
                m.d.sync += [
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    walk_table_addr.eq(walk_table_next),
                    walk_level.eq(walk_level - 1),
                ]

            # ================================================================
            # 5. Vector load — fetch the trap/IRQ handler PC from memory.
            # ================================================================

            # Successful handler-PC response: redirect fetch to handler.
            with m.If(vector_response_valid & ~vector_response_error & (vector_handler_pc != 0)):
                m.d.sync += clear_retire_sync() + [
                    vector_load_active.eq(0),
                    vector_load_started.eq(0),
                    vector_virtual_addr.eq(0),
                    vector_load_addr.eq(0),
                    vector_phys_valid.eq(0),
                    self.regs[15].eq(vector_handler_pc),
                    self.fetch_pc.eq(vector_handler_pc),
                    self.fetch_phys_addr.eq(Mux(paging_enabled, self.fetch_phys_addr, vector_handler_pc)),
                    fetch_phys_valid.eq(~paging_enabled),
                    self.translate_virtual_addr.eq(vector_handler_pc),
                    self.translate_access.eq(ACCESS_EXECUTE),
                ]

            # ================================================================
            # 6. Terminal / exceptional overrides.
            #
            # These come LAST so they win via last-write-wins semantics,
            # squashing any pipeline advancement scheduled above.
            # ================================================================

            # Trap / IRQ entry: flush pipeline and start vector load.
            with m.If(entry_start):
                m.d.sync += clear_pipeline_sync() + [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    vector_load_active.eq(1),
                    vector_load_started.eq(0),
                    vector_virtual_addr.eq(self.special_regs.interrupt_table_base + (entry_vector << 3)),
                    vector_load_addr.eq(self.special_regs.interrupt_table_base + (entry_vector << 3)),
                    vector_phys_valid.eq(~paging_enabled),
                    vector_load_epc.eq(entry_epc),
                    vector_load_flags.eq(self.flags),
                    self.translate_virtual_addr.eq(self.special_regs.interrupt_table_base + (entry_vector << 3)),
                    self.translate_access.eq(ACCESS_READ),
                ]

            # Vector load response error or null handler → lockup.
            with m.If(vector_response_valid & (vector_response_error | (vector_handler_pc == 0))):
                m.d.sync += clear_pipeline_sync() + [
                    vector_load_active.eq(0),
                    vector_load_started.eq(0),
                    vector_virtual_addr.eq(0),
                    vector_load_addr.eq(0),
                    vector_phys_valid.eq(0),
                    vector_load_epc.eq(0),
                    vector_load_flags.eq(0),
                    self.locked_up.eq(1),
                ]

            # Walk bus error → lockup.
            with m.If(walk_response_valid & walk_response_error):
                m.d.sync += clear_pipeline_sync() + [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    self.locked_up.eq(1),
                ]

            # Lockup from vector translate error or walk fault in vector context.
            with m.If(vector_translate_lockup | walk_fault_lockup):
                m.d.sync += clear_pipeline_sync() + [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    vector_load_active.eq(0),
                    vector_load_started.eq(0),
                    vector_virtual_addr.eq(0),
                    vector_load_addr.eq(0),
                    vector_phys_valid.eq(0),
                    vector_load_epc.eq(0),
                    vector_load_flags.eq(0),
                    self.locked_up.eq(1),
                ]

            # Trap preempt escalation → lockup.
            with m.If(trap_preempt_lockup):
                m.d.sync += clear_pipeline_sync() + [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    self.locked_up.eq(1),
                ]

            # Fetch or memory bus error / paging without MMU → lockup.
            with m.If(fetch_error | paging_without_mmu | memory_error | storebuf_response_error):
                m.d.sync += clear_pipeline_sync() + [
                    walk_active.eq(0),
                    walk_processing.eq(0),
                    walk_started.eq(0),
                    self.locked_up.eq(1),
                    sb0_valid.eq(0),
                    sb0_started.eq(0),
                    sb1_valid.eq(0),
                    sb1_started.eq(0),
                ]

            # Halt / lockup requested by retire stage: suppress pipeline.
            with m.If(retire_stage.halt_request | retire_stage.lockup_request):
                m.d.sync += clear_pipeline_sync()

            # Once halted or locked up, keep pipeline clear (absolute last).
            with m.If(self.halted | self.locked_up):
                m.d.sync += clear_pipeline_sync()

            # R0 hard-wired to zero.
            with m.If(self.regs[0] != 0):
                m.d.sync += self.regs[0].eq(0)

        return m


__all__ = ['Little64V4Core']
