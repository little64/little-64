#include "assembler.hpp"
#include "encoder.hpp"
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <functional>
#include <stdexcept>

// ---------------------------------------------------------------------------
// Synthetic token helpers — used by pseudo-instruction expanders
// ---------------------------------------------------------------------------

static Token makeRegToken(uint8_t reg, int line) {
    Token t;
    t.kind = TokenKind::Register;
    t.lexeme = "R" + std::to_string(reg);
    t.int_value = reg;
    t.line = line;
    t.column = 0;
    return t;
}

static Token makeImmToken(int32_t val, int line) {
    Token t;
    t.kind = TokenKind::ImmediateAbs;
    t.lexeme = std::to_string(val);
    t.int_value = static_cast<uint64_t>(val);
    t.line = line;
    t.column = 0;
    return t;
}

// ---------------------------------------------------------------------------
// Pseudo-instruction table
//
// To add a new pseudo-instruction, add one entry here.
//   arity  — expected number of source operands (tokens, not counting commas)
//   expand — returns a vector of Assembler::EmitItem objects in emission order;
//             each item's address is computed by pass1 based on current address
// ---------------------------------------------------------------------------

struct PseudoDef {
    int arity;
    std::function<std::vector<Assembler::EmitItem>(
        const std::vector<Token>&, uint16_t addr, int line)> expand;
};

static Assembler::EmitItem makeInstrItem(const ParsedInstruction& instr) {
    Assembler::EmitItem item;
    item.is_instruction = true;
    item.instr = instr;
    return item;
}

static Assembler::EmitItem makeDataItem(const DataDirective& data) {
    Assembler::EmitItem item;
    item.is_instruction = false;
    item.data = data;
    return item;
}

static const std::unordered_map<std::string, PseudoDef> pseudo_table = {
    // JAL @target → MOVE R15+2, R14  ;  JUMP @target
    //
    // When MOVE executes, R15 already points at the JUMP (next instr), so
    // R15+2 = address after JUMP = the return address stored in R14 (LR).
    {"JAL", {1, [](const std::vector<Token>& ops, uint16_t addr, int line) {
        ParsedInstruction move;
        move.mnemonic        = "MOVE";
        move.detected_format = Format::LS_REG;
        move.operands        = {makeRegToken(15, line), makeImmToken(2, line), makeRegToken(14, line)};
        move.line            = line;

        ParsedInstruction jump;
        jump.mnemonic        = "JUMP";
        jump.detected_format = Format::LS_PCREL;
        jump.operands        = {ops[0], makeRegToken(15, line)};
        jump.line            = line;

        return std::vector<Assembler::EmitItem>{
            makeInstrItem(move),
            makeInstrItem(jump),
        };
    }}},

    // CALL @target →
    //   PUSH R14           addr+0  save caller LR on stack
    //   MOVE R15+2, R14    addr+2  R15 points at JUMP (addr+4) → R15+2 = addr+6 = POP below
    //   JUMP @target       addr+4  jump to callee
    //   POP R14            addr+6  ← return address; restores caller LR when callee does RET
    //
    // This embeds the LR restore AT the return address, so after callee returns via
    //   RET (MOVE R14, R15), the POP R14 executes automatically and R14 is restored.
    {"CALL", {1, [](const std::vector<Token>& ops, uint16_t addr, int line) {
        ParsedInstruction push;
        push.mnemonic        = "PUSH";
        push.detected_format = Format::LS_REG;
        push.operands        = {makeRegToken(14, line), makeImmToken(0, line), makeRegToken(13, line)};
        push.line            = line;

        ParsedInstruction move;
        move.mnemonic        = "MOVE";
        move.detected_format = Format::LS_REG;
        move.operands        = {makeRegToken(15, line), makeImmToken(2, line), makeRegToken(14, line)};
        move.line            = line;

        ParsedInstruction jump;
        jump.mnemonic        = "JUMP";
        jump.detected_format = Format::LS_PCREL;
        jump.operands        = {ops[0], makeRegToken(15, line)};
        jump.line            = line;

        ParsedInstruction pop;
        pop.mnemonic        = "POP";
        pop.detected_format = Format::LS_REG;
        pop.operands        = {makeRegToken(14, line), makeImmToken(0, line), makeRegToken(13, line)};
        pop.line            = line;

        return std::vector<Assembler::EmitItem>{
            makeInstrItem(push),
            makeInstrItem(move),
            makeInstrItem(jump),
            makeInstrItem(pop),
        };
    }}},

    // LDI64 #imm64, Rd
    // Expands to:
    //   LOAD @+1, Rd   ; load value at constant location (1 instruction unit after next)
    //   JUMP @+4      ; skip the 8-byte constant and continue
    //   .long imm64
    {"LDI64", {2, [](const std::vector<Token>& ops, uint16_t addr, int line) {
        if (ops[0].kind != TokenKind::ImmediateAbs && ops[0].kind != TokenKind::Ident)
            throw std::runtime_error("LDI64 requires a 64-bit immediate value or symbol");
        if (ops[1].kind != TokenKind::Register)
            throw std::runtime_error("LDI64 requires a destination register");

        Token pcrel_val;
        pcrel_val.kind = TokenKind::PCRelOffset;
        pcrel_val.lexeme = "@+1";
        pcrel_val.int_value = 1;
        pcrel_val.line = line;

        Token pcrel_after;
        pcrel_after.kind = TokenKind::PCRelOffset;
        pcrel_after.lexeme = "@+4";
        pcrel_after.int_value = 4;
        pcrel_after.line = line;

        ParsedInstruction load;
        load.mnemonic = "LOAD";
        load.detected_format = Format::LS_PCREL;
        load.operands = {pcrel_val, ops[1]};
        load.line = line;

        ParsedInstruction jump;
        jump.mnemonic = "JUMP";
        jump.detected_format = Format::LS_PCREL;
        jump.operands = {pcrel_after, makeRegToken(15, line)};
        jump.line = line;

        DataDirective dd;
        dd.kind = DataDirective::Kind::Long;
        dd.line = line;
        if (ops[0].kind == TokenKind::Ident) {
            dd.isSymbol = true;
            dd.symbol = ops[0].lexeme;
        } else {
            dd.isSymbol = false;
            dd.value = ops[0].int_value;
        }

        return std::vector<Assembler::EmitItem>{
            makeInstrItem(load),
            makeInstrItem(jump),
            makeDataItem(dd),
        };
    }}},

    // RET → MOVE R14, R15
    //
    // Jumps to the link register (R14).  When paired with CALL, control lands on
    // the POP R14 embedded by CALL, transparently restoring the caller's LR.
    {"RET", {0, [](const std::vector<Token>&, uint16_t addr, int line) {
        ParsedInstruction move;
        move.mnemonic        = "MOVE";
        move.detected_format = Format::LS_REG;
        move.operands        = {makeRegToken(14, line), makeImmToken(0, line), makeRegToken(15, line)};
        move.line            = line;

        return std::vector<Assembler::EmitItem>{makeInstrItem(move)};
    }}},
};

// ---------------------------------------------------------------------------

static void appendU16(std::vector<uint8_t>& data, uint16_t v) {
    data.push_back(static_cast<uint8_t>(v & 0xFF));
    data.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
}

static void appendU32(std::vector<uint8_t>& data, uint32_t v) {
    data.push_back(static_cast<uint8_t>(v & 0xFF));
    data.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    data.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
    data.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
}

static void appendU64(std::vector<uint8_t>& data, uint64_t v) {
    appendU32(data, static_cast<uint32_t>(v & 0xFFFFFFFF));
    appendU32(data, static_cast<uint32_t>((v >> 32) & 0xFFFFFFFF));
}

static std::vector<uint8_t> makeElfObject(const std::vector<uint16_t>& words,
                                          const std::unordered_map<std::string, SymbolInfo>& symbols,
                                          const std::vector<Assembler::RelocEntry>& relocs) {
    // Convert mapped words to bytes (little-endian)
    std::vector<uint8_t> text;
    text.reserve(words.size() * 2);
    for (uint16_t w : words) {
        appendU16(text, w);
    }

    // Build string table for symbols and section names
    std::string strtab_contents;
    strtab_contents.push_back('\0');
    std::unordered_map<std::string, uint32_t> sym_name_offset;

    // include defined global symbols plus externs from symbols map and reloc refs
    std::vector<std::string> symbol_names;
    for (const auto& [name, info] : symbols) {
        symbol_names.push_back(name);
    }
    for (const auto& r : relocs) {
        if (std::find(symbol_names.begin(), symbol_names.end(), r.symbol) == symbol_names.end())
            symbol_names.push_back(r.symbol);
    }
    // Sort: local symbols first (for ELF sh_info correctness), then globals, both alphabetical.
    std::sort(symbol_names.begin(), symbol_names.end(), [&](const std::string& a, const std::string& b) {
        auto ia = symbols.find(a), ib = symbols.find(b);
        bool a_local = (ia != symbols.end()) && !ia->second.global;
        bool b_local = (ib != symbols.end()) && !ib->second.global;
        if (a_local != b_local) return a_local; // locals precede globals
        return a < b;
    });
    symbol_names.erase(std::unique(symbol_names.begin(), symbol_names.end()), symbol_names.end());

    // Count local symbols (they are sorted first); sh_info = one past the last local.
    size_t n_local_syms = 0;
    for (const auto& name : symbol_names) {
        auto it = symbols.find(name);
        if (it != symbols.end() && !it->second.global)
            ++n_local_syms;
        else
            break;
    }
    const uint32_t first_global_sh_info = static_cast<uint32_t>(n_local_syms + 1); // +1 for null entry

    for (const auto& name : symbol_names) {
        sym_name_offset[name] = static_cast<uint32_t>(strtab_contents.size());
        strtab_contents += name;
        strtab_contents.push_back('\0');
    }

    std::string shstrtab;
    shstrtab.push_back('\0');
    const auto shname = [&shstrtab](const char* s) {
        uint32_t off = static_cast<uint32_t>(shstrtab.size());
        shstrtab += s;
        shstrtab.push_back('\0');
        return off;
    };

    uint32_t sh_name_text    = shname(".text");
    uint32_t sh_name_symtab  = shname(".symtab");
    uint32_t sh_name_strtab  = shname(".strtab");
    uint32_t sh_name_relat   = shname(".rela.text");
    uint32_t sh_name_shstr   = shname(".shstrtab");

    // Build symbol table (.symtab): first null entry, then each label.
    // symbol_names already built above from symbols+relocs

    std::vector<uint8_t> symtab;
    // Elf64_Sym layout: st_name(4), st_info(1), st_other(1), st_shndx(2), st_value(8), st_size(8)
    auto append_sym = [&](uint32_t name, uint8_t info, uint16_t shndx,
                          uint64_t value, uint64_t size) {
        appendU32(symtab, name);
        symtab.push_back(info);
        symtab.push_back(0);
        appendU16(symtab, shndx);
        appendU64(symtab, value);
        appendU64(symtab, size);
    };

    // null symbol
    append_sym(0, 0, 0, 0, 0);

    for (const auto& name : symbol_names) {
        auto it = symbols.find(name);
        bool defined = it != symbols.end() && it->second.defined;
        bool glob = (it != symbols.end() && it->second.global);
        uint16_t value = (defined ? it->second.value : 0);
        uint32_t name_off = sym_name_offset.at(name);
        uint8_t bind = glob ? (1 << 4) : 0; // STB_GLOBAL or STB_LOCAL
        uint8_t info = bind | 0; // STT_NOTYPE
        uint16_t shndx = defined ? 1 : 0;
        append_sym(name_off, info, shndx, value, 0);
    }

    // Section indices (null=0, text=1, symtab=2, strtab=3, shstrtab=4, rela.text=5)
    constexpr uint16_t kShText   = 1;
    constexpr uint16_t kShSymtab = 2;
    constexpr uint16_t kShStrtab = 3;
    constexpr uint16_t kShShstr  = 4;
    constexpr uint16_t shnum     = 6;
    constexpr uint16_t shstrndx  = kShShstr;

    // Build .rela.text contents
    std::vector<uint8_t> rela_text;
    auto append_rela = [&](uint64_t offset, uint64_t info, int64_t addend) {
        appendU64(rela_text, offset);
        appendU64(rela_text, info);
        appendU64(rela_text, static_cast<uint64_t>(addend));
    };

    // Symbol index map is 1..N in symbol table output order.
    // Linear search is required because symbol_names is sorted locals-first (not purely
    // alphabetically), so std::lower_bound with the default comparator would miss globals
    // that sort alphabetically before some locals.
    auto find_symbol_index = [&](const std::string& name) -> uint32_t {
        auto it = std::find(symbol_names.begin(), symbol_names.end(), name);
        if (it == symbol_names.end()) return 0;
        return static_cast<uint32_t>(std::distance(symbol_names.begin(), it) + 1);
    };

    for (const auto& r : relocs) {
        uint32_t sym_idx = find_symbol_index(r.symbol);
        if (sym_idx == 0)
            throw std::runtime_error("Undefined relocation symbol: " + r.symbol);
        uint64_t info = (static_cast<uint64_t>(sym_idx) << 32) |
                        static_cast<uint64_t>(static_cast<uint32_t>(r.type));
        append_rela(r.offset, info, r.addend);
    }

    // compute offsets
    uint64_t offset = 64; // ELF header size for 64-bit
    uint64_t text_offset = offset;
    uint64_t text_size = text.size();
    offset += text_size;

    // align symtab to 8 bytes
    offset = (offset + 7) & ~uint64_t(7);
    uint64_t symtab_offset = offset;
    offset += symtab.size();

    // align strtab to 8 bytes
    offset = (offset + 7) & ~uint64_t(7);
    uint64_t strtab_offset = offset;
    offset += strtab_contents.size();

    // align shstrtab to 8 bytes
    offset = (offset + 7) & ~uint64_t(7);
    uint64_t shstrtab_offset = offset;
    offset += shstrtab.size();

    // .rela.text (even if empty)
    offset = (offset + 7) & ~uint64_t(7);
    uint64_t rela_offset = offset;
    offset += rela_text.size();

    uint64_t shoff = (offset + 7) & ~uint64_t(7);

    std::vector<uint8_t> out;
    out.reserve(shoff + shnum * 64);

    // ELF header
    out.resize(64, 0);
    out[0] = 0x7F; out[1] = 'E'; out[2] = 'L'; out[3] = 'F';
    out[4] = 2; // ELFCLASS64
    out[5] = 1; // ELFDATA2LSB
    out[6] = 1; // EV_CURRENT
    out[7] = 0; // OSABI

    auto writeU16 = [&](size_t idx, uint16_t v) {
        out[idx] = static_cast<uint8_t>(v & 0xFF);
        out[idx + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
    };
    auto writeU32 = [&](size_t idx, uint32_t v) {
        out[idx] = static_cast<uint8_t>(v & 0xFF);
        out[idx + 1] = static_cast<uint8_t>((v >> 8) & 0xFF);
        out[idx + 2] = static_cast<uint8_t>((v >> 16) & 0xFF);
        out[idx + 3] = static_cast<uint8_t>((v >> 24) & 0xFF);
    };
    auto writeU64 = [&](size_t idx, uint64_t v) {
        writeU32(idx, static_cast<uint32_t>(v & 0xFFFFFFFF));
        writeU32(idx + 4, static_cast<uint32_t>((v >> 32) & 0xFFFFFFFF));
    };

    writeU16(16, 1); // e_type = ET_REL
    writeU16(18, 0); // e_machine = EM_NONE
    writeU32(20, 1); // e_version
    writeU64(24, 0); // e_entry
    writeU64(32, 0); // e_phoff
    writeU64(40, shoff); // e_shoff
    writeU32(48, 0); // e_flags
    writeU16(52, 64); // e_ehsize
    writeU16(54, 0); // e_phentsize
    writeU16(56, 0); // e_phnum
    writeU16(58, 64); // e_shentsize
    writeU16(60, shnum); // e_shnum
    writeU16(62, shstrndx); // e_shstrndx

    // .text
    out.resize(text_offset);
    out.insert(out.end(), text.begin(), text.end());

    // padding to align symtab
    while (out.size() < symtab_offset) out.push_back(0);
    out.insert(out.end(), symtab.begin(), symtab.end());

    while (out.size() < strtab_offset) out.push_back(0);
    out.insert(out.end(), strtab_contents.begin(), strtab_contents.end());

    while (out.size() < shstrtab_offset) out.push_back(0);
    out.insert(out.end(), shstrtab.begin(), shstrtab.end());

    while (out.size() < rela_offset) out.push_back(0);
    out.insert(out.end(), rela_text.begin(), rela_text.end());

    while (out.size() < shoff) out.push_back(0);

    auto append_sh = [&](uint32_t name, uint32_t type, uint64_t flags,
                         uint64_t addr, uint64_t off, uint64_t size,
                         uint32_t link, uint32_t info, uint64_t addralign,
                         uint64_t entsize) {
        appendU32(out, name);
        appendU32(out, type);
        appendU64(out, flags);
        appendU64(out, addr);
        appendU64(out, off);
        appendU64(out, size);
        appendU32(out, link);
        appendU32(out, info);
        appendU64(out, addralign);
        appendU64(out, entsize);
    };

    // section 0: null
    append_sh(0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    // section 1: .text — SHF_ALLOC(2)|SHF_EXECINSTR(4) = 6
    append_sh(sh_name_text, 1, 6, 0, text_offset, text_size, 0, 0, 1, 0);
    // section 2: .symtab — sh_link=.strtab, sh_info=index of first global symbol
    append_sh(sh_name_symtab, 2, 0, 0, symtab_offset, symtab.size(), kShStrtab, first_global_sh_info, 8, 24);
    // section 3: .strtab
    append_sh(sh_name_strtab, 3, 0, 0, strtab_offset, strtab_contents.size(), 0, 0, 1, 0);
    // section 4: .shstrtab
    append_sh(sh_name_shstr, 3, 0, 0, shstrtab_offset, shstrtab.size(), 0, 0, 1, 0);
    // section 5: .rela.text — sh_link=.symtab, sh_info=.text
    append_sh(sh_name_relat, 4, 0, 0, rela_offset, rela_text.size(), kShSymtab, kShText, 8, 24);

    return out;
}

std::vector<uint16_t> Assembler::assemble(const std::string& source) {
    Encoder::init();
    emit_items.clear();

    Lexer lexer;
    std::vector<Token> tokens = lexer.tokenize(source);

    SymbolTable symbols;
    pass1(tokens, symbols);

    std::vector<uint16_t> output;
    pass2(symbols, output, false, nullptr);

    return output;
}

std::vector<uint8_t> Assembler::assembleElf(const std::string& source,
                                             const ElfOptions&) {
    Encoder::init();
    emit_items.clear();

    Lexer lexer;
    std::vector<Token> tokens = lexer.tokenize(source);

    SymbolTable symbols;
    pass1(tokens, symbols);

    std::vector<uint16_t> output;
    std::vector<RelocEntry> relocs;
    pass2(symbols, output, true, &relocs);

    return makeElfObject(output, symbols, relocs);
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
            auto it = symbols.find(label);
            if (it != symbols.end() && it->second.defined)
                throw std::runtime_error("Duplicate label: " + label + " at line " +
                                         std::to_string(tok.line));
            // Preserve global=true if already declared via .global; plain labels are local.
            bool is_global = (it != symbols.end()) && it->second.global;
            symbols[label] = {current_address, true, is_global};
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
            } else if (tok.lexeme == ".byte") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    DataDirective dd;
                    dd.kind    = DataDirective::Kind::Byte;
                    dd.value   = tokens[idx].int_value;
                    dd.address = current_address;
                    dd.line    = tok.line;
                    EmitItem item;
                    item.is_instruction = false;
                    item.data = std::move(dd);
                    emit_items.push_back(std::move(item));
                    current_address += 1;
                    idx++;
                } else {
                    throw std::runtime_error(".byte requires a value at line " +
                                             std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".short" || tok.lexeme == ".word") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    if (current_address % 2 != 0) current_address += 1;
                    DataDirective dd;
                    dd.kind    = DataDirective::Kind::Short;
                    dd.value   = tokens[idx].int_value;
                    dd.address = current_address;
                    dd.line    = tok.line;
                    EmitItem item;
                    item.is_instruction = false;
                    item.data = std::move(dd);
                    emit_items.push_back(std::move(item));
                    current_address += 2;
                    idx++;
                } else {
                    throw std::runtime_error(tok.lexeme + " requires a value at line " +
                                             std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".int") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::ImmediateAbs) {
                    if (current_address % 2 != 0) current_address += 1;
                    DataDirective dd;
                    dd.kind    = DataDirective::Kind::Int;
                    dd.value   = tokens[idx].int_value;
                    dd.address = current_address;
                    dd.line    = tok.line;
                    EmitItem item;
                    item.is_instruction = false;
                    item.data = std::move(dd);
                    emit_items.push_back(std::move(item));
                    current_address += 4;
                    idx++;
                } else {
                    throw std::runtime_error(".int requires a value at line " +
                                             std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".long") {
                idx++;
                if (idx < tokens.size() && (tokens[idx].kind == TokenKind::ImmediateAbs || tokens[idx].kind == TokenKind::Ident)) {
                    if (current_address % 2 != 0) current_address += 1;
                    DataDirective dd;
                    dd.kind    = DataDirective::Kind::Long;
                    dd.address = current_address;
                    dd.line    = tok.line;
                    if (tokens[idx].kind == TokenKind::ImmediateAbs) {
                        dd.value = tokens[idx].int_value;
                        dd.isSymbol = false;
                    } else {
                        dd.isSymbol = true;
                        dd.symbol = tokens[idx].lexeme;
                    }
                    EmitItem item;
                    item.is_instruction = false;
                    item.data = std::move(dd);
                    emit_items.push_back(std::move(item));
                    current_address += 8;
                    idx++;
                } else {
                    throw std::runtime_error(".long requires a value or symbol at line " +
                                             std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".ascii" || tok.lexeme == ".asciiz") {
                bool with_null = (tok.lexeme == ".asciiz");
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::StringLiteral) {
                    const std::string& text = tokens[idx].lexeme;
                    DataDirective dd;
                    dd.kind    = with_null ? DataDirective::Kind::Asciiz
                                           : DataDirective::Kind::Ascii;
                    dd.text    = text;
                    dd.address = current_address;
                    dd.line    = tok.line;
                    EmitItem item;
                    item.is_instruction = false;
                    item.data = std::move(dd);
                    emit_items.push_back(std::move(item));
                    current_address += static_cast<uint16_t>(text.length()) +
                                       (with_null ? 1 : 0);
                    idx++;
                } else {
                    throw std::runtime_error(tok.lexeme + " requires a string literal at line " +
                                             std::to_string(tok.line));
                }
            } else if (tok.lexeme == ".global" || tok.lexeme == ".extern") {
                idx++;
                if (idx < tokens.size() && tokens[idx].kind == TokenKind::Ident) {
                    std::string name = tokens[idx].lexeme;
                    auto it = symbols.find(name);
                    if (it == symbols.end()) {
                        symbols[name] = {0, false, true};
                    } else {
                        it->second.global = true;
                    }
                    idx++;
                } else {
                    throw std::runtime_error(tok.lexeme + " requires a symbol name at line " +
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

        // Instruction (real or pseudo)
        int line_at_start = line_count;
        std::string first_lexeme = (tokens[idx].kind == TokenKind::Ident) ? tokens[idx].lexeme : "";
        auto pseudo_it = pseudo_table.find(first_lexeme);

        if (pseudo_it != pseudo_table.end()) {
            idx++;  // consume mnemonic
            std::vector<Token> operands;
            while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                   tokens[idx].kind != TokenKind::EndOfFile) {
                if (tokens[idx].kind != TokenKind::Comma)
                    operands.push_back(tokens[idx]);
                idx++;
            }
            const auto& def = pseudo_it->second;
        if (static_cast<int>(operands.size()) != def.arity)
            throw std::runtime_error(first_lexeme + " expects " + std::to_string(def.arity) +
                                     " operand(s) at line " + std::to_string(line_at_start));

        for (auto item : def.expand(operands, current_address, line_at_start)) {
            if (item.is_instruction) {
                item.instr.address = current_address;
                emit_items.push_back(std::move(item));
                current_address += 2;
            } else {
                // Align 2-byte-access directives to even addresses.
                if ((item.data.kind == DataDirective::Kind::Short ||
                     item.data.kind == DataDirective::Kind::Int ||
                     item.data.kind == DataDirective::Kind::Long) &&
                    (current_address % 2 != 0)) {
                    current_address += 1;
                }
                item.data.address = current_address;
                emit_items.push_back(std::move(item));

                switch (item.data.kind) {
                    case DataDirective::Kind::Byte:
                        current_address += 1;
                        break;
                    case DataDirective::Kind::Short:
                        current_address += 2;
                        break;
                    case DataDirective::Kind::Int:
                        current_address += 4;
                        break;
                    case DataDirective::Kind::Long:
                        current_address += 8;
                        break;
                    case DataDirective::Kind::Ascii:
                        current_address += static_cast<uint16_t>(item.data.text.length());
                        break;
                    case DataDirective::Kind::Asciiz:
                        current_address += static_cast<uint16_t>(item.data.text.length() + 1);
                        break;
                }
            }
        }
        } else {
            ParsedInstruction parsed = parseInstruction(tokens, idx, current_address, line_count);
            parsed.line = line_at_start;
            EmitItem item;
            item.is_instruction = true;
            item.instr = std::move(parsed);
            emit_items.push_back(std::move(item));
            current_address += 2;
        }

        while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
               tokens[idx].kind != TokenKind::EndOfFile)
            idx++;
        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Newline) {
            idx++;
            line_count++;
        }
    }
}

// Forward declarations for helpers used by pass2 and encodeInstruction
static bool isJumpMnemonic(const std::string& m);

// Single-pass over emit_items, producing a packed byte buffer then folding
// into uint16_t output words.  Items are emitted in source order so data and
// instructions are interleaved correctly.
//
// Instruction addresses come from pass1 (item.instr.address), so .org is
// handled correctly for PC-relative encoding.  Data alignment uses the
// current byte-buffer size, which stays in sync with pass1's address
// tracking as long as both use the same padding rules.
void Assembler::pass2(const SymbolTable& symbols, std::vector<uint16_t>& output,
                         bool elf_mode, std::vector<RelocEntry>* out_relocs) {
    std::vector<uint8_t> buf;

    auto emit_le = [&](uint64_t v, int n) {
        for (int i = 0; i < n; i++)
            buf.push_back(static_cast<uint8_t>((v >> (i * 8)) & 0xFF));
    };
    auto align2 = [&]() {
        if (buf.size() % 2 != 0) buf.push_back(0);
    };
    // Pad buf with zeros up to the byte offset corresponding to a logical address.
    // This fills .org gaps so items are placed at their correct addresses.
    auto pad_to = [&](uint16_t addr) {
        size_t target = static_cast<size_t>(addr) - static_cast<size_t>(origin);
        if (buf.size() > target)
            throw std::runtime_error("Overlapping .org sections: data at 0x" +
                                     [&]{ std::ostringstream s; s << std::hex << addr; return s.str(); }());
        while (buf.size() < target)
            buf.push_back(0);
    };

    for (const auto& item : emit_items) {
        uint16_t item_addr = item.is_instruction ? item.instr.address : item.data.address;
        pad_to(item_addr);

        if (item.is_instruction) {
            if (buf.size() % 2 != 0)
                throw std::runtime_error(
                    "Instruction at odd address (preceded by an odd-length .byte/.ascii "
                    "sequence) at line " + std::to_string(item.instr.line));
            // Add relocation entries for PC-relative symbol references in ELF mode
            if (elf_mode && item.instr.detected_format == Format::LS_PCREL &&
                !item.instr.operands.empty() &&
                item.instr.operands[0].kind == TokenKind::PCRelLabel) {
                if (out_relocs) {
                    // JUMP.* (conditional branches) use 10-bit offset encoding; all others use 6-bit
                    bool is_cond_jump = isJumpMnemonic(item.instr.mnemonic) &&
                                       item.instr.mnemonic != "JUMP";
                    out_relocs->push_back({
                        item_addr,
                        item.instr.operands[0].lexeme,
                        is_cond_jump ? RelocType::PCREL10 : RelocType::PCREL6,
                        0
                    });
                }
            }
            // Use the address computed in pass1 — correctly reflects .org
            uint16_t word = encodeInstruction(item.instr, symbols, item.instr.address, elf_mode);
            buf.push_back(static_cast<uint8_t>(word));
            buf.push_back(static_cast<uint8_t>(word >> 8));
        } else {
            switch (item.data.kind) {
                case DataDirective::Kind::Byte:
                    emit_le(item.data.value, 1);
                    break;
                case DataDirective::Kind::Short:
                    align2();
                    emit_le(item.data.value, 2);
                    break;
                case DataDirective::Kind::Int:
                    align2();
                    emit_le(item.data.value, 4);
                    break;
                case DataDirective::Kind::Long: {
                    align2();
                    if (item.data.isSymbol) {
                        if (elf_mode) {
                            // relocation for .long symbol ref
                            if (out_relocs) {
                                out_relocs->push_back({
                                    static_cast<uint64_t>(buf.size()),
                                    item.data.symbol,
                                    RelocType::ABS64,
                                    0
                                });
                            }
                            emit_le(0, 8);
                        } else {
                            auto sym_it = symbols.find(item.data.symbol);
                            if (sym_it == symbols.end() || !sym_it->second.defined)
                                throw std::runtime_error("Undefined symbol in .long: " + item.data.symbol);
                            emit_le(sym_it->second.value, 8);
                        }
                    } else {
                        emit_le(item.data.value, 8);
                    }
                    break;
                }
                case DataDirective::Kind::Ascii:
                    for (unsigned char c : item.data.text) buf.push_back(c);
                    break;
                case DataDirective::Kind::Asciiz:
                    for (unsigned char c : item.data.text) buf.push_back(c);
                    buf.push_back(0);
                    break;
            }
        }
    }

    align2();
    for (size_t i = 0; i < buf.size(); i += 2)
        output.push_back(static_cast<uint16_t>(buf[i]) |
                         (static_cast<uint16_t>(buf[i + 1]) << 8));
}

// Helper: check if mnemonic is JUMP or a JUMP.* variant
static bool isJumpMnemonic(const std::string& m) {
    return m == "JUMP" ||
           m == "JUMP.Z" || m == "JUMP.C" || m == "JUMP.S" || m == "JUMP.GT" || m == "JUMP.LT";
}

// Helper: check if mnemonic is MOVE
static bool isMoveMnemonic(const std::string& m) {
    return m == "MOVE";
}

// Helper: check if mnemonic is PUSH or POP
static bool isPushPopMnemonic(const std::string& m) {
    return m == "PUSH" || m == "POP";
}

// Resolve LD/ST pseudo-mnemonics (with width suffixes) to their canonical LS forms.
// Bare "LD" is handled separately at the call site because it routes to LDI when
// followed by an immediate operand.
// LD.B → BYTE_LOAD   LD.S / LD.W → SHORT_LOAD   LD.I → WORD_LOAD   LD → LOAD
// ST   → STORE       ST.B → BYTE_STORE           ST.S / ST.W → SHORT_STORE
// ST.I → WORD_STORE
static std::string normalizeMnemonic(const std::string& m) {
    if (m == "LD")                   return "LOAD";
    if (m == "LD.B")                 return "BYTE_LOAD";
    if (m == "LD.S" || m == "LD.W") return "SHORT_LOAD";
    if (m == "LD.I")                 return "WORD_LOAD";
    if (m == "ST")                   return "STORE";
    if (m == "ST.B")                 return "BYTE_STORE";
    if (m == "ST.S" || m == "ST.W") return "SHORT_STORE";
    if (m == "ST.I")                 return "WORD_STORE";
    return m;
}

ParsedInstruction Assembler::parseInstruction(const std::vector<Token>& tokens,
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

    // Resolve LD/ST pseudo-mnemonics.
    // Bare "LD" maps to LDI when the next token is an immediate; otherwise to LOAD.
    // Width-suffixed forms (LD.B, LD.S, etc.) always map to LS memory instructions.
    if (base_mnemonic == "LD" && idx < tokens.size() &&
        tokens[idx].kind == TokenKind::ImmediateAbs) {
        base_mnemonic = "LDI";
    } else {
        base_mnemonic = normalizeMnemonic(base_mnemonic);
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
        GP::Encoding enc = Encoder::getGPEncoding(base_mnemonic);

        switch (enc) {
            case GP::Encoding::NONE:
                // No register operands — consume nothing (any trailing tokens are an error)
                break;
            case GP::Encoding::RD:
                // Rd only
                if (idx >= tokens.size() || tokens[idx].kind == TokenKind::Newline ||
                    tokens[idx].kind == TokenKind::EndOfFile)
                    throw std::runtime_error(base_mnemonic + " requires Rd at line " +
                                             std::to_string(line_count));
                if (tokens[idx].kind != TokenKind::Register)
                    throw std::runtime_error("Expected register for Rd at line " +
                                             std::to_string(line_count));
                result.operands.push_back(tokens[idx++]);  // Rd
                break;
            case GP::Encoding::RS1_RD:
            case GP::Encoding::IMM4_RD:
                // Collect all operand tokens; validation happens in pass 2
                while (idx < tokens.size() && tokens[idx].kind != TokenKind::Newline &&
                       tokens[idx].kind != TokenKind::EndOfFile) {
                    if (tokens[idx].kind != TokenKind::Comma)
                        result.operands.push_back(tokens[idx]);
                    idx++;
                }
                break;
        }
        return result;
    }

    if (!Encoder::isLSMnemonic(base_mnemonic) && !isJumpMnemonic(base_mnemonic))
        throw std::runtime_error("Unknown mnemonic: " + base_mnemonic + " at line " +
                                 std::to_string(line_count));

    // Stage 2: LS mnemonic — sub-format from first operand token
    if (idx >= tokens.size() || tokens[idx].kind == TokenKind::Newline ||
        tokens[idx].kind == TokenKind::EndOfFile)
        throw std::runtime_error("Expected operands for " + base_mnemonic + " at line " +
                                 std::to_string(line_count));

    TokenKind first_kind = tokens[idx].kind;

    if (first_kind == TokenKind::LeftBracket) {
        // Format 00 (LS Register): [Rs1] or [Rs1+N]
        // MOVE, JUMP, PUSH, and POP do not use bracket syntax.
        if (isMoveMnemonic(base_mnemonic) || isJumpMnemonic(base_mnemonic) ||
            isPushPopMnemonic(base_mnemonic))
            throw std::runtime_error(base_mnemonic +
                                     " does not use bracket syntax at line " +
                                     std::to_string(line_count));

        result.detected_format = Format::LS_REG;
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

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Register) {
            result.operands.push_back(tokens[idx++]);  // explicit Rd
        } else if (isJumpMnemonic(base_mnemonic)) {
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

    if (first_kind == TokenKind::Register &&
        (isMoveMnemonic(base_mnemonic) || isJumpMnemonic(base_mnemonic))) {
        // Register form for MOVE/JUMP: Rs1[+offset][, Rd]
        // MOVE requires explicit Rd; JUMP defaults Rd to R15.
        result.detected_format = Format::LS_REG;
        result.operands.push_back(tokens[idx++]);  // Rs1

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Plus) {
            idx++;  // consume '+'
            if (idx >= tokens.size() || tokens[idx].kind != TokenKind::ImmediateAbs)
                throw std::runtime_error("Expected offset after '+' at line " +
                                         std::to_string(line_count));
            result.operands.push_back(tokens[idx++]);  // offset
        } else {
            Token zero;
            zero.kind = TokenKind::ImmediateAbs;
            zero.lexeme = "0";
            zero.int_value = 0;
            zero.line = line_count;
            result.operands.push_back(zero);
        }

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Register) {
            result.operands.push_back(tokens[idx++]);  // explicit Rd
        } else if (isJumpMnemonic(base_mnemonic)) {
            Token r15;
            r15.kind = TokenKind::Register;
            r15.lexeme = "R15";
            r15.int_value = 15;
            r15.line = line_count;
            result.operands.push_back(r15);
        } else {
            throw std::runtime_error("MOVE requires a destination register at line " +
                                     std::to_string(line_count));
        }
        return result;
    }

    if (first_kind == TokenKind::Register && isPushPopMnemonic(base_mnemonic)) {
        // Register form for PUSH/POP: Rs1[, Rd]
        // Rd defaults to R13 (stack pointer) when omitted.
        result.detected_format = Format::LS_REG;
        result.operands.push_back(tokens[idx++]);  // Rs1 (data register)

        Token zero;
        zero.kind = TokenKind::ImmediateAbs;
        zero.lexeme = "0";
        zero.int_value = 0;
        zero.line = line_count;
        result.operands.push_back(zero);  // offset (always 0)

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Comma) idx++;

        if (idx < tokens.size() && tokens[idx].kind == TokenKind::Register) {
            result.operands.push_back(tokens[idx++]);  // explicit Rd (stack pointer)
        } else {
            Token r13;
            r13.kind = TokenKind::Register;
            r13.lexeme = "R13";
            r13.int_value = 13;
            r13.line = line_count;
            result.operands.push_back(r13);  // default Rd = R13
        }
        return result;
    }

    throw std::runtime_error("Unexpected operand syntax for " + base_mnemonic + " at line " +
                             std::to_string(line_count));
}

uint16_t Assembler::encodeInstruction(const ParsedInstruction& instr,
                                      const SymbolTable& symbols,
                                      uint16_t current_address,
                                      bool elf_mode) {
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
            uint8_t opcode    = Encoder::getGPOpcode(instr.mnemonic);
            GP::Encoding enc  = Encoder::getGPEncoding(instr.mnemonic);
            uint8_t rs1 = 0, rd = 0;

            switch (enc) {
                case GP::Encoding::NONE:
                    if (!instr.operands.empty()) err(instr.mnemonic + " takes no operands");
                    break;
                case GP::Encoding::RD:
                    if (instr.operands.size() < 1) err(instr.mnemonic + " requires Rd");
                    if (instr.operands[0].kind != TokenKind::Register) err("Expected register for Rd");
                    rd = instr.operands[0].int_value;
                    break;
                case GP::Encoding::RS1_RD:
                    if (instr.operands.size() < 2) err(instr.mnemonic + " requires Rs1, Rd");
                    if (instr.operands[0].kind != TokenKind::Register) err("Expected register for Rs1");
                    if (instr.operands[1].kind != TokenKind::Register) err("Expected register for Rd");
                    rs1 = instr.operands[0].int_value;
                    rd  = instr.operands[1].int_value;
                    break;
                case GP::Encoding::IMM4_RD:
                    if (instr.operands.size() < 2) err(instr.mnemonic + " requires #imm4, Rd");
                    if (instr.operands[0].kind != TokenKind::ImmediateAbs)
                        err("Expected immediate for " + instr.mnemonic + " shift count");
                    if (instr.operands[1].kind != TokenKind::Register) err("Expected register for Rd");
                    if (instr.operands[0].int_value > 15)
                        err("Immediate shift count out of range (0–15)");
                    rs1 = static_cast<uint8_t>(instr.operands[0].int_value);
                    rd  = instr.operands[1].int_value;
                    break;
            }
            return Encoder::encodeGP(opcode, rs1, rd);
        }

        case Format::LS_REG: {
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
            if (instr.operands.size() < 2) err(instr.mnemonic + " requires @label, Rd");
            if (instr.operands[1].kind != TokenKind::Register) err("Expected register for Rd");

            uint8_t rd = instr.operands[1].int_value;
            int32_t raw_offset = 0;

            const Token& addr_tok = instr.operands[0];
            if (addr_tok.kind == TokenKind::PCRelLabel) {
                auto it = symbols.find(addr_tok.lexeme);
                bool has_symbol = (it != symbols.end());
                bool defined = has_symbol && it->second.defined;

                if (!elf_mode && (!has_symbol || !defined))
                    err("Undefined label: " + addr_tok.lexeme);

                if (!elf_mode) {
                    if (!has_symbol) err("Undefined label: " + addr_tok.lexeme);
                    uint16_t target = it->second.value;
                    // pc_rel is in instruction units (×2 bytes), relative to next instruction
                    int32_t byte_diff = (int32_t)target - (int32_t)(current_address + 2);
                    if (byte_diff % 2 != 0) err("Target address is not instruction-aligned");
                    raw_offset = byte_diff / 2;
                } else {
                    // In ELF relocatable mode, placeholder value; linker resolves.
                    raw_offset = 0;
                }
            } else if (addr_tok.kind == TokenKind::PCRelOffset) {
                raw_offset = (int32_t)(int64_t)addr_tok.int_value;
            } else {
                err("Expected @label or @offset");
            }

            // JUMP is a pseudo-instruction aliased to MOVE
            const std::string& ls_mnemonic = (instr.mnemonic == "JUMP") ? "MOVE" : instr.mnemonic;
            uint8_t opcode = Encoder::getLSOpcode(ls_mnemonic);

            if (isJumpMnemonic(instr.mnemonic) && instr.mnemonic != "JUMP") {
                // Conditional JUMP.* in Format 01: 10-bit signed offset, Rd implicit = R15
                if (!elf_mode && (raw_offset < -511 || raw_offset > 511))
                    err("PC-relative offset out of range [-511, 511] for conditional jump");
                return Encoder::encodeLSPCRelJump(opcode, static_cast<int16_t>(raw_offset));
            } else {
                // All other LS PC-relative instructions: 6-bit signed offset
                if (!elf_mode && (raw_offset < -32 || raw_offset > 31))
                    err("PC-relative offset out of range [-32, 31]");
                return Encoder::encodeLSPCRel(opcode, static_cast<int8_t>(raw_offset), rd);
            }
        }
    }

    // Unreachable
    err("Internal assembler error");
    return 0;
}

std::string Assembler::getListing() const {
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (const auto& item : emit_items) {
        if (item.is_instruction)
            oss << "0x" << std::setw(4) << item.instr.address
                << "  " << item.instr.mnemonic << "\n";
    }
    return oss.str();
}

std::vector<std::string> Assembler::getAllMnemonics() {
    Encoder::init();
    std::vector<std::string> result = Encoder::getMnemonics();

    // LDI and LD with numeric suffix forms (.SN and .N, N = 0–3)
    for (const std::string base : {"LDI", "LD"}) {
        result.push_back(base);
        for (int n = 0; n <= 3; ++n) {
            result.push_back(base + "." + std::to_string(n));
            result.push_back(base + ".S" + std::to_string(n));
        }
    }

    // LD/ST width suffix aliases (map to LS memory instructions)
    for (const char* s : {"LD.B", "LD.S", "LD.W", "LD.I",
                          "ST", "ST.B", "ST.S", "ST.W", "ST.I"})
        result.push_back(s);

    // JUMP and Conditional JUMP variants
    for (const char* s : {"JUMP", "JUMP.Z", "JUMP.C", "JUMP.S", "JUMP.GT", "JUMP.LT"})
        result.push_back(s);

    // Pseudo-instructions from the table
    for (const auto& kv : pseudo_table)
        result.push_back(kv.first);

    return result;
}
