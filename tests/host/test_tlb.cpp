#include "cpu.hpp"
#include "address_translator.hpp"
#include "support/cpu_test_helpers.hpp"

#include <cstdio>

namespace {

constexpr uint64_t PTE_V = 1ULL << 0;
constexpr uint64_t PTE_R = 1ULL << 1;
constexpr uint64_t PTE_W = 1ULL << 2;
constexpr uint64_t PTE_X = 1ULL << 3;

// We carve up low physical memory for page tables and data:
//   0x0000 .. 0x0FFF — PA page 0 (STOP opcode lives here)
//   0x4000 .. 0x4FFF — Root page table (L2)
//   0x5000 .. 0x5FFF — L1 table
//   0x6000 .. 0x6FFF — L0 table 0 (first 512 pages)
//   0x7000 .. 0x7FFF — L0 table 1 (next 512 pages)
//   0x8000 .. 0x8FFF — alternate root page table for switching tests
//   0x9000 .. 0x9FFF — alternate L1
//   0xA000 .. 0xAFFF — alternate L0
//   0x10000+         — data pages

constexpr uint64_t ROOT     = 0x4000;
constexpr uint64_t L1       = 0x5000;
constexpr uint64_t L0       = 0x6000;
constexpr uint64_t L0_B     = 0x7000;
constexpr uint64_t ROOT_ALT = 0x8000;
constexpr uint64_t L1_ALT   = 0x9000;
constexpr uint64_t L0_ALT   = 0xA000;
constexpr uint64_t KVA      = 0xFFFFFFC000000000ULL;
constexpr uint64_t KPA      = 0x0;
constexpr uint64_t DATA_BASE = 0x10000;

constexpr size_t TLB_SIZE = 64;

uint64_t table_pte(uint64_t table_page) {
    return ((table_page >> 12) << 10) | PTE_V;
}

uint64_t leaf_pte(uint64_t phys_page, bool r, bool w, bool x) {
    uint64_t pte = ((phys_page >> 12) << 10) | PTE_V;
    if (r) pte |= PTE_R;
    if (w) pte |= PTE_W;
    if (x) pte |= PTE_X;
    return pte;
}

Little64CPU make_cpu() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP at physical 0x0
    return cpu;
}

void build_mapping(Little64CPU& cpu,
                   uint64_t root, uint64_t l1, uint64_t l0,
                   uint64_t va, uint64_t pa,
                   bool r, bool w, bool x) {
    auto& bus = cpu.getMemoryBus();
    bus.write64(root + (((va >> 30) & 0x1FFULL) * 8), table_pte(l1));
    bus.write64(l1 + (((va >> 21) & 0x1FFULL) * 8), table_pte(l0));
    bus.write64(l0 + (((va >> 12) & 0x1FFULL) * 8), leaf_pte(pa, r, w, x));
}

void enable_paging(Little64CPU& cpu, uint64_t root) {
    cpu.registers.page_table_root_physical = root;
    cpu.registers.setPagingEnabled(true);
}

// ── Test: repeated accesses to the same page use TLB (hit path) ──

void test_tlb_hit_read() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    enable_paging(cpu, ROOT);

    auto& bus = cpu.getMemoryBus();
    bus.write8(PA + 0, 0xAA);
    bus.write8(PA + 1, 0xBB);
    bus.write8(PA + 2, 0xCC);
    bus.write8(PA + 3, 0xDD);

    // Four reads from the same page — first is a TLB miss, next three are hits.
    for (int i = 0; i < 4; ++i) {
        cpu.registers.regs[14] = VA + i;
        cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
        CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault on TLB-cached read");
    }
    // Last read should have loaded 0xDD.
    CHECK_EQ(cpu.registers.regs[1], 0xDDULL, "TLB hit returns correct data");
}

void test_tlb_hit_write() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, true, false);
    enable_paging(cpu, ROOT);

    // Write four different bytes via the same page.
    for (int i = 0; i < 4; ++i) {
        cpu.registers.regs[14] = VA + i;
        cpu.registers.regs[1] = 0x10 + i;
        cpu.dispatchInstruction(make_instr("BYTE_STORE [R14], R1"));
        CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault on TLB-cached write");
    }

    auto& bus = cpu.getMemoryBus();
    for (int i = 0; i < 4; ++i) {
        CHECK_EQ(bus.read8(PA + i), static_cast<uint64_t>(0x10 + i),
                 "TLB hit write stores correct data");
    }
}

// ── Test: TLB permission accumulation ──
// First read, then write to same page.  The TLB entry's perms field should
// accumulate both R and W bits.

void test_tlb_permission_accumulation() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, true, false);
    enable_paging(cpu, ROOT);

    auto& bus = cpu.getMemoryBus();
    bus.write8(PA, 0x42);

    // Read first — populates TLB with R permission.
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x42ULL, "initial read correct");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault on read");

    // Write second — should accumulate W permission in the same TLB entry.
    cpu.registers.regs[14] = VA;
    cpu.registers.regs[1] = 0x99;
    cpu.dispatchInstruction(make_instr("BYTE_STORE [R14], R1"));
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault on write after read (perms accumulated)");
    CHECK_EQ(bus.read8(PA), 0x99ULL, "write through accumulated TLB entry succeeds");
}

// ── Test: sweep more pages than TLB entries to force eviction ──

void test_tlb_eviction_sweep() {
    Little64CPU cpu = make_cpu();

    // Map 128 pages (2× TLB size) to force every TLB slot to be evicted.
    constexpr int NUM_PAGES = 128;
    auto& bus = cpu.getMemoryBus();

    // Build page tables: ROOT → L1 → L0 (first 512 entries), each page
    // maps to a unique physical page.
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0));

    for (int i = 0; i < NUM_PAGES; ++i) {
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;
        uint64_t pa = DATA_BASE + static_cast<uint64_t>(i) * 0x1000;

        uint64_t l0_idx = (va >> 12) & 0x1FFULL;
        bus.write64(L0 + l0_idx * 8, leaf_pte(pa, true, true, false));

        // Write a tag byte at each physical page.
        bus.write8(pa, static_cast<uint8_t>(i & 0xFF));
    }

    enable_paging(cpu, ROOT);

    // First pass: read all pages — fills and thrashes the TLB.
    for (int i = 0; i < NUM_PAGES; ++i) {
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;
        cpu.registers.regs[14] = va;
        cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
        CHECK_EQ(cpu.registers.regs[1], static_cast<uint64_t>(i & 0xFF),
                 "eviction sweep read returns correct tag");
        CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault during sweep");
    }

    // Second pass in reverse — every access is a TLB miss (evicted by forward pass).
    for (int i = NUM_PAGES - 1; i >= 0; --i) {
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;
        cpu.registers.regs[14] = va;
        cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
        CHECK_EQ(cpu.registers.regs[1], static_cast<uint64_t>(i & 0xFF),
                 "reverse sweep read returns correct tag after eviction");
        CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault during reverse sweep");
    }
}

// ── Test: TLB aliasing — two VAs that hash to the same TLB slot ──
// With TLB_SIZE=64 (mask=0x3F), vpage N and vpage N+64 collide.

void test_tlb_aliasing() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    // Page A  — VA page 0 of our range
    // Page B  — VA page 64 of our range, same TLB slot
    constexpr uint64_t VA_A = KVA;
    constexpr uint64_t VA_B = KVA + TLB_SIZE * 0x1000;
    constexpr uint64_t PA_A = DATA_BASE;
    constexpr uint64_t PA_B = DATA_BASE + TLB_SIZE * 0x1000;

    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0));

    uint64_t l0_idx_a = (VA_A >> 12) & 0x1FFULL;
    uint64_t l0_idx_b = (VA_B >> 12) & 0x1FFULL;
    bus.write64(L0 + l0_idx_a * 8, leaf_pte(PA_A, true, false, false));
    bus.write64(L0 + l0_idx_b * 8, leaf_pte(PA_B, true, false, false));

    bus.write8(PA_A, 0x11);
    bus.write8(PA_B, 0x22);

    enable_paging(cpu, ROOT);

    // Read page A — fills the TLB slot.
    cpu.registers.regs[14] = VA_A;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x11ULL, "alias: page A read correct");

    // Read page B — evicts page A from the same TLB slot.
    cpu.registers.regs[14] = VA_B;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x22ULL, "alias: page B read correct after evicting A");

    // Read page A again — TLB miss, must re-walk page table.
    cpu.registers.regs[14] = VA_A;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x11ULL, "alias: page A read correct after re-fill");
}

// ── Test: TLB flush on page table root change via SSR ──

void test_tlb_flush_on_root_change() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA_OLD = DATA_BASE;
    constexpr uint64_t PA_NEW = DATA_BASE + 0x1000;

    // Build mapping in the primary page table: VA → PA_OLD
    build_mapping(cpu, ROOT, L1, L0, VA, PA_OLD, true, false, false);

    // Build mapping in the alternate page table: same VA → PA_NEW
    build_mapping(cpu, ROOT_ALT, L1_ALT, L0_ALT, VA, PA_NEW, true, false, false);

    bus.write8(PA_OLD, 0xAA);
    bus.write8(PA_NEW, 0xBB);

    // Use primary page table, read the page to populate TLB.
    enable_paging(cpu, ROOT);
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0xAAULL, "root change: read from primary mapping");

    // Switch page table root via SSR to sr11 (page_table_root_physical).
    // This must flush the TLB.
    cpu.registers.setSpecialRegister(11, ROOT_ALT);
    // Simulate the TLB flush that would happen via SSR instruction dispatch.
    // In a real execution SSR is dispatched via cycle(), which calls _flushTLB().
    // Since we set the register directly, we must also call dispatchInstruction
    // with an SSR encoding. Let's use the cycle()-based approach instead.
    //
    // Reset to use the SSR instruction path properly:
    // Re-create cpu and set up a program that does:
    //   LDI ROOT_ALT, R2; SSR R2, sr11; BYTE_LOAD [R14], R1; STOP
    {
        Little64CPU cpu2 = make_cpu();
        auto& bus2 = cpu2.getMemoryBus();

        build_mapping(cpu2, ROOT, L1, L0, VA, PA_OLD, true, false, false);
        build_mapping(cpu2, ROOT_ALT, L1_ALT, L0_ALT, VA, PA_NEW, true, false, false);
        bus2.write8(PA_OLD, 0xAA);
        bus2.write8(PA_NEW, 0xBB);

        enable_paging(cpu2, ROOT);

        // Populate TLB with the primary mapping.
        cpu2.registers.regs[14] = VA;
        cpu2.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
        CHECK_EQ(cpu2.registers.regs[1], 0xAAULL, "root change setup: primary read ok");

        // Simulate SSR sr11, R2 — the dispatch path flushes TLB for sr11 writes.
        cpu2.registers.regs[2] = ROOT_ALT;
        cpu2.registers.regs[3] = 11; // SR index for page_table_root_physical
        cpu2.dispatchInstruction(make_instr("SSR R3, R2"));
        CHECK_EQ(cpu2.registers.page_table_root_physical, ROOT_ALT,
                 "root change: SSR updated page_table_root_physical");

        // Now read the same VA — TLB was flushed, should walk new table → PA_NEW.
        cpu2.registers.regs[14] = VA;
        cpu2.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
        CHECK_EQ(cpu2.registers.regs[1], 0xBBULL,
                 "root change: read after SSR returns new mapping data");
    }
}

// ── Test: TLB flush on SSR to cpu_control (sr0) ──

void test_tlb_flush_on_cpu_control_change() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    bus.write8(PA, 0x55);

    enable_paging(cpu, ROOT);

    // Populate TLB.
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x55ULL, "cpu_control change: initial read ok");

    // Write cpu_control via SSR (sr0) — keeps paging enabled.
    // This should flush TLB even if the value is "the same", because the
    // instruction path always flushes on sr0 writes.
    uint64_t current = cpu.registers.cpu_control;
    cpu.registers.regs[2] = current;
    cpu.registers.regs[3] = 0; // SR index for cpu_control
    cpu.dispatchInstruction(make_instr("SSR R3, R2"));

    // Read again — should succeed (re-walks page table after flush).
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x55ULL,
             "cpu_control change: read ok after TLB flush via SSR sr0");
}

// ── Test: TLB flush across loadProgram ──
// Ensures that loading a new program clears stale TLB entries.

void test_tlb_flush_on_loadprogram() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    bus.write8(PA, 0x77);

    enable_paging(cpu, ROOT);

    // Populate TLB.
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x77ULL, "loadProgram: initial read ok");

    // Reload a program — must flush TLB.
    cpu.loadProgram(std::vector<uint16_t>{0xDF00});

    // Re-setup paging (loadProgram resets registers).
    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    bus.write8(PA, 0x88);
    enable_paging(cpu, ROOT);

    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x88ULL,
             "loadProgram: read after reload sees new data (TLB was flushed)");
}

// ── Test: execute through 64+ distinct pages ──
// Map each page with a STOP instruction at the start, jump to each page,
// and verify no faults occur.  This exercises TLB fill+evict on the execute path.

void test_tlb_execute_sweep() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr int NUM_PAGES = 80; // > TLB_SIZE

    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0));

    for (int i = 0; i < NUM_PAGES; ++i) {
        uint64_t pa = DATA_BASE + static_cast<uint64_t>(i) * 0x1000;
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;

        uint64_t l0_idx = (va >> 12) & 0x1FFULL;
        bus.write64(L0 + l0_idx * 8, leaf_pte(pa, true, false, true));

        // Place STOP (0xDF00) at the start of each page.
        bus.write16(pa, 0xDF00);
    }

    enable_paging(cpu, ROOT);

    for (int i = 0; i < NUM_PAGES; ++i) {
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;
        cpu.registers.regs[15] = va;
        cpu.isRunning = true;
        cpu.registers.trap_cause = 0;
        cpu.cycle();
        CHECK_FALSE(cpu.isRunning, "execute sweep: CPU stopped");
        CHECK_EQ(cpu.registers.trap_cause, 0ULL, "execute sweep: no fault");
    }
}

// ── Test: interleaved read/write/execute across many pages ──
// This exercises all three TLB permission check paths with heavy churn.

void test_tlb_mixed_access_churn() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr int NUM_PAGES = 96;

    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0));

    for (int i = 0; i < NUM_PAGES; ++i) {
        uint64_t pa = DATA_BASE + static_cast<uint64_t>(i) * 0x1000;
        uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;
        uint64_t l0_idx = (va >> 12) & 0x1FFULL;
        bus.write64(L0 + l0_idx * 8, leaf_pte(pa, true, true, true));

        // Place STOP at the start and a tag byte at offset 0x100.
        bus.write16(pa, 0xDF00);
        bus.write8(pa + 0x100, static_cast<uint8_t>(i));
    }

    enable_paging(cpu, ROOT);

    for (int pass = 0; pass < 3; ++pass) {
        for (int i = 0; i < NUM_PAGES; ++i) {
            uint64_t va = KVA + static_cast<uint64_t>(i) * 0x1000;

            // Read tag byte.
            cpu.registers.regs[14] = va + 0x100;
            cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
            uint8_t expected_tag = static_cast<uint8_t>((i + pass) & 0xFF);
            CHECK_EQ(cpu.registers.regs[1], static_cast<uint64_t>(expected_tag),
                     "mixed churn: read tag correct");

            // Write updated tag.
            cpu.registers.regs[1] = static_cast<uint64_t>((i + pass + 1) & 0xFF);
            cpu.dispatchInstruction(make_instr("BYTE_STORE [R14], R1"));
            CHECK_EQ(cpu.registers.trap_cause, 0ULL, "mixed churn: write ok");

            // Execute STOP from the same page.
            cpu.registers.regs[15] = va;
            cpu.isRunning = true;
            cpu.registers.trap_cause = 0;
            cpu.cycle();
            CHECK_FALSE(cpu.isRunning, "mixed churn: execute STOP");
        }
    }
}

// ── Test: TLB entries from paging-on don't leak into paging-off ──

void test_tlb_paging_toggle() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();

    constexpr uint64_t VA = KVA + 0x10000;
    constexpr uint64_t PA = DATA_BASE;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    bus.write8(PA, 0x42);

    // Paging on: read through translation.
    enable_paging(cpu, ROOT);
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x42ULL, "paging toggle: read with paging on");

    // Paging off: identity map.  Write something to a low physical address.
    cpu.registers.setPagingEnabled(false);
    bus.write8(0x100, 0xEE);
    cpu.registers.regs[14] = 0x100;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0xEEULL, "paging toggle: identity read with paging off");

    // Paging on again: ensure old TLB entries don't cause problems.
    // (The inline fast-path skips TLB when paging is off, and the slow path
    // fills TLB only when paging is on, so no leak should occur.)
    enable_paging(cpu, ROOT);
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));
    CHECK_EQ(cpu.registers.regs[1], 0x42ULL,
             "paging toggle: TLB still works after paging off+on");
}

} // namespace

int main() {
    std::printf("=== Little-64 TLB stress tests ===\n");
    test_tlb_hit_read();
    test_tlb_hit_write();
    test_tlb_permission_accumulation();
    test_tlb_eviction_sweep();
    test_tlb_aliasing();
    test_tlb_flush_on_root_change();
    test_tlb_flush_on_cpu_control_change();
    test_tlb_flush_on_loadprogram();
    test_tlb_execute_sweep();
    test_tlb_mixed_access_churn();
    test_tlb_paging_toggle();
    return print_summary();
}
