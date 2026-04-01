#include "disassembler.hpp"
#include "support/test_harness.hpp"

#include <array>
#include <cstdio>

static void test_gp_decode_text_and_fields() {
    auto add = Disassembler::disassemble(0xC012, 0x0000); // ADD R1, R2
    CHECK_EQ(add.is_unknown, false, "ADD is recognized");
    CHECK_EQ(add.format, 3, "ADD is format 11");
    CHECK_EQ(add.opcode_gp, 0, "ADD opcode is 0");
    CHECK_EQ(add.rs1, 1, "ADD rs1 is R1");
    CHECK_EQ(add.rd, 2, "ADD rd is R2");
    CHECK_EQ(add.text == "ADD R1, R2", true, "ADD disassembly text");
}

static void test_conditional_jump_decode() {
    auto jz = Disassembler::disassemble(0x6FFE, 0x0002); // JUMP.Z @-2 at addr 2 => eff 0
    CHECK_EQ(jz.is_unknown, false, "JUMP.Z is recognized");
    CHECK_EQ(jz.format, 1, "JUMP.Z uses LS PC-relative format");
    CHECK_EQ(jz.opcode_ls, 11, "JUMP.Z opcode is 11");
    CHECK_EQ(jz.rd, 15, "JUMP.Z has implicit R15 destination");
    CHECK_EQ(jz.pc_rel, -2, "JUMP.Z decodes signed 10-bit offset");
    CHECK_EQ(jz.effective_address, 0x0000, "JUMP.Z effective address");
}

static void test_unconditional_jump_decode() {
    auto jmp = Disassembler::disassemble(0xE002, 0x0000); // JUMP @+2
    CHECK_EQ(jmp.is_unknown, false, "JUMP is recognized");
    CHECK_EQ(jmp.is_unconditional_jump, true, "JUMP uses unconditional extended format");
    CHECK_EQ(jmp.pc_rel, 2, "JUMP signed offset decode");
    CHECK_EQ(jmp.effective_address, 0x0006, "JUMP effective address");
    CHECK_EQ(jmp.text == "JUMP @+2  ; 0x0006", true, "JUMP disassembly text");
}

static void test_buffer_disassembly_addresses() {
    std::array<uint16_t, 2> words = {0x8000, 0xDF00}; // LDI #0x0,R0 ; STOP
    auto out = Disassembler::disassembleBuffer(words.data(), words.size(), 0x0100);
    CHECK_EQ(out.size(), 2ULL, "disassembleBuffer emits one record per word");
    CHECK_EQ(out[0].address, 0x0100, "first instruction address");
    CHECK_EQ(out[1].address, 0x0102, "second instruction address");
}

int main() {
    std::printf("=== Little-64 disassembler tests ===\n");
    test_gp_decode_text_and_fields();
    test_conditional_jump_decode();
    test_unconditional_jump_decode();
    test_buffer_disassembly_addresses();
    return print_summary();
}
