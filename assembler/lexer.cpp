#include "lexer.hpp"
#include <cctype>
#include <stdexcept>

char Lexer::peek(int offset) const {
    if (pos + offset >= source.length()) {
        return '\0';
    }
    return source[pos + offset];
}

char Lexer::consume() {
    char c = peek();
    if (c == '\n') {
        line++;
        column = 1;
    } else {
        column++;
    }
    pos++;
    return c;
}

void Lexer::skipWhitespace() {
    while (std::isspace(peek()) && peek() != '\n') {
        consume();
    }
}

void Lexer::skipComment() {
    if (peek() == ';') {
        while (peek() != '\n' && peek() != '\0') {
            consume();
        }
    }
}

Token Lexer::scanNumber(int base) {
    int start_line = line, start_col = column;
    std::string lexeme;
    while (std::isxdigit(peek())) {
        lexeme += consume();
    }
    uint64_t value = 0;
    try {
        value = std::stoull(lexeme, nullptr, base);
    } catch (...) {
        throw std::runtime_error("Number out of range at " + std::to_string(line) + ":" + std::to_string(column));
    }
    Token t;
    t.kind = TokenKind::ImmediateAbs;
    t.lexeme = lexeme;
    t.int_value = value;
    t.line = start_line;
    t.column = start_col;
    return t;
}

Token Lexer::scanIdentifierOrRegister() {
    int start_line = line, start_col = column;
    std::string lexeme;

    // Scan base identifier/register name
    while (std::isalnum(peek()) || peek() == '_' || peek() == '.') {
        lexeme += consume();
    }

    // Check for mask suffix [mask] on mnemonic (e.g., LOAD[3], STORE[BW])
    if (peek() == '[') {
        size_t bracket_start = lexeme.length();
        lexeme += consume();  // '['
        while (peek() != ']' && peek() != '\0') {
            lexeme += consume();
        }
        if (peek() == ']') {
            lexeme += consume();  // ']'
        }
    }

    // Check if it's a register (R0-R15)
    // Registers don't have suffixes, so check the base name
    std::string base_name = lexeme;
    if (base_name.find('[') != std::string::npos) {
        base_name = base_name.substr(0, base_name.find('['));
    }
    if ((base_name[0] == 'R' || base_name[0] == 'r') && base_name.length() <= 3) {
        if (base_name.length() > 1 && std::isdigit(base_name[1])) {
            int reg_num = std::stoi(base_name.substr(1));
            if (reg_num >= 0 && reg_num <= 15) {
                Token t;
                t.kind = TokenKind::Register;
                t.lexeme = base_name;
                t.int_value = reg_num;
                t.line = start_line;
                t.column = start_col;
                return t;
            }
        }
    }

    // Otherwise it's an identifier (mnemonic, label, directive, etc.)
    Token t;
    t.kind = TokenKind::Ident;
    t.lexeme = lexeme;
    t.line = start_line;
    t.column = start_col;
    return t;
}

Token Lexer::makeToken(TokenKind kind, const std::string& lexeme) {
    Token t;
    t.kind = kind;
    t.lexeme = lexeme;
    t.line = line;
    t.column = column;
    return t;
}

std::vector<Token> Lexer::tokenize(const std::string& source_code) {
    source = source_code;
    pos = 0;
    line = 1;
    column = 1;

    std::vector<Token> tokens;

    while (peek() != '\0') {
        skipWhitespace();
        if (peek() == '\0') break;

        // Comment
        if (peek() == ';') {
            skipComment();
            continue;
        }

        // Newline
        if (peek() == '\n') {
            consume();
            tokens.push_back(makeToken(TokenKind::Newline, "\\n"));
            continue;
        }

        // Single-char tokens
        if (peek() == ',') {
            consume();
            tokens.push_back(makeToken(TokenKind::Comma, ","));
            continue;
        }
        if (peek() == ':') {
            consume();
            tokens.push_back(makeToken(TokenKind::Colon, ":"));
            continue;
        }
        if (peek() == '[') {
            consume();
            tokens.push_back(makeToken(TokenKind::LeftBracket, "["));
            continue;
        }
        if (peek() == ']') {
            consume();
            tokens.push_back(makeToken(TokenKind::RightBracket, "]"));
            continue;
        }

        // Numbers (with # prefix or bare)
        if (peek() == '#') {
            consume();
            if (peek() == '0' && (peek(1) == 'x' || peek(1) == 'X')) {
                consume(); // '0'
                consume(); // 'x'
                tokens.push_back(scanNumber(16));
            } else if (peek() == '0' && (peek(1) == 'b' || peek(1) == 'B')) {
                consume(); // '0'
                consume(); // 'b'
                tokens.push_back(scanNumber(2));
            } else {
                tokens.push_back(scanNumber(10));
            }
            continue;
        }

        // Bare numbers (0x..., 0b..., or decimal)
        if (peek() == '0' && (peek(1) == 'x' || peek(1) == 'X')) {
            consume(); // '0'
            consume(); // 'x'
            tokens.push_back(scanNumber(16));
            continue;
        }
        if (peek() == '0' && (peek(1) == 'b' || peek(1) == 'B')) {
            consume(); // '0'
            consume(); // 'b'
            tokens.push_back(scanNumber(2));
            continue;
        }
        if (std::isdigit(peek())) {
            tokens.push_back(scanNumber(10));
            continue;
        }

        // PC-relative with prefix (@label or @+offset)
        if (peek() == '@') {
            int at_line = line, at_col = column;
            consume();
            if (peek() == '+' || peek() == '-') {
                char sign = consume();
                Token t = scanNumber(10);
                if (sign == '-') {
                    t.int_value = -(int64_t)t.int_value;
                }
                t.kind = TokenKind::PCRelOffset;
                t.line = at_line;
                t.column = at_col;
                tokens.push_back(t);
            } else {
                Token t = scanIdentifierOrRegister();
                t.kind = TokenKind::PCRelLabel;
                t.line = at_line;
                t.column = at_col;
                tokens.push_back(t);
            }
            continue;
        }

        // Identifiers/registers/directives (may start with . or letter, can include . within)
        if (std::isalpha(peek()) || peek() == '_' || peek() == '.') {
            Token t = scanIdentifierOrRegister();
            tokens.push_back(t);
            // Check if followed by [ for mask suffix
            skipWhitespace();
            if (peek() == '[') {
                // Don't consume the bracket here; let the parser handle it
            }
            continue;
        }

        throw std::runtime_error("Unexpected character '" + std::string(1, peek()) + "' at " +
                               std::to_string(line) + ":" + std::to_string(column));
    }

    tokens.push_back(makeToken(TokenKind::EndOfFile, ""));
    return tokens;
}
