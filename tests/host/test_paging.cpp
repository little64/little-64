#include "cpu.hpp"
#include "address_translator.hpp"
#include "support/cpu_test_helpers.hpp"

#include <cstdio>

namespace {

constexpr uint64_t PTE_V = 1ULL << 0;
constexpr uint64_t PTE_R = 1ULL << 1;
constexpr uint64_t PTE_W = 1ULL << 2;
constexpr uint64_t PTE_X = 1ULL << 3;
constexpr uint64_t PTE_RESERVED63 = 1ULL << 63;

constexpr uint64_t ROOT = 0x4000;
constexpr uint64_t L1 = 0x5000;
constexpr uint64_t L0 = 0x6000;
constexpr uint64_t KVA = 0xFFFFFFC000000000ULL;
constexpr uint64_t KPA = 0x0;

constexpr uint64_t AUX_NO_VALID = AddressTranslator::AUX_SUBTYPE_NO_VALID_PTE;
constexpr uint64_t AUX_INVALID_NONLEAF = AddressTranslator::AUX_SUBTYPE_INVALID_NONLEAF;
constexpr uint64_t AUX_PERMISSION = AddressTranslator::AUX_SUBTYPE_PERMISSION;
constexpr uint64_t AUX_RESERVED = AddressTranslator::AUX_SUBTYPE_RESERVED_BIT;
constexpr uint64_t AUX_CANONICAL = AddressTranslator::AUX_SUBTYPE_CANONICAL;

uint64_t aux_code(uint64_t subtype, uint64_t level) {
    return (subtype & 0xFULL) | ((level & 0xFFULL) << 8);
}

Little64CPU make_cpu() {
    Little64CPU cpu;
    cpu.loadProgram(std::vector<uint16_t>{0xDF00}); // STOP at physical 0x0
    return cpu;
}

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

void build_mapping(Little64CPU& cpu,
                   uint64_t root,
                   uint64_t l1,
                   uint64_t l0,
                   uint64_t va,
                   uint64_t pa,
                   bool r,
                   bool w,
                   bool x) {
    auto& bus = cpu.getMemoryBus();
    bus.write64(root + (((va >> 30) & 0x1FFULL) * 8), table_pte(l1));
    bus.write64(l1 + (((va >> 21) & 0x1FFULL) * 8), table_pte(l0));
    bus.write64(l0 + (((va >> 12) & 0x1FFULL) * 8), leaf_pte(pa, r, w, x));
}

void enable_paging(Little64CPU& cpu, uint64_t root) {
    cpu.registers.page_table_root_physical = root;
    cpu.registers.setPagingEnabled(true);
}

void expect_fault_common(const Little64CPU& cpu,
                         uint64_t cause,
                         uint64_t access,
                         uint64_t fault_addr,
                         uint64_t aux) {
    CHECK_FALSE(cpu.isRunning, "fault stops CPU when exception is not handled");
    CHECK_EQ(cpu.registers.trap_cause, cause, "expected paging fault cause");
    CHECK_EQ(cpu.registers.trap_access, access, "expected trap_access kind");
    CHECK_EQ(cpu.registers.trap_fault_addr, fault_addr, "expected trap fault address");
    CHECK_EQ(cpu.registers.trap_aux, aux, "expected trap_aux subtype/level");
}

void test_execute_translation_success() {
    Little64CPU cpu = make_cpu();

    build_mapping(cpu, ROOT, L1, L0, KVA, KPA, true, false, true);
    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;

    cpu.cycle();
    CHECK_FALSE(cpu.isRunning, "mapped execute fetch reaches STOP instruction");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no trap on valid execute mapping");
}

void test_paging_disabled_identity_execute() {
    Little64CPU cpu = make_cpu();
    cpu.registers.regs[15] = 0;
    cpu.cycle();
    CHECK_FALSE(cpu.isRunning, "identity execute reaches STOP with paging disabled");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no fault when paging disabled identity executes");
}

void test_execute_alignment_fault() {
    Little64CPU cpu = make_cpu();
    cpu.registers.regs[15] = 1;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_EXEC_ALIGN,
                        2,
                        1,
                        aux_code(AddressTranslator::AUX_SUBTYPE_NONE, 0));
}

void test_canonical_fault() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t NON_CANON = 0xFFFFFF8000000000ULL;
    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = NON_CANON;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_CANONICAL,
                        2,
                        NON_CANON,
                        aux_code(AUX_CANONICAL, 2));
}

void test_root_misaligned_fault() {
    Little64CPU cpu = make_cpu();
    enable_paging(cpu, ROOT + 8);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_RESERVED,
                        2,
                        KVA,
                        aux_code(AUX_RESERVED, 2));
}

void test_not_present_l2_fault() {
    Little64CPU cpu = make_cpu();
    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_NOT_PRESENT,
                        2,
                        KVA,
                        aux_code(AUX_NO_VALID, 2));
}

void test_not_present_l1_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_NOT_PRESENT,
                        2,
                        KVA,
                        aux_code(AUX_NO_VALID, 1));
}

void test_not_present_l0_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0));

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_NOT_PRESENT,
                        2,
                        KVA,
                        aux_code(AUX_NO_VALID, 0));
}

void test_invalid_nonleaf_l2_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), leaf_pte(L1, true, false, false));

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_RESERVED,
                        2,
                        KVA,
                        aux_code(AUX_INVALID_NONLEAF, 2));
}

void test_invalid_nonleaf_l1_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), leaf_pte(L0, true, false, false));

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_RESERVED,
                        2,
                        KVA,
                        aux_code(AUX_INVALID_NONLEAF, 1));
}

void test_reserved_bit_l1_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    bus.write64(ROOT + (((KVA >> 30) & 0x1FFULL) * 8), table_pte(L1));
    bus.write64(L1 + (((KVA >> 21) & 0x1FFULL) * 8), table_pte(L0) | PTE_RESERVED63);

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_RESERVED,
                        2,
                        KVA,
                        aux_code(AUX_RESERVED, 1));
}

void test_reserved_bit_leaf_fault() {
    Little64CPU cpu = make_cpu();
    auto& bus = cpu.getMemoryBus();
    build_mapping(cpu, ROOT, L1, L0, KVA, KPA, true, false, true);
    const uint64_t leaf_addr = L0 + (((KVA >> 12) & 0x1FFULL) * 8);
    bus.write64(leaf_addr, bus.read64(leaf_addr) | PTE_RESERVED63);

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = KVA;
    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_RESERVED,
                        2,
                        KVA,
                        aux_code(AUX_RESERVED, 0));
}

void test_execute_permission_fault() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x2000;

    build_mapping(cpu, ROOT, L1, L0, VA, KPA, true, false, false);

    enable_paging(cpu, ROOT);
    cpu.registers.regs[15] = VA;

    cpu.cycle();

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_PERMISSION,
                        2,
                        VA,
                        aux_code(AUX_PERMISSION, 0));
}

void test_read_permission_fault() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x3000;
    constexpr uint64_t PA = 0x3000;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, false, false, true);

    enable_paging(cpu, ROOT);
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_PERMISSION,
                        0,
                        VA,
                        aux_code(AUX_PERMISSION, 0));
}

void test_store_permission_fault() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t DVA = KVA + 0x4000;
    constexpr uint64_t DPA = 0x2000;

    build_mapping(cpu, ROOT, L1, L0, DVA, DPA, true, false, false);

    enable_paging(cpu, ROOT);

    cpu.registers.regs[14] = DVA;
    cpu.registers.regs[1] = 0xAB;
    cpu.dispatchInstruction(make_instr("BYTE_STORE [R14], R1"));

    expect_fault_common(cpu,
                        AddressTranslator::TRAP_PAGE_FAULT_PERMISSION,
                        1,
                        DVA,
                        aux_code(AUX_PERMISSION, 0));
}

void test_read_translation_success() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x5000;
    constexpr uint64_t PA = 0x3000;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, false, false);
    enable_paging(cpu, ROOT);

    cpu.getMemoryBus().write8(PA, 0x5A);
    cpu.registers.regs[14] = VA;
    cpu.dispatchInstruction(make_instr("BYTE_LOAD [R14], R1"));

    CHECK_EQ(cpu.registers.regs[1], 0x5AULL, "BYTE_LOAD reads translated physical byte");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no trap on valid read mapping");
}

void test_store_translation_success() {
    Little64CPU cpu = make_cpu();
    constexpr uint64_t VA = KVA + 0x6000;
    constexpr uint64_t PA = 0x3000;

    build_mapping(cpu, ROOT, L1, L0, VA, PA, true, true, false);
    enable_paging(cpu, ROOT);

    cpu.registers.regs[14] = VA;
    cpu.registers.regs[1] = 0xC7;
    cpu.dispatchInstruction(make_instr("BYTE_STORE [R14], R1"));

    CHECK_EQ(cpu.getMemoryBus().read8(PA), 0xC7ULL, "BYTE_STORE writes translated physical byte");
    CHECK_EQ(cpu.registers.trap_cause, 0ULL, "no trap on valid write mapping");
}

} // namespace

int main() {
    std::printf("=== Little-64 paging tests ===\n");
    test_paging_disabled_identity_execute();
    test_execute_translation_success();
    test_execute_alignment_fault();
    test_canonical_fault();
    test_root_misaligned_fault();
    test_not_present_l2_fault();
    test_not_present_l1_fault();
    test_not_present_l0_fault();
    test_invalid_nonleaf_l2_fault();
    test_invalid_nonleaf_l1_fault();
    test_reserved_bit_l1_fault();
    test_reserved_bit_leaf_fault();
    test_execute_permission_fault();
    test_read_permission_fault();
    test_store_permission_fault();
    test_read_translation_success();
    test_store_translation_success();
    return print_summary();
}
