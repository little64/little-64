// Little-64 assembler test suite
// Groups A-I are a regression baseline against the pre-rework assembler.
// Group G2 is the motivating test for the mixed code/data rework:
//   it FAILS on the old assembler (data-after-instructions layout)
//   and PASSES after the rework.
// Group J (.ascii/.asciiz) is added after the lexer/assembler rework.

#include "assembler.hpp"
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Minimal test harness
// ---------------------------------------------------------------------------

static int _pass = 0, _fail = 0;

#define CHECK_EQ(actual, expected, msg)                                        \
    do {                                                                       \
        auto _a = (actual);                                                    \
        auto _e = (expected);                                                  \
        if (_a == _e) {                                                        \
            _pass++;                                                           \
        } else {                                                               \
            std::fprintf(stderr, "FAIL [%s:%d] %s\n"                          \
                                 "  expected: 0x%04X\n"                        \
                                 "  actual  : 0x%04X\n",                       \
                         __FILE__, __LINE__, (msg),                            \
                         static_cast<unsigned>(_e),                            \
                         static_cast<unsigned>(_a));                           \
            _fail++;                                                           \
        }                                                                      \
    } while (0)

#define CHECK_THROWS(expr, msg)                                                \
    do {                                                                       \
        bool _threw = false;                                                   \
        try { (expr); } catch (...) { _threw = true; }                         \
        if (_threw) {                                                          \
            _pass++;                                                           \
        } else {                                                               \
            std::fprintf(stderr, "FAIL [%s:%d] expected exception: %s\n",     \
                         __FILE__, __LINE__, (msg));                           \
            _fail++;                                                           \
        }                                                                      \
    } while (0)

static std::vector<uint16_t> assemble(const std::string& src) {
    Assembler a;
    return a.assemble(src);
}

// ---------------------------------------------------------------------------
// Group A — LDI encoding
// Format 10: (2<<14) | (shift<<12) | (imm8<<4) | rd
// ---------------------------------------------------------------------------

static void test_ldi_encoding() {
    // LDI #5, R3 → shift=0, imm=5, rd=3
    // 0x8000 | 0x0000 | 0x0050 | 0x0003 = 0x8053
    CHECK_EQ(assemble("LDI #5, R3")[0], 0x8053, "LDI #5, R3");

    // LDI.S1 #0xFF, R0 → shift=1, imm=255, rd=0
    // 0x8000 | 0x1000 | 0x0FF0 | 0x0000 = 0x9FF0
    CHECK_EQ(assemble("LDI.S1 #0xFF, R0")[0], 0x9FF0, "LDI.S1 #0xFF, R0");

    // LDI #0, R0 → shift=0, imm=0, rd=0
    CHECK_EQ(assemble("LDI #0, R0")[0], 0x8000, "LDI #0, R0");

    // LDI #255, R15 → shift=0, imm=255, rd=15
    // 0x8000 | 0x0FF0 | 0x000F = 0x8FFF
    CHECK_EQ(assemble("LDI #255, R15")[0], 0x8FFF, "LDI #255, R15");

    // LDI.S3 #1, R1 → shift=3, imm=1, rd=1
    // 0x8000 | 0x3000 | 0x0010 | 0x0001 = 0xB011
    CHECK_EQ(assemble("LDI.S3 #1, R1")[0], 0xB011, "LDI.S3 #1, R1");

    // Alternate shift syntax: LDI.2 #7, R4 → shift=2, imm=7, rd=4
    // 0x8000 | 0x2000 | 0x0070 | 0x0004 = 0xA074
    CHECK_EQ(assemble("LDI.2 #7, R4")[0], 0xA074, "LDI.2 #7, R4");
}

// ---------------------------------------------------------------------------
// Group B — GP encoding
// Format 11: (3<<14) | (opcode<<8) | (rs1<<4) | rd
// Opcodes: ADD=0, SUB=1, AND=2, OR=3, TEST=4, STOP=63
// ---------------------------------------------------------------------------

static void test_gp_encoding() {
    // ADD R1, R2 → op=0, rs1=1, rd=2
    // 0xC000 | 0x0000 | 0x0010 | 0x0002 = 0xC012
    CHECK_EQ(assemble("ADD R1, R2")[0], 0xC012, "ADD R1, R2");

    // SUB R3, R4 → op=1, rs1=3, rd=4
    // 0xC000 | 0x0100 | 0x0030 | 0x0004 = 0xC134
    CHECK_EQ(assemble("SUB R3, R4")[0], 0xC134, "SUB R3, R4");

    // AND R2, R1 → op=2, rs1=2, rd=1
    // 0xC000 | 0x0200 | 0x0020 | 0x0001 = 0xC221
    CHECK_EQ(assemble("AND R2, R1")[0], 0xC221, "AND R2, R1");

    // OR R0, R5 → op=3, rs1=0, rd=5
    // 0xC000 | 0x0300 | 0x0000 | 0x0005 = 0xC305
    CHECK_EQ(assemble("OR R0, R5")[0], 0xC305, "OR R0, R5");

    // TEST R7, R7 → op=4, rs1=7, rd=7
    // 0xC000 | 0x0400 | 0x0070 | 0x0007 = 0xC477
    CHECK_EQ(assemble("TEST R7, R7")[0], 0xC477, "TEST R7, R7");

    // STOP → op=63, rs1=0, rd=0
    // 0xC000 | 0x3F00 | 0x0000 | 0x0000 = 0xFF00
    CHECK_EQ(assemble("STOP")[0], 0xFF00, "STOP");
}

// ---------------------------------------------------------------------------
// Group C — LS_REG encoding
// Format 00: (opcode<<10) | (offset2<<8) | (rs1<<4) | rd
// Opcodes: LOAD=0, STORE=1, BYTE_LOAD=5, MOVE=4
// ---------------------------------------------------------------------------

static void test_ls_reg_encoding() {
    // LOAD [R2+4], R5 → op=0, offset2=2, rs1=2, rd=5
    // 0x0000 | 0x0200 | 0x0020 | 0x0005 = 0x0225
    CHECK_EQ(assemble("LOAD [R2+4], R5")[0], 0x0225, "LOAD [R2+4], R5");

    // STORE [R1], R3 → op=1, offset2=0, rs1=1, rd=3
    // 0x0400 | 0x0000 | 0x0010 | 0x0003 = 0x0413
    CHECK_EQ(assemble("STORE [R1], R3")[0], 0x0413, "STORE [R1], R3");

    // LOAD [R0], R0 → all zero
    CHECK_EQ(assemble("LOAD [R0], R0")[0], 0x0000, "LOAD [R0], R0");

    // BYTE_LOAD [R3+2], R4 → op=5, offset2=1, rs1=3, rd=4
    // 0x1400 | 0x0100 | 0x0030 | 0x0004 = 0x1534
    CHECK_EQ(assemble("BYTE_LOAD [R3+2], R4")[0], 0x1534, "BYTE_LOAD [R3+2], R4");

    // MOVE R5+6, R7 → op=4, offset2=3, rs1=5, rd=7
    // 0x1000 | 0x0300 | 0x0050 | 0x0007 = 0x1357
    CHECK_EQ(assemble("MOVE R5+6, R7")[0], 0x1357, "MOVE R5+6, R7");

    // Maximum offset: LOAD [R15+6], R15 → op=0, offset2=3, rs1=15, rd=15
    // 0x0000 | 0x0300 | 0x00F0 | 0x000F = 0x03FF
    CHECK_EQ(assemble("LOAD [R15+6], R15")[0], 0x03FF, "LOAD [R15+6], R15");
}

// ---------------------------------------------------------------------------
// Group D — LS_PCREL encoding
// Format 01: (1<<14) | (opcode<<10) | (pc_rel_6bit<<4) | rd
// pc_rel = (target - (instr_addr + 2)) / 2, range [-32, 31]
// LOAD opcode=0
// ---------------------------------------------------------------------------

static void test_ls_pcrel_encoding() {
    // LOAD @+0, R1 → op=0, pc_rel=0, rd=1
    // 0x4000 | 0x0000 | 0x0000 | 0x0001 = 0x4001
    CHECK_EQ(assemble("LOAD @+0, R1")[0], 0x4001, "LOAD @+0, R1");

    // LOAD @+1, R2 → pc_rel=1, rd=2
    // 0x4000 | 0x0010 | 0x0002 = 0x4012
    CHECK_EQ(assemble("LOAD @+1, R2")[0], 0x4012, "LOAD @+1, R2");

    // LOAD @-1, R0 → pc_rel=-1, 6-bit: 0x3F
    // 0x4000 | (0x3F<<4) | 0 = 0x4000 | 0x03F0 = 0x43F0
    CHECK_EQ(assemble("LOAD @-1, R0")[0], 0x43F0, "LOAD @-1, R0");

    // Forward label reference: target is 6 bytes ahead of instruction
    // .org 0; LOAD @target, R1; STOP; STOP; target: STOP
    // instr_addr=0, target=6, byte_diff=6-(0+2)=4, pc_rel=4/2=2
    // 0x4000 | (2<<4) | 1 = 0x4021
    {
        auto out = assemble(".org 0\n    LOAD @target, R1\n    STOP\n    STOP\ntarget:\n    STOP\n");
        CHECK_EQ(out[0], 0x4021, "forward label: LOAD @target 6 bytes ahead");
    }

    // Backward label reference
    // .org 0; target: STOP; STOP; LOAD @target, R1
    // instr_addr=4, target=0, byte_diff=0-(4+2)=-6, pc_rel=-6/2=-3
    // -3 as 6-bit: (-3 & 0x3F) = 0x3D
    // 0x4000 | (0x3D<<4) | 1 = 0x4000 | 0x03D0 | 0x0001 = 0x43D1
    {
        auto out = assemble(".org 0\ntarget:\n    STOP\n    STOP\n    LOAD @target, R1\n");
        CHECK_EQ(out[2], 0x43D1, "backward label: LOAD @target 6 bytes behind");
    }
}

// ---------------------------------------------------------------------------
// Group E — JUMP pseudo-instruction (encodes as MOVE, opcode=4, Rd=R15)
// ---------------------------------------------------------------------------

static void test_jump_pseudo() {
    // JUMP @+0 → MOVE PC-rel, pc_rel=0, rd=15
    // 0x4000 | (4<<10) | (0<<4) | 15 = 0x4000 | 0x1000 | 0x000F = 0x500F
    CHECK_EQ(assemble("JUMP @+0")[0], 0x500F, "JUMP @+0");

    // JUMP @-1 → MOVE PC-rel, pc_rel=-1 (0x3F), rd=15
    // 0x4000 | 0x1000 | (0x3F<<4) | 0xF = 0x4000|0x1000|0x03F0|0x000F = 0x53FF
    CHECK_EQ(assemble("JUMP @-1")[0], 0x53FF, "JUMP @-1");

    // JUMP R3 → MOVE LS_REG, offset2=0, rs1=3, rd=15
    // (4<<10) | (0<<8) | (3<<4) | 15 = 0x1000 | 0x0030 | 0x000F = 0x103F
    CHECK_EQ(assemble("JUMP R3")[0], 0x103F, "JUMP R3");

    // JUMP R2+4 → MOVE LS_REG, offset2=2, rs1=2, rd=15
    // (4<<10) | (2<<8) | (2<<4) | 15 = 0x1000|0x0200|0x0020|0x000F = 0x122F
    CHECK_EQ(assemble("JUMP R2+4, R15")[0], 0x122F, "JUMP R2+4, R15");

    // JUMP label forward: resolves same as MOVE @label, R15
    {
        auto out = assemble(".org 0\n    JUMP @target\n    STOP\n    STOP\ntarget:\n    STOP\n");
        // MOVE pc_rel=2, rd=15: 0x4000|0x1000|(2<<4)|0xF = 0x500F|0x20 = 0x502F
        CHECK_EQ(out[0], 0x502F, "JUMP @label forward (=MOVE @label, R15)");
    }
}

// ---------------------------------------------------------------------------
// Group F — Conditional jumps with implicit R15 destination
// JUMP.Z=11, JUMP.C=12, JUMP.S=13, JUMP.GT=14, JUMP.LT=15
// ---------------------------------------------------------------------------

static void test_conditional_jumps() {
    // JUMP.Z @+0 → LS_PCREL, opcode=11=0xB, pc_rel=0, rd=15
    // (1<<14) | (0xB<<10) | (0<<4) | 15 = 0x4000|0x2C00|0x000F = 0x6C0F
    CHECK_EQ(assemble("JUMP.Z @+0")[0], 0x6C0F, "JUMP.Z @+0 implicit R15");

    // JUMP.Z R2 → LS_REG, opcode=0xB, offset2=0, rs1=2, rd=15
    // (0xB<<10) | (0<<8) | (2<<4) | 15 = 0x2C00|0x0020|0x000F = 0x2C2F
    CHECK_EQ(assemble("JUMP.Z R2")[0], 0x2C2F, "JUMP.Z R2 implicit R15");

    // JUMP.C @+0 → opcode=12=0xC, pc_rel=0, rd=15
    // (1<<14) | (0xC<<10) | 0 | 15 = 0x4000|0x3000|0x000F = 0x700F
    CHECK_EQ(assemble("JUMP.C @+0")[0], 0x700F, "JUMP.C @+0");

    // JUMP.Z @+0, R0 → explicit rd=0
    // (1<<14) | (0xB<<10) | 0 | 0 = 0x6C00
    CHECK_EQ(assemble("JUMP.Z @+0, R0")[0], 0x6C00, "JUMP.Z @+0, R0 explicit dest");

    // JUMP.GT @+0 → opcode=14=0xE
    // (1<<14)|(0xE<<10)|0|15 = 0x4000|0x3800|0x000F = 0x7C0F
    CHECK_EQ(assemble("JUMP.GT @+0")[0], 0x780F, "JUMP.GT @+0");
}

// ---------------------------------------------------------------------------
// Group G — Data directives, all data after code (safe in both old and new)
// ---------------------------------------------------------------------------

static void test_data_directives() {
    // .byte 0xAB after STOP
    // Instructions: [0xFF00]. Data bytes: [0xAB, 0x00(pad)]. Word: 0x00AB.
    {
        auto out = assemble("STOP\n.byte 0xAB\n");
        CHECK_EQ(out[0], 0xFF00, ".byte after STOP: instruction word");
        CHECK_EQ(out[1], 0x00AB, ".byte after STOP: data word (padded)");
    }

    // Two .byte values pack little-endian into one word
    // data bytes: [0x12, 0x34]. Word: 0x12 | (0x34<<8) = 0x3412
    {
        auto out = assemble("STOP\n.byte 0x12\n.byte 0x34\n");
        CHECK_EQ(out[1], 0x3412, "two .byte → one LE word");
    }

    // .short 0xBEEF after STOP → little-endian bytes [0xEF,0xBE] → word 0xBEEF
    {
        auto out = assemble("STOP\n.short 0xBEEF\n");
        CHECK_EQ(out[0], 0xFF00, ".short after STOP: instruction");
        CHECK_EQ(out[1], 0xBEEF, ".short 0xBEEF");
    }

    // .word is an alias for .short
    {
        auto out = assemble("STOP\n.word 0x1234\n");
        CHECK_EQ(out[1], 0x1234, ".word is alias for .short");
    }

    // .int 0xDEADBEEF → bytes [0xEF,0xBE,0xAD,0xDE] → words 0xBEEF, 0xDEAD
    {
        auto out = assemble("STOP\n.int 0xDEADBEEF\n");
        CHECK_EQ(out[1], 0xBEEF, ".int low word");
        CHECK_EQ(out[2], 0xDEAD, ".int high word");
    }

    // .long 0x0102030405060708 → 4 words LE
    // bytes: [08,07,06,05,04,03,02,01]
    // words: 0x0708, 0x0506, 0x0304, 0x0102
    {
        auto out = assemble("STOP\n.long 0x0102030405060708\n");
        CHECK_EQ(out[1], 0x0708, ".long word[0]");
        CHECK_EQ(out[2], 0x0506, ".long word[1]");
        CHECK_EQ(out[3], 0x0304, ".long word[2]");
        CHECK_EQ(out[4], 0x0102, ".long word[3]");
    }

    // Odd .byte followed by .short: auto-pads to 2-byte align
    // data bytes: [0x12, 0x00(pad), 0xCD, 0xAB]
    // words: 0x0012, 0xABCD
    {
        auto out = assemble("STOP\n.byte 0x12\n.short 0xABCD\n");
        CHECK_EQ(out[1], 0x0012, ".byte + .short: pad word");
        CHECK_EQ(out[2], 0xABCD, ".byte + .short: data word");
    }
}

// ---------------------------------------------------------------------------
// Group G2 — Mixed code+data (THE MOTIVATING TEST)
// FAILS on old assembler (data-after-instructions layout).
// PASSES after rework (interleaved layout).
// ---------------------------------------------------------------------------

static void test_mixed_code_data() {
    // .short comes before STOP in source; must appear before STOP in binary.
    {
        auto out = assemble(".org 0\n    .short 0xABCD\n    STOP\n");
        CHECK_EQ(out[0], 0xABCD, "mixed: .short before STOP → output[0]");
        CHECK_EQ(out[1], 0xFF00, "mixed: STOP after .short → output[1]");
    }

    // Data then instruction then data
    {
        auto out = assemble(".org 0\n    .short 0x0001\n    STOP\n    .short 0x0002\n");
        CHECK_EQ(out[0], 0x0001, "mixed: first .short");
        CHECK_EQ(out[1], 0xFF00, "mixed: STOP in middle");
        CHECK_EQ(out[2], 0x0002, "mixed: second .short");
    }
}

// ---------------------------------------------------------------------------
// Group H — Error cases (must all throw std::runtime_error)
// ---------------------------------------------------------------------------

static void test_error_cases() {
    CHECK_THROWS(assemble("LOAD @missing, R0"), "undefined label");
    CHECK_THROWS(assemble("foo:\nfoo:\n    STOP\n"), "duplicate label");
    CHECK_THROWS(assemble("LDI #256, R0"), "immediate out of range (>255)");
    CHECK_THROWS(assemble("BOGUS R1, R2"), "unknown mnemonic");
    CHECK_THROWS(assemble(".byte"), "bare .byte with no value");
    CHECK_THROWS(assemble(".org"), "bare .org with no address");
    CHECK_THROWS(assemble(".short"), "bare .short with no value");
    CHECK_THROWS(assemble(".int"), "bare .int with no value");
    CHECK_THROWS(assemble(".long"), "bare .long with no value");
    CHECK_THROWS(assemble("LOAD [R1+3], R0"), "offset not in {0,2,4,6}");

    // PC-relative out of range: label 33 instruction-units ahead (> 31 max)
    {
        std::string src = ".org 0\n    LOAD @far, R1\n";
        for (int i = 0; i < 33; i++) src += "    STOP\n";
        src += "far:\n    STOP\n";
        CHECK_THROWS(assemble(src), "PC-relative out of range (+33)");
    }

    // PC-relative out of range: label 33 units behind (< -32 min)
    {
        std::string src = ".org 0\nfar:\n";
        for (int i = 0; i < 33; i++) src += "    STOP\n";
        src += "    LOAD @far, R1\n";
        CHECK_THROWS(assemble(src), "PC-relative out of range (-34)");
    }
}

// ---------------------------------------------------------------------------
// Group I — .org addressing and label resolution
//
// NOTE: in the current (pre-rework) assembler, pass2's instruction phase
// always starts current_address from origin=0, regardless of .org value.
// This means non-zero .org with PC-relative instructions produces wrong
// (and often out-of-range) offsets. Tests here only use .org 0.
// After the rework (which uses instr.address from pass1), non-zero .org
// works correctly; see the post-rework tests below (currently commented out).
// ---------------------------------------------------------------------------

static void test_org_addressing() {
    // .org 0 (explicit) works identically to no .org
    {
        auto out = assemble(".org 0\n    STOP\n");
        CHECK_EQ(out[0], 0xFF00, ".org 0 + STOP");
    }

    // .org 0: forward label — same arithmetic as Group D
    // LOAD @target at addr=0, target at addr=6, pc_rel=+2 → 0x4021
    {
        auto out = assemble(".org 0\n    LOAD @target, R1\n    STOP\n    STOP\ntarget:\n    STOP\n");
        CHECK_EQ(out[0], 0x4021, ".org 0 forward label pc_rel=+2");
    }

    // .org 0: backward label — same arithmetic as Group D
    // LOAD @target at addr=4, target at addr=0, pc_rel=-3 → 0x43D1
    {
        auto out = assemble(".org 0\ntarget:\n    STOP\n    STOP\n    LOAD @target, R1\n");
        CHECK_EQ(out[2], 0x43D1, ".org 0 backward label pc_rel=-3");
    }

    // Post-rework: non-zero .org with PC-relative
    // Enabled after the assembler uses instr.address (pass1 value) in pass2.
    // .org 0x0100; LOAD @target; STOP; STOP; target: STOP
    // instr_addr=0x0100 (pass1), target=0x0106, byte_diff=4, pc_rel=2 → 0x4021
    // {
    //     auto out = assemble(".org 0x0100\n    LOAD @target, R1\n    STOP\n    STOP\ntarget:\n    STOP\n");
    //     CHECK_EQ(out[0], 0x4021, ".org 0x0100 forward label pc_rel=+2");
    // }
}

// ---------------------------------------------------------------------------
// Group J — .ascii and .asciiz string directives
// Added after the lexer/assembler rework.
// ---------------------------------------------------------------------------

static void test_ascii_directives() {
    // .ascii "AB" after STOP:
    // bytes: ['A'=0x41, 'B'=0x42] → LE word: 0x41|(0x42<<8) = 0x4241
    {
        auto out = assemble("STOP\n.ascii \"AB\"\n");
        CHECK_EQ(out[0], 0xFF00, ".ascii: instruction");
        CHECK_EQ(out[1], 0x4241, ".ascii \"AB\" → LE word 0x4241");
    }

    // .asciiz "hi" after STOP:
    // bytes: ['h'=0x68, 'i'=0x69, 0x00, 0x00(pad)]
    // words: 0x6968, 0x0000
    {
        auto out = assemble("STOP\n.asciiz \"hi\"\n");
        CHECK_EQ(out[1], 0x6968, ".asciiz \"hi\" word[0] = 0x6968");
        CHECK_EQ(out[2], 0x0000, ".asciiz \"hi\" word[1] = 0x0000 (null+pad)");
    }

    // Empty .ascii "" → no data bytes emitted
    {
        auto out = assemble("STOP\n.ascii \"\"\n");
        CHECK_EQ((int)out.size(), 1, "empty .ascii emits no data words");
    }

    // .asciiz "" → just a null byte → padded to one word: 0x0000
    {
        auto out = assemble("STOP\n.asciiz \"\"\n");
        CHECK_EQ(out[1], 0x0000, ".asciiz \"\" → one null-padded word");
    }

    // Escape sequences in .ascii
    // .ascii "A\nB": 'A'=0x41, '\n'=0x0A, 'B'=0x42
    // bytes: [0x41, 0x0A, 0x42, 0x00(pad)]
    // words: 0x0A41, 0x0042
    {
        auto out = assemble("STOP\n.ascii \"A\\nB\"\n");
        CHECK_EQ(out[1], 0x0A41, ".ascii escape \\n: word[0]");
        CHECK_EQ(out[2], 0x0042, ".ascii escape \\n: word[1]");
    }

    // Mixed: .asciiz label followed by instruction
    // .org 0; LOAD @msg, R1; msg: .asciiz "X"
    // msg_addr=2 (LOAD is at 0). byte_diff=2-(0+2)=0, pc_rel=0
    // LOAD op=0, pc_rel=0, rd=1: 0x4001
    {
        auto out = assemble(".org 0\n    LOAD @msg, R1\nmsg:\n    .asciiz \"X\"\n");
        CHECK_EQ(out[0], 0x4001, "LOAD @msg: msg is 2 bytes ahead, pc_rel=0");
        // 'X'=0x58, null=0x00 → word 0x0058
        CHECK_EQ(out[1], 0x0058, ".asciiz \"X\" after LOAD");
    }

    // Unterminated string must throw
    CHECK_THROWS(assemble("STOP\n.ascii \"unterminated\n"), "unterminated string literal");
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

int main() {
    std::printf("=== Little-64 assembler tests ===\n\n");

    std::printf("A: LDI encoding\n");
    test_ldi_encoding();

    std::printf("B: GP encoding\n");
    test_gp_encoding();

    std::printf("C: LS_REG encoding\n");
    test_ls_reg_encoding();

    std::printf("D: LS_PCREL encoding\n");
    test_ls_pcrel_encoding();

    std::printf("E: JUMP pseudo\n");
    test_jump_pseudo();

    std::printf("F: Conditional jumps\n");
    test_conditional_jumps();

    std::printf("G: Data directives (code-then-data)\n");
    test_data_directives();

    std::printf("G2: Mixed code+data (FAILS pre-rework)\n");
    test_mixed_code_data();

    std::printf("H: Error cases\n");
    test_error_cases();

    std::printf("I: .org addressing\n");
    test_org_addressing();

    std::printf("J: .ascii / .asciiz\n");
    test_ascii_directives();

    std::printf("\n=== Results: %d passed, %d failed ===\n", _pass, _fail);
    return _fail != 0 ? 1 : 0;
}
