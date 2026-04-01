#pragma once
#include <cstdint>

// ---- GP operand encoding kinds (4th column in opcodes_gp.def) ----
namespace GP {
    enum class Encoding : uint8_t {
        NONE    = 0,  // no operands           (IRET, STOP)
        RD      = 1,  // Rd only, Rs1 zeroed   (reserved for future use)
        RS1_RD  = 2,  // Rs1 register + Rd     (ADD, SLL, …)
        IMM4_RD = 3,  // 4-bit imm in Rs1 + Rd (SLLI, SRLI, SRAI)
    };
}

// ---- GP opcodes (5-bit, format 110: bits[15:13]=110) ----
namespace GP {
    enum class Opcode : uint8_t {
#define LITTLE64_GP_OPCODE(name, value, mnemonic, num_regs) name = value,
#include "opcodes_gp.def"
#undef LITTLE64_GP_OPCODE
    };
}

// ---- LS opcodes (4-bit, formats 00 and 01: bits[15:14]=00 or 01) ----
namespace LS {
    enum class Opcode : uint8_t {
#define LITTLE64_LS_OPCODE(name, value, mnemonic) name = value,
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE
    };
}
