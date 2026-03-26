#pragma once
#include <cstdint>

// ---- GP opcodes (6-bit, format 11: bits[15:14]=11) ----
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
