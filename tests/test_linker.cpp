#include "linker.hpp"
#include "llvm_assembler.hpp"
#include "support/test_harness.hpp"
#include <cstdio>
#include <string>
#include <vector>

int main() {
    std::string asm_error;
    auto obj1 = LLVMAssembler::assembleSourceText(".global start\nstart: STOP\n", "linker_obj1.asm", asm_error);
    CHECK_TRUE(static_cast<bool>(obj1), "llvm assembler produced object 1");
    if (!obj1) {
        std::fprintf(stderr, "Assembly failed for object 1: %s\n", asm_error.c_str());
        return print_summary();
    }

    auto obj2 = LLVMAssembler::assembleSourceText(".extern start\nMOVE R15, R14\nJUMP @start\n", "linker_obj2.asm", asm_error);
    CHECK_TRUE(static_cast<bool>(obj2), "llvm assembler produced object 2");
    if (!obj2) {
        std::fprintf(stderr, "Assembly failed for object 2: %s\n", asm_error.c_str());
        return print_summary();
    }

    LinkError err;
    auto linked = Linker::linkObjects({*obj1, *obj2}, &err);
    if (!linked) {
        std::fprintf(stderr, "Link failed: %s\n", err.message.c_str());
        CHECK_TRUE(false, "Linking first object set should succeed");
        return print_summary();
    }

    // Check that linked output is non-empty and begins with a jump by comparing first instruction
    CHECK_EQ(linked->size() > 0, true, "Linked output exists");

    // first object is start: STOP (0xDF00), second object has explicit call sequence (MOVE + JUMP)
    CHECK_EQ((*linked)[0], (uint16_t)0xDF00, "First word is STOP from start");
    // The JUMP is the third word (index 2) in final output.
    // Resolves to target=0 from instruction at byte offset 4 => rel=-3 -> 0xFFFD.
    CHECK_EQ((*linked)[2], (uint16_t)0xFFFD, "Third word is JAL to start with resolved PCREL13");

    // Test: local symbol that sorts alphabetically after a global (exercises find_symbol_index)
    //       combined with an opcode whose bits [11:10] are non-zero (exercises PCREL6 mask).
    //
    // "zz_local" is a local label: sorted before globals in the symtab, but alphabetically
    // AFTER "handler". With the old lower_bound-based lookup, find_symbol_index("handler")
    // would land on "zz_local" first and fail.
    //
    // JUMP.Z has opcode 11 (= 0b1011). Bits [11:10] = 0b10. The old mask 0xF00F would zero
    // those bits, silently changing the opcode from JUMP.Z (11) to SHORT_STORE (8).
    // The correct mask is 0xFC0F, which preserves the full 4-bit opcode.
    {
        auto o1 = LLVMAssembler::assembleSourceText(".global handler\nhandler: STOP\n", "linker_obj3.asm", asm_error);
        CHECK_TRUE(static_cast<bool>(o1), "llvm assembler produced object 3");
        if (!o1) {
            std::fprintf(stderr, "Assembly failed for object 3: %s\n", asm_error.c_str());
            return print_summary();
        }

        auto o2 = LLVMAssembler::assembleSourceText(".extern handler\n.global start\nstart: JUMP.Z @handler\nzz_local: STOP\n", "linker_obj4.asm", asm_error);
        CHECK_TRUE(static_cast<bool>(o2), "llvm assembler produced object 4");
        if (!o2) {
            std::fprintf(stderr, "Assembly failed for object 4: %s\n", asm_error.c_str());
            return print_summary();
        }

        LinkError err2;
        auto linked2 = Linker::linkObjects({*o1, *o2}, &err2);
        if (!linked2) {
            std::fprintf(stderr, "Link failed: %s\n", err2.message.c_str());
            CHECK_TRUE(false, "Linking second object set should succeed");
            return print_summary();
        }
        CHECK_EQ((*linked2)[0], (uint16_t)0xDF00, "handler = STOP");
        // JUMP.Z now uses PCREL10 encoding: bits[9:0] = 10-bit offset, no Rd field.
        // JUMP.Z at byte 2, handler at byte 0: rel = (0-(2+2))/2 = -2
        // initial: (1<<14)|(11<<10)|0x000 = 0x6C00
        // patched (PCREL10): (0x6C00 & 0xFC00) | (-2 & 0x3FF) = 0x6C00 | 0x3FE = 0x6FFE
        CHECK_EQ((*linked2)[1], (uint16_t)0x6FFE, "JUMP.Z with external target: correct 10-bit opcode and offset");
        CHECK_EQ((*linked2)[2], (uint16_t)0xDF00, "zz_local = STOP");
    }

    return print_summary();
}
