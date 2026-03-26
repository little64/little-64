#pragma once
#include <cstdint>

// ---- Type 0 opcodes (4-bit, type=0, encoding selected by operand type) ----
namespace T0 {
    enum class Opcode : uint8_t {
#define LITTLE64_T0_OPCODE(name, value, mnemonic) name = value,
#include "opcodes_t0.def"
#undef LITTLE64_T0_OPCODE
    };
}

// ---- Type 1 opcodes (2-bit, type=1: load/store) ----
namespace LS {
    enum class Opcode : uint8_t {
#define LITTLE64_LS_OPCODE(name, value, mnemonic) name = value,
#include "opcodes_ls.def"
#undef LITTLE64_LS_OPCODE
    };
}
