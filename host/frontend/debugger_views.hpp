#pragma once

#include "../disassembler/disassembler.hpp"
#include "../emulator/frontend_api.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

struct DebugRegisterRow {
    std::string name;
    uint64_t value = 0;
    bool muted = false;
};

struct DebugDisassemblyRow {
    uint64_t address = 0;
    uint16_t raw = 0;
    std::string text;
    bool is_pc = false;
};

struct DebugMemoryRow {
    uint64_t address = 0;
    std::string hex_bytes;
    std::string ascii;
    bool contains_pc = false;
};

struct DebugRegionRow {
    std::string name;
    uint64_t base = 0;
    uint64_t size = 0;
    uint64_t end_inclusive = 0;
    std::string type;
};

inline std::vector<DebugRegisterRow> buildRegisterRows(const RegisterSnapshot& regs, uint64_t pc) {
    std::vector<DebugRegisterRow> rows;
    rows.reserve(29);

    for (int i = 0; i < 16; ++i) {
        DebugRegisterRow row;
        switch (i) {
            case 13: row.name = "SP"; break;
            case 14: row.name = "LR"; break;
            case 15: row.name = "PC"; break;
            default: row.name = "R" + std::to_string(i); break;
        }
        row.value = regs.gpr[i];
        row.muted = (i == 0);
        rows.push_back(std::move(row));
    }

    rows.push_back({"PC", pc, false});
    rows.push_back({"FLAGS", regs.flags, false});

    rows.push_back({"cpu_ctrl", regs.cpu_control, false});
    rows.push_back({"int_table", regs.interrupt_table_base, false});
    rows.push_back({"int_mask", regs.interrupt_mask, false});
    rows.push_back({"int_state", regs.interrupt_states, false});
    rows.push_back({"int_epc", regs.interrupt_epc, false});
    rows.push_back({"int_eflg", regs.interrupt_eflags, false});
    rows.push_back({"trap_cau", regs.trap_cause, false});
    rows.push_back({"trap_vadr", regs.trap_fault_addr, false});
    rows.push_back({"trap_acc", regs.trap_access, false});
    rows.push_back({"trap_pc", regs.trap_pc, false});
    rows.push_back({"trap_aux", regs.trap_aux, false});

    return rows;
}

inline std::vector<DebugDisassemblyRow>
buildDisassemblyRowsFromCache(const std::vector<DisassembledInstruction>& instructions, uint64_t pc) {
    std::vector<DebugDisassemblyRow> rows;
    rows.reserve(instructions.size());
    for (const auto& instr : instructions) {
        rows.push_back({instr.address, instr.raw, instr.text, instr.address == pc});
    }
    return rows;
}

inline std::vector<DebugDisassemblyRow>
buildDisassemblyWindowRows(IEmulatorRuntime& runtime,
                           uint64_t center_pc,
                           int row_count = 96,
                           uint64_t leading_bytes = 64) {
    const uint64_t base = center_pc >= leading_bytes ? (center_pc - leading_bytes) : 0;

    std::vector<DebugDisassemblyRow> rows;
    rows.reserve(std::max(0, row_count));
    for (int row = 0; row < row_count; ++row) {
        const uint64_t addr = base + static_cast<uint64_t>(row * 2);
        const uint16_t lo = runtime.memoryRead8(addr);
        const uint16_t hi = runtime.memoryRead8(addr + 1);
        const uint16_t word = static_cast<uint16_t>(lo | (hi << 8));
        const auto dis = Disassembler::disassemble(word, static_cast<uint16_t>(addr & 0xFFFF));
        rows.push_back({addr, word, dis.text, addr == center_pc});
    }
    return rows;
}

inline std::vector<DebugMemoryRow>
buildMemoryRows(IEmulatorRuntime& runtime,
                uint64_t start,
                int row_count,
                int bytes_per_row,
                uint64_t pc) {
    std::vector<DebugMemoryRow> rows;
    rows.reserve(std::max(0, row_count));

    for (int row = 0; row < row_count; ++row) {
        DebugMemoryRow out;
        out.address = start + static_cast<uint64_t>(row) * static_cast<uint64_t>(bytes_per_row);

        char hex_buf[3 * 64 + 8]{};
        int hex_off = 0;

        out.ascii.reserve(bytes_per_row);
        for (int i = 0; i < bytes_per_row; ++i) {
            const uint64_t addr = out.address + static_cast<uint64_t>(i);
            const uint8_t value = runtime.memoryRead8(addr);
            hex_off += std::snprintf(hex_buf + hex_off,
                                     static_cast<size_t>(std::max(0, (int)sizeof(hex_buf) - hex_off)),
                                     "%02X ", value);
            out.ascii.push_back(std::isprint(value) ? static_cast<char>(value) : '.');
        }

        out.hex_bytes = std::string(hex_buf);
        if (!out.hex_bytes.empty() && out.hex_bytes.back() == ' ') {
            out.hex_bytes.pop_back();
        }
        out.contains_pc = (pc >= out.address && pc < out.address + static_cast<uint64_t>(bytes_per_row));
        rows.push_back(std::move(out));
    }

    return rows;
}

inline std::vector<DebugRegionRow> buildRegionRows(const std::vector<MemoryRegionView>& regions) {
    std::vector<DebugRegionRow> rows;
    rows.reserve(regions.size());

    for (const auto& r : regions) {
        DebugRegionRow row;
        row.name = r.name;
        row.base = r.base;
        row.size = r.size;
        row.end_inclusive = r.size > 0 ? (r.base + r.size - 1) : r.base;

        if (r.name == "ROM") row.type = "ROM";
        else if (r.name == "RAM") row.type = "RAM";
        else row.type = "MMIO";

        rows.push_back(std::move(row));
    }

    return rows;
}

inline bool drainSerialToBuffer(IEmulatorRuntime& runtime, std::string& buffer) {
    const std::string drained = runtime.drainSerialTx();
    if (drained.empty()) return false;
    buffer += drained;
    return true;
}
