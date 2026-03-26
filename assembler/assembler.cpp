#include "assembler.hpp"
#include "encoder.hpp"
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cctype>
#include <cmath>

std::vector<uint16_t> Assembler::assemble(const std::string& source) {
    Encoder::init();
    instructions.clear();

    Lexer lexer;
    std::vector<Token> tokens = lexer.tokenize(source);

    SymbolTable symbols;
    pass1(tokens, symbols);

    std::vector<uint16_t> output;
    pass2(tokens, symbols, output);

    return output;
}

void Assembler::pass1(const std::vector<Token>& tokens, SymbolTable& symbols) {
    uint16_t current_address = origin;
    size_t idx = 0;
    int line_count = 0;

    while (idx < tokens.size()) {
        const Token& tok = tokens[idx];

        if (tok.kind == TokenKind::EndOfFile) break;
        if (tok.kind == TokenKind::Newline) {
            idx++;
            line_count++;
            continue;
        }

        // Check for label definition
        if (tok.kind == TokenKind::Ident && idx + 1 < tokens.size() &&
            tokens[idx + 1].kind == TokenKind::Colon) {
            std::string label = tok.lexeme;
            if (symbols.find(label) != symbols.end()) {
                throw std::runtime_error("Duplicate label: " + label + " at line " +
                                       std::to_string(tok.line));
            }
            symbols[label] = current_address;
            idx += 2;  // skip label and colon
            continue;
        }

        // Check for directive
        if (tok.kind == TokenKind::Ident && tok.lexeme[0] == '.') {
            if (tok.lexeme == ".org") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    current_address = tokens[idx].int_value;
                    idx++;
                } else {
                    throw std::runtime_error(".org requires an address at line " +
                                           std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".word") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    current_address += 2;
                    idx++;
                } else {
                    throw std::runtime_error(".word requires a value at line " +
                                           std::to_string(tok.line));
                }
            } else {
                throw std::runtime_error("Unknown directive: " + tok.lexeme + " at line " +
                                       std::to_string(tok.line));
            }
            // Skip to next line
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile) {
                idx++;
            }
            if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
                idx++;
                line_count++;
            }
            continue;
        }

        // It's an instruction
        int line_at_start = line_count;
        ParsedInstruction parsed =
            parseInstruction(tokens, idx, current_address, line_count);
        parsed.line = line_at_start;
        instructions.push_back(parsed);
        current_address += 2;

        // Skip to next line
        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile) {
            idx++;
        }
        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
            idx++;
            line_count++;
        }
    }
}

void Assembler::pass2(const std::vector<Token>& tokens, const SymbolTable& symbols,
                      std::vector<uint16_t>& output) {
    uint16_t current_address = origin;

    for (const auto& instr : instructions) {
        uint16_t encoded = encodeInstruction(instr, symbols, current_address);
        output.push_back(encoded);
        current_address += 2;
    }

    // Also handle .word directives from the token stream
    size_t idx = 0;
    int line_count = 0;
    current_address = origin;

    while (idx < tokens.size()) {
        const Token& tok = tokens[idx];

        if (tok.kind == TokenKind::EndOfFile) break;
        if (tok.kind == TokenKind::Newline) {
            idx++;
            line_count++;
            continue;
        }

        if (tok.kind == TokenKind::Ident && idx + 1 < tokens.size() &&
            tokens[idx + 1].kind == TokenKind::Colon) {
            idx += 2;
            continue;
        }

        if (tok.kind == TokenKind::Ident && tok.lexeme[0] == '.') {
            if (tok.lexeme == ".org") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    current_address = tokens[idx].int_value;
                    idx++;
                }
            } else if (tok.lexeme == ".word") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    uint16_t value = tokens[idx].int_value & 0xFFFF;
                    output.push_back(value);
                    current_address += 2;
                    idx++;
                }
            }
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile) {
                idx++;
            }
            if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
                idx++;
                line_count++;
            }
            continue;
        }

        // Skip instruction (already processed)
        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile) {
            idx++;
        }
        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
            idx++;
            line_count++;
        }
        current_address += 2;
    }
}

Assembler::ParsedInstruction Assembler::parseInstruction(const std::vector<Token>& tokens,
                                                         size_t& idx, uint16_t address,
                                                         int& line_count) {
    ParsedInstruction result;
    result.address = address;
    result.line = line_count;

    // Parse mnemonic (may include suffix like .S1 or [BW])
    if (idx >= tokens.size() || tokens[idx].kind != TokenKind::Ident) {
        throw std::runtime_error("Expected mnemonic");
    }

    std::string full_mnemonic = tokens[idx].lexeme;
    idx++;

    // Parse mnemonic suffixes
    // The full_mnemonic may contain .SN or [mask] suffix(es)
    result.mnemonic = full_mnemonic;
    result.shift_or_mask = 0;
    result.is_mask = false;

    // Look for [mask] first (appears after base mnemonic)
    size_t bracket_pos = result.mnemonic.find('[');
    if (bracket_pos != std::string::npos) {
        size_t close_bracket = result.mnemonic.find(']', bracket_pos);
        if (close_bracket != std::string::npos) {
            std::string mask_str = result.mnemonic.substr(bracket_pos + 1, close_bracket - bracket_pos - 1);
            result.is_mask = true;

            // Parse mask value
            if (mask_str == "B") {
                result.shift_or_mask = 1;  // bit 0
            } else if (mask_str == "W") {
                result.shift_or_mask = 2;  // bit 1
            } else if (mask_str == "BW") {
                result.shift_or_mask = 3;  // both bits
            } else if (mask_str == "0") {
                result.shift_or_mask = 0;
            } else {
                throw std::runtime_error("Invalid mask: " + mask_str);
            }

            result.mnemonic = result.mnemonic.substr(0, bracket_pos);
        }
    }

    // Look for .S# suffix (appears after base mnemonic, before any bracket)
    size_t dot_pos = result.mnemonic.rfind('.');
    if (dot_pos != std::string::npos && dot_pos + 2 < result.mnemonic.length()) {
        if (result.mnemonic[dot_pos + 1] == 'S' || result.mnemonic[dot_pos + 1] == 's') {
            char shift_char = result.mnemonic[dot_pos + 2];
            if (shift_char >= '0' && shift_char <= '3') {
                result.shift_or_mask = shift_char - '0';
                result.mnemonic = result.mnemonic.substr(0, dot_pos);
            }
        }
    }

    // Collect operands until end of line
    while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
           tokens[idx].kind != TokenKind::EndOfFile) {
        if (tokens[idx].kind == TokenKind::Comma) {
            idx++;
            continue;
        }
        result.operands.push_back(tokens[idx]);
        idx++;
    }

    return result;
}

uint16_t Assembler::encodeInstruction(const ParsedInstruction& instr,
                                      const SymbolTable& symbols,
                                      uint16_t current_address) {
    // Normalize mnemonic (remove .S suffix if present, keep base name)
    std::string base_mnemonic = instr.mnemonic;
    size_t dot_pos = base_mnemonic.find('.');
    if (dot_pos != std::string::npos) {
        base_mnemonic = base_mnemonic.substr(0, dot_pos);
    }

    // Determine whether this is a T=0 or T=1 instruction
    bool is_ls = (base_mnemonic == "LOAD" || base_mnemonic == "STORE" ||
                  base_mnemonic == "INC_LOAD" || base_mnemonic == "DEC_STORE");

    if (is_ls) {
        // T=1 instruction (load/store)
        uint8_t opcode = Encoder::getLSOpcode(base_mnemonic);

        if (instr.is_mask) {
            // Format 4: T=1, E=1 (PC-relative with mask)
            // Operands: @label/offset, Rd
            if (instr.operands.size() < 2) {
                throw std::runtime_error("Instruction requires 2 operands at line " +
                                       std::to_string(instr.line));
            }

            const Token& addr_tok = instr.operands[0];
            uint8_t pcrel = 0;

            if (addr_tok.kind == TokenKind::PCRelLabel) {
                auto it = symbols.find(addr_tok.lexeme);
                if (it == symbols.end()) {
                    throw std::runtime_error("Undefined label: " + addr_tok.lexeme +
                                           " at line " + std::to_string(instr.line));
                }
                uint16_t target = it->second;
                int32_t offset = (int32_t)target - (int32_t)(current_address + 2);
                offset >>= 1;  // PC-rel offset is word-based
                if (offset < -32 || offset > 31) {
                    throw std::runtime_error("PC-relative offset out of range at line " +
                                           std::to_string(instr.line));
                }
                pcrel = offset & 0x3F;
            } else if (addr_tok.kind == TokenKind::PCRelOffset) {
                int32_t offset = addr_tok.int_value;
                if (offset < -32 || offset > 31) {
                    throw std::runtime_error("PC-relative offset out of range at line " +
                                           std::to_string(instr.line));
                }
                pcrel = offset & 0x3F;
            } else {
                throw std::runtime_error("Expected @label or @offset at line " +
                                       std::to_string(instr.line));
            }

            uint8_t rd = 0;
            if (instr.operands[1].kind == TokenKind::Register) {
                rd = instr.operands[1].int_value;
            } else {
                throw std::runtime_error("Expected register for destination at line " +
                                       std::to_string(instr.line));
            }

            return Encoder::encodeLS_mask(opcode, instr.shift_or_mask, pcrel, rd);
        } else {
            // Format 3: T=1, E=0 (immediate with shift)
            // Operands: #imm6, Rd
            if (instr.operands.size() < 2) {
                throw std::runtime_error("Instruction requires 2 operands at line " +
                                       std::to_string(instr.line));
            }

            const Token& imm_tok = instr.operands[0];
            if (imm_tok.kind != TokenKind::ImmediateAbs) {
                throw std::runtime_error("Expected #immediate at line " +
                                       std::to_string(instr.line));
            }

            uint8_t imm6 = imm_tok.int_value & 0x3F;
            uint8_t rd = 0;
            if (instr.operands[1].kind == TokenKind::Register) {
                rd = instr.operands[1].int_value;
            } else {
                throw std::runtime_error("Expected register for destination at line " +
                                       std::to_string(instr.line));
            }

            return Encoder::encodeLS_shift(opcode, instr.shift_or_mask, imm6, rd);
        }
    } else {
        // T=0 instruction (general purpose)
        uint8_t opcode = Encoder::getT0Opcode(base_mnemonic);

        if (instr.operands.size() < 2) {
            throw std::runtime_error("Instruction requires 2 operands at line " +
                                   std::to_string(instr.line));
        }

        const Token& src_tok = instr.operands[0];
        uint8_t src_val = 0;
        bool is_register_operand = false;

        if (src_tok.kind == TokenKind::Register) {
            // E=0: register format
            src_val = src_tok.int_value;
            is_register_operand = true;
        } else if (src_tok.kind == TokenKind::PCRelLabel) {
            // E=1: PC-relative format
            auto it = symbols.find(src_tok.lexeme);
            if (it == symbols.end()) {
                throw std::runtime_error("Undefined label: " + src_tok.lexeme +
                                       " at line " + std::to_string(instr.line));
            }
            uint16_t target = it->second;
            int32_t offset = (int32_t)target - (int32_t)(current_address + 2);
            offset >>= 1;  // PC-rel offset is word-based
            if (offset < -32 || offset > 31) {
                throw std::runtime_error("PC-relative offset out of range at line " +
                                       std::to_string(instr.line));
            }
            src_val = offset & 0x3F;
            is_register_operand = false;
        } else if (src_tok.kind == TokenKind::PCRelOffset) {
            // E=1: raw PC-relative offset
            int32_t offset = src_tok.int_value;
            if (offset < -32 || offset > 31) {
                throw std::runtime_error("PC-relative offset out of range at line " +
                                       std::to_string(instr.line));
            }
            src_val = offset & 0x3F;
            is_register_operand = false;
        } else {
            throw std::runtime_error("Expected register or @label/@offset at line " +
                                   std::to_string(instr.line));
        }

        uint8_t rd = 0;
        if (instr.operands[1].kind == TokenKind::Register) {
            rd = instr.operands[1].int_value;
        } else {
            throw std::runtime_error("Expected register for destination at line " +
                                   std::to_string(instr.line));
        }

        return Encoder::encodeT0(opcode, is_register_operand, src_val, rd);
    }
}

std::string Assembler::getListing() const {
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (const auto& instr : instructions) {
        oss << "0x" << std::setw(4) << instr.address << "  ";
        // Encoding would go here, but we'd need to re-compute it
        oss << instr.mnemonic << "\n";
    }
    return oss.str();
}
