#include "assembler.hpp"
#include "encoder.hpp"
#include <sstream>
#include <iomanip>

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

        // Label definition
        if (tok.kind == TokenKind::Ident && idx + 1 < tokens.size() &&
            tokens[idx + 1].kind == TokenKind::Colon) {
            std::string label = tok.lexeme;
            if (symbols.find(label) != symbols.end())
                throw std::runtime_error("Duplicate label: " + label + " at line " +
                                         std::to_string(tok.line));
            symbols[label] = current_address;
            idx += 2;
            continue;
        }

        // Directive
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
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile)
                idx++;
            if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
                idx++;
                line_count++;
            }
            continue;
        }

        // Instruction
        int line_at_start = line_count;
        ParsedInstruction parsed = parseInstruction(tokens, idx, current_address, line_count);
        parsed.line = line_at_start;
        instructions.push_back(parsed);
        current_address += 2;

        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile)
            idx++;
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
        output.push_back(encodeInstruction(instr, symbols, current_address));
        current_address += 2;
    }

    // Emit .word directives
    size_t idx = 0;
    int line_count = 0;
    current_address = origin;

    while (idx < tokens.size()) {
        const Token& tok = tokens[idx];

        if (tok.kind == TokenKind::EndOfFile) break;
        if (tok.kind == TokenKind::Newline) { idx++; line_count++; continue; }

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
                    output.push_back(tokens[idx].int_value & 0xFFFF);
                    current_address += 2;
                    idx++;
                }
            }
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile)
                idx++;
            if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
                idx++;
                line_count++;
            }
            continue;
        }

        // Skip over instruction tokens (already processed)
        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile)
            idx++;
        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
            idx++;
            line_count++;
        }
        current_address += 2;
    }
}

// Helper: check if mnemonic is JUMP or a JUMP.* variant
static bool isJumpMnemonic(const std::string& m) {
    return m == "JUMP" ||
           m == "JUMP.Z" || m == "JUMP.C" || m == "JUMP.S" || m == "JUMP.GT" || m == "JUMP.LT";
}

Assembler::ParsedInstruction Assembler::parseInstruction(const std::vector<Token>& tokens,
                                                          size_t& idx, uint16_t address,
                                                          int& line_count) {
    ParsedInstruction result;
    result.address = address;
    result.line = line_count;

    if (idx >= tokens.size() || tokens[idx].kind != TokenKind::Ident)
        throw std::runtime_error("Expected mnemonic at line " + std::to_string(line_count));

    std::string full_mnemonic = tokens[idx].lexeme;
    idx++;

    // Strip .SN suffix from LDI (e.g. LDI.S2 → base="LDI", shift=2)
    result.shift = 0;
    std::string base_mnemonic = full_mnemonic;
    size_t dot_pos = full_mnemonic.rfind('.');
    if (dot_pos != std::string::npos && dot_pos + 2 == full_mnemonic.length()) {
        char after_dot = full_mnemonic[dot_pos + 1];
        if (after_dot == 'S' || after_dot == 's') {
            // .S with no digit — not a shift suffix, keep as-is (e.g. JUMP.S)
        } else if (after_dot >= '0' && after_dot <= '3') {
            result.shift = after_dot - '0';
            base_mnemonic = full_mnemonic.substr(0, dot_pos);
        }
    } else if (dot_pos != std::string::npos && dot_pos + 3 == full_mnemonic.length()) {
        // Could be .S0-.S3
        if ((full_mnemonic[dot_pos + 1] == 'S' || full_mnemonic[dot_pos + 1] == 's') &&
            full_mnemonic[dot_pos + 2] >= '0' && full_mnemonic[dot_pos + 2] <= '3') {
            result.shift = full_mnemonic[dot_pos + 2] - '0';
            base_mnemonic = full_mnemonic.substr(0, dot_pos);
        }
    }

    result.mnemonic = base_mnemonic;

    // Stage 1: classify by mnemonic
    if (Encoder::isLDIMnemonic(base_mnemonic)) {
        // Format 10 (LDI): #imm8, Rd
        result.detected_format = Format::LDI;
        // Collect operands
        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile) {
            if (tokens[idx].kind != TokenKind::Comma)
                result.operands.push_back(tokens[idx]);
            idx++;
        }
        return result;
    }

    if (Encoder::isGPMnemonic(base_mnemonic)) {
        result.detected_format = Format::GP;
        uint8_t nregs = Encoder::getGPNumRegs(base_mnemonic);

        if (nregs == 0) {
            // No register operands — consume nothing (any trailing tokens are an error)
        } else if (nregs == 1) {
            // Rd only
            if (idx >= tokens.size() || tokens[idx].kind == TokenKind::Newline ||
                tokens[idx].kind == TokenKind::EndOfFile)
                throw std::runtime_error(base_mnemonic + " requires Rd at line " +
                                         std::to_string(line_count));
            if (tokens[idx].kind != TokenKind::Register)
                throw std::runtime_error("Expected register for Rd at line " +
                                         std::to_string(line_count));
            result.operands.push_back(tokens[idx++]);  // Rd
        } else {
            // Rs1, Rd
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile) {
                if (tokens[idx].kind != TokenKind::Comma)
                    result.operands.push_back(tokens[idx]);
                idx++;
            }
        }
        return result;
    }

    if (!Encoder::isLSMnemonic(base_mnemonic) && !isJumpMnemonic(base_mnemonic))
        throw std::runtime_error("Unknown mnemonic: " + base_mnemonic + " at line " +
                                 std::to_string(line_count));

    // Stage 2: LS mnemonic — sub-format from first operand token
    // Skip whitespace-level: just peek at the next meaningful token
    if (idx >= tokens.size() || tokens[idx].kind == TokenKind::Newline ||
        tokens[idx].kind == TokenKind::EndOfFile)
        throw std::runtime_error("Expected operands for " + base_mnemonic + " at line " +
                                 std::to_string(line_count));

    TokenKind first_kind = tokens[idx].kind;

    if (first_kind == TokenKind::LeftBracket) {
        // Format 00 (LS Register): [Rs1] or [Rs1+N]
        result.detected_format = Format::LS_REG;
        // Parse: [ Rs1 (+ N)? ] , Rd
        // Store the bracket contents as operands for encodeInstruction to interpret
        // We collect: Rs1 token, optionally the offset token, then Rd token
        idx++;  // consume '['
        if (idx >= tokens.size() || tokens[idx].kind != TokenKind::Register)
            throw std::runtime_error("Expected register after '[' at line " +
                                     std::to_string(line_count));
        result.operands.push_back(tokens[idx++]);  // Rs1

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Plus) {
            idx++;  // consume '+'
            if (idx >= tokens.size() || tokens[idx].kind != TokenKind::ImmediateAbs)
                throw std::runtime_error("Expected offset after '+' at line " +
                                         std::to_string(line_count));
            result.operands.push_back(tokens[idx++]);  // offset (in bytes)
        } else {
            // No offset: push a synthetic zero token
            Token zero;
            zero.kind = TokenKind::ImmediateAbs;
            zero.lexeme = "0";
            zero.int_value = 0;
            zero.line = line_count;
            result.operands.push_back(zero);
        }

        if (idx >= tokens.size() || tokens[idx].kind != TokenKind::RightBracket)
            throw std::runtime_error("Expected ']' at line " + std::to_string(line_count));
        idx++;  // consume ']'

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx >= tokens.size() || tokens[idx].kind != TokenKind::Register)
            throw std::runtime_error("Expected destination register at line " +
                                     std::to_string(line_count));
        result.operands.push_back(tokens[idx++]);  // Rd
        return result;
    }

    if (first_kind == TokenKind::PCRelLabel || first_kind == TokenKind::PCRelOffset) {
        // Format 01 (LS PC-Relative): @label/offset , Rd (Rd defaults to R15 for JUMP.*)
        result.detected_format = Format::LS_PCREL;
        result.operands.push_back(tokens[idx++]);  // @label or @offset

        // Optional comma and Rd
        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Register) {
            result.operands.push_back(tokens[idx++]);  // explicit Rd
        } else if (isJumpMnemonic(base_mnemonic)) {
            // JUMP.* with no explicit Rd: infer R15 (PC)
            Token r15;
            r15.kind = TokenKind::Register;
            r15.lexeme = "R15";
            r15.int_value = 15;
            r15.line = line_count;
            result.operands.push_back(r15);
        } else {
            throw std::runtime_error("Expected destination register at line " +
                                     std::to_string(line_count));
        }
        return result;
    }

    if (first_kind == TokenKind::Register && isJumpMnemonic(base_mnemonic)) {
        // Bare register form for JUMP.*: Rs1 (Rd=R15) or Rs1, Rd
        result.detected_format = Format::LS_REG;
        Token rs1_tok = tokens[idx++];  // Rs1

        // Build synthetic operands: Rs1, zero_offset, Rd
        result.operands.push_back(rs1_tok);

        Token zero;
        zero.kind = TokenKind::ImmediateAbs;
        zero.lexeme = "0";
        zero.int_value = 0;
        zero.line = line_count;
        result.operands.push_back(zero);

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Register) {
            result.operands.push_back(tokens[idx++]);  // explicit Rd
        } else {
            // Infer R15
            Token r15;
            r15.kind = TokenKind::Register;
            r15.lexeme = "R15";
            r15.int_value = 15;
            r15.line = line_count;
            result.operands.push_back(r15);
        }
        return result;
    }

    throw std::runtime_error("Unexpected operand syntax for " + base_mnemonic + " at line " +
                             std::to_string(line_count));
}

uint16_t Assembler::encodeInstruction(const ParsedInstruction& instr,
                                      const SymbolTable& symbols,
                                      uint16_t current_address) {
    auto err = [&](const std::string& msg) {
        throw std::runtime_error(msg + " at line " + std::to_string(instr.line));
    };

    switch (instr.detected_format) {
        case Format::LDI: {
            if (instr.operands.size() < 2) err("LDI requires #imm8, Rd");
            if (instr.operands[0].kind != TokenKind::ImmediateAbs) err("Expected #immediate");
            uint32_t val = instr.operands[0].int_value;
            if (val > 255) err("Immediate value out of range for LDI (max 255)");
            if (instr.operands[1].kind != TokenKind::Register) err("Expected register");
            uint8_t rd = instr.operands[1].int_value;
            return Encoder::encodeLDI(instr.shift, (uint8_t)val, rd);
        }

        case Format::GP: {
            uint8_t opcode = Encoder::getGPOpcode(instr.mnemonic);
            uint8_t nregs  = Encoder::getGPNumRegs(instr.mnemonic);
            uint8_t rs1 = 0, rd = 0;

            if (nregs == 0) {
                if (!instr.operands.empty()) err(instr.mnemonic + " takes no operands");
            } else if (nregs == 1) {
                if (instr.operands.size() < 1) err(instr.mnemonic + " requires Rd");
                if (instr.operands[0].kind != TokenKind::Register) err("Expected register for Rd");
                rd = instr.operands[0].int_value;
            } else {
                if (instr.operands.size() < 2) err(instr.mnemonic + " requires Rs1, Rd");
                if (instr.operands[0].kind != TokenKind::Register) err("Expected register for Rs1");
                if (instr.operands[1].kind != TokenKind::Register) err("Expected register for Rd");
                rs1 = instr.operands[0].int_value;
                rd  = instr.operands[1].int_value;
            }
            return Encoder::encodeGP(opcode, rs1, rd);
        }

        case Format::LS_REG: {
            // operands: [Rs1, offset_bytes, Rd]
            if (instr.operands.size() < 3) err(instr.mnemonic + " requires [Rs1+N], Rd");
            if (instr.operands[0].kind != TokenKind::Register) err("Expected register for Rs1");
            if (instr.operands[1].kind != TokenKind::ImmediateAbs) err("Expected byte offset");
            if (instr.operands[2].kind != TokenKind::Register) err("Expected register for Rd");

            uint8_t rs1 = instr.operands[0].int_value;
            uint32_t byte_offset = instr.operands[1].int_value;
            uint8_t rd  = instr.operands[2].int_value;

            if (byte_offset != 0 && byte_offset != 2 && byte_offset != 4 && byte_offset != 6)
                err("Offset must be 0, 2, 4, or 6 bytes");
            uint8_t offset2 = byte_offset / 2;

            // JUMP is a pseudo-instruction aliased to MOVE
            const std::string& ls_mnemonic = (instr.mnemonic == "JUMP") ? "MOVE" : instr.mnemonic;
            uint8_t opcode = Encoder::getLSOpcode(ls_mnemonic);
            return Encoder::encodeLSReg(opcode, offset2, rs1, rd);
        }

        case Format::LS_PCREL: {
            // operands: [@label_or_offset, Rd]
            if (instr.operands.size() < 2) err(instr.mnemonic + " requires @label, Rd");
            if (instr.operands[1].kind != TokenKind::Register) err("Expected register for Rd");

            uint8_t rd = instr.operands[1].int_value;
            int32_t raw_offset = 0;

            const Token& addr_tok = instr.operands[0];
            if (addr_tok.kind == TokenKind::PCRelLabel) {
                auto it = symbols.find(addr_tok.lexeme);
                if (it == symbols.end())
                    err("Undefined label: " + addr_tok.lexeme);
                uint16_t target = it->second;
                // pc_rel is in instruction units (×2 bytes), relative to next instruction
                int32_t byte_diff = (int32_t)target - (int32_t)(current_address + 2);
                if (byte_diff % 2 != 0) err("Target address is not instruction-aligned");
                raw_offset = byte_diff / 2;
            } else if (addr_tok.kind == TokenKind::PCRelOffset) {
                raw_offset = (int32_t)(int64_t)addr_tok.int_value;
            } else {
                err("Expected @label or @offset");
            }

            if (raw_offset < -32 || raw_offset > 31)
                err("PC-relative offset out of range [-32, 31]");

            // JUMP is a pseudo-instruction aliased to MOVE
            const std::string& ls_mnemonic = (instr.mnemonic == "JUMP") ? "MOVE" : instr.mnemonic;
            uint8_t opcode = Encoder::getLSOpcode(ls_mnemonic);
            return Encoder::encodeLSPCRel(opcode, (int8_t)raw_offset, rd);
        }
    }

    // Unreachable
    err("Internal assembler error");
    return 0;
}

std::string Assembler::getListing() const {
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (const auto& instr : instructions) {
        oss << "0x" << std::setw(4) << instr.address << "  " << instr.mnemonic << "\n";
    }
    return oss.str();
}
