#pragma once

#include "test_harness.hpp"
#include "cpu.hpp"
#include "linker.hpp"
#include "llvm_assembler.hpp"
#include "special_register_layout.hpp"
#include <cstdint>
#include <iomanip>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t FLAG_Z = 1ULL << 0;
static constexpr uint64_t FLAG_C = 1ULL << 1;
static constexpr uint64_t FLAG_S = 1ULL << 2;

static constexpr uint64_t ROM_SIZE = 4096;
static constexpr uint64_t RAM_BASE = ROM_SIZE;

[[maybe_unused]] static uint16_t encode_ls_reg(uint8_t opcode, uint8_t offset2, uint8_t rs1, uint8_t rd) {
    return static_cast<uint16_t>((opcode << 10) | ((offset2 & 0x3) << 8) | ((rs1 & 0xF) << 4) | (rd & 0xF));
}

[[maybe_unused]] static std::string as_short(uint16_t word) {
    std::ostringstream os;
    os << ".short 0x" << std::hex << std::uppercase << std::setw(4) << std::setfill('0')
       << static_cast<unsigned>(word);
    return os.str();
}

[[maybe_unused]] static std::string preprocess_for_llvm(const std::string& src) {
    std::ostringstream out;
    std::istringstream in(src);
    std::string line;
    int ldi64_counter = 0;

    const std::regex push_re(R"(^\s*PUSH\s+R(\d+)\s*,\s*R(\d+)\s*$)", std::regex::icase);
    const std::regex pop_re(R"(^\s*POP\s+R(\d+)\s*,\s*R(\d+)\s*$)", std::regex::icase);
    const std::regex move_off_re(R"(^\s*MOVE\s+R(\d+)\s*\+\s*(\d+)\s*,\s*R(\d+)\s*$)", std::regex::icase);
    const std::regex ldi64_re(R"(^\s*LDI64\s+#?([^,\s]+)\s*,\s*R(\d+)\s*$)", std::regex::icase);
    const std::regex jal_re(R"(^\s*JAL\s+@([^\s]+)\s*$)", std::regex::icase);
    const std::regex call_re(R"(^\s*CALL\s+@([^\s]+)\s*$)", std::regex::icase);
    const std::regex ret_re(R"(^\s*RET\s*$)", std::regex::icase);

    std::smatch m;
    while (std::getline(in, line)) {
        if (std::regex_match(line, m, ldi64_re)) {
            uint64_t imm = std::stoull(m[1].str(), nullptr, 0);
            int rd = std::stoi(m[2].str());
            const std::string c_label = "__l64_const_" + std::to_string(ldi64_counter);
            const std::string e_label = "__l64_after_" + std::to_string(ldi64_counter);
            ++ldi64_counter;

            out << "LOAD @" << c_label << ", R" << rd << "\n";
            out << "JUMP @" << e_label << "\n";
            out << c_label << ":\n";
            for (int i = 0; i < 8; ++i) {
                const uint8_t b = static_cast<uint8_t>((imm >> (i * 8)) & 0xFFu);
                out << ".byte 0x" << std::hex << std::uppercase << std::setw(2) << std::setfill('0')
                    << static_cast<unsigned>(b) << std::dec << "\n";
            }
            out << e_label << ":\n";
            continue;
        }

        if (std::regex_match(line, m, push_re)) {
            const int rs = std::stoi(m[1].str());
            const int sp = std::stoi(m[2].str());
            out << as_short(encode_ls_reg(2, 0, static_cast<uint8_t>(rs), static_cast<uint8_t>(sp))) << "\n";
            continue;
        }

        if (std::regex_match(line, m, pop_re)) {
            const int rd = std::stoi(m[1].str());
            const int sp = std::stoi(m[2].str());
            out << as_short(encode_ls_reg(3, 0, static_cast<uint8_t>(rd), static_cast<uint8_t>(sp))) << "\n";
            continue;
        }

        if (std::regex_match(line, m, move_off_re)) {
            const int rs = std::stoi(m[1].str());
            const int off = std::stoi(m[2].str());
            const int rd = std::stoi(m[3].str());
            if (off >= 0 && off <= 6 && (off % 2) == 0) {
                out << as_short(encode_ls_reg(4, static_cast<uint8_t>(off / 2), static_cast<uint8_t>(rs), static_cast<uint8_t>(rd))) << "\n";
            } else {
                out << line << "\n";
            }
            continue;
        }

        if (std::regex_match(line, m, jal_re)) {
            out << as_short(encode_ls_reg(4, 1, 15, 14)) << "\n";
            out << "JUMP @" << m[1].str() << "\n";
            continue;
        }

        if (std::regex_match(line, m, call_re)) {
            out << as_short(encode_ls_reg(2, 0, 14, 13)) << "\n";
            out << as_short(encode_ls_reg(4, 1, 15, 14)) << "\n";
            out << "JUMP @" << m[1].str() << "\n";
            out << as_short(encode_ls_reg(3, 0, 14, 13)) << "\n";
            continue;
        }

        if (std::regex_match(line, ret_re)) {
            out << "MOVE R14, R15\n";
            continue;
        }

        out << line << "\n";
    }

    return out.str();
}

[[maybe_unused]] static std::vector<uint16_t> assemble_words(const std::string& src) {
    std::string asm_error;
    auto llvm_src = preprocess_for_llvm(src);
    auto obj = LLVMAssembler::assembleSourceText(llvm_src, "cpu_test.asm", asm_error);
    if (!obj) {
        throw std::runtime_error("LLVM assembly failed: " + asm_error);
    }

    LinkError link_error;
    auto words = Linker::linkObjects({*obj}, &link_error);
    if (!words) {
        throw std::runtime_error("Link failed: " + link_error.message);
    }

    return *words;
}

[[maybe_unused]] static Little64CPU::Instruction make_instr(const char* src) {
    return Little64CPU::Instruction(assemble_words(src)[0]);
}

struct ExecResult {
    uint64_t rd_value;
    uint64_t flags;
};

[[maybe_unused]] static ExecResult exec(const char* src, int rd, uint64_t initial) {
    Little64CPU cpu;
    cpu.registers.regs[rd] = initial;
    cpu.dispatchInstruction(make_instr(src));
    return { cpu.registers.regs[rd], cpu.registers.flags };
}

[[maybe_unused]] static std::string ldi_special_register_index(uint64_t special_register_id, int rd) {
    return "LDI64 #" + std::to_string(special_register_id) + ", R" + std::to_string(rd) + "\n";
}

[[maybe_unused]] static Little64CPU run_program(const std::string& src, int max_cycles = 10000) {
    auto words = assemble_words(src);
    Little64CPU cpu;
    cpu.loadProgram(words);
    for (int cycle = 0; cycle < max_cycles && cpu.isRunning; ++cycle) {
        cpu.cycle();
    }
    return cpu;
}
