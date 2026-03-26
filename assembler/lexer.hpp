#pragma once

#include <vector>
#include <string>
#include <cstdint>

enum class TokenKind {
    // Identifiers and literals
    Ident,              // identifier (label name, directive name)
    Register,           // R0-R15, stores register index
    ImmediateAbs,       // #number
    PCRelLabel,         // @label
    PCRelOffset,        // @+number or @-number

    // Syntax
    Comma,              // ,
    Colon,              // :
    Plus,               // + (inside bracket address expressions, e.g. [R1+4])
    LeftBracket,        // [
    RightBracket,       // ]

    // Directives and control
    Newline,            // end of line
    EndOfFile,
};

struct Token {
    TokenKind kind;
    std::string lexeme;     // raw text
    int line;               // 1-based
    int column;             // 1-based
    uint64_t int_value = 0; // for numeric/register tokens
};

class Lexer {
public:
    // Tokenize the entire source string
    std::vector<Token> tokenize(const std::string& source);

private:
    std::string source;
    size_t pos = 0;
    int line = 1;
    int column = 1;

    char peek(int offset = 0) const;
    char consume();
    void skipWhitespace();
    void skipComment();
    Token scanNumber(int base = 10);
    Token scanIdentifierOrRegister();
    Token makeToken(TokenKind kind, const std::string& lexeme);
};
