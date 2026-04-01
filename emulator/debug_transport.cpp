#include "debug_transport.hpp"

#include <iostream>

bool StdioDebugTransport::readCommand(std::string& line) {
    return static_cast<bool>(std::getline(std::cin, line));
}

void StdioDebugTransport::writeLine(std::string_view line) {
    std::cout << line << '\n' << std::flush;
}
