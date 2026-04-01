#include "debug_server.hpp"

#include "headless_runtime.hpp"

#include <iomanip>
#include <sstream>
#include <string>

namespace {

std::string trim(const std::string& input) {
    const auto begin = input.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) {
        return {};
    }
    const auto end = input.find_last_not_of(" \t\r\n");
    return input.substr(begin, end - begin + 1);
}

bool parseUnsigned(const std::string& token, uint64_t& value) {
    try {
        size_t parsed = 0;
        value = std::stoull(token, &parsed, 0);
        return parsed == token.size();
    } catch (...) {
        return false;
    }
}

std::string hex64(uint64_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return out.str();
}

} // namespace

DebugServer::DebugServer(IEmulatorRuntime& runtime, IDebugTransport& transport)
    : _runtime(runtime), _transport(transport) {}

int DebugServer::run() {
    _transport.writeLine("little-64 debug server (stdio skeleton)");
    _transport.writeLine("Type 'help' for available commands.");

    bool should_exit = false;
    std::string line;
    while (!should_exit && _transport.readCommand(line)) {
        if (!handleCommand(line, should_exit)) {
            _transport.writeLine("ERR command failed");
        }
    }

    return 0;
}

bool DebugServer::handleCommand(const std::string& line, bool& should_exit) {
    std::string command_line = trim(line);
    if (command_line.empty()) {
        return true;
    }

    std::istringstream in(command_line);
    std::string command;
    in >> command;

    if (command == "help") {
        printHelp();
        return true;
    }

    if (command == "quit" || command == "exit") {
        should_exit = true;
        _transport.writeLine("OK bye");
        return true;
    }

    if (command == "load") {
        std::string path;
        in >> path;
        if (path.empty()) {
            _transport.writeLine("ERR usage: load <path>");
            return false;
        }
        std::string error;
        if (!loadRuntimeImageFromPath(_runtime, path, error)) {
            _transport.writeLine("ERR " + error);
            return false;
        }
        _transport.writeLine("OK loaded");
        return true;
    }

    if (command == "run") {
        uint64_t max_cycles = 0;
        std::string token;
        if (in >> token && !parseUnsigned(token, max_cycles)) {
            _transport.writeLine("ERR usage: run [max_cycles]");
            return false;
        }

        HeadlessRunOptions options;
        options.stream_serial_stdout = false;
        options.max_cycles = max_cycles;

        std::string error;
        const int rc = runRuntimeUntilStop(_runtime, options, error);
        if (rc != 0) {
            _transport.writeLine("ERR " + error);
            return false;
        }

        std::string serial = _runtime.drainSerialTx();
        if (!serial.empty()) {
            _transport.writeLine("SERIAL " + serial);
        }
        _transport.writeLine("OK halted");
        return true;
    }

    if (command == "step") {
        uint64_t count = 1;
        std::string token;
        if (in >> token && (!parseUnsigned(token, count) || count == 0)) {
            _transport.writeLine("ERR usage: step [count]");
            return false;
        }

        for (uint64_t i = 0; i < count && _runtime.isRunning(); ++i) {
            _runtime.cycle();
        }

        std::string serial = _runtime.drainSerialTx();
        if (!serial.empty()) {
            _transport.writeLine("SERIAL " + serial);
        }
        _transport.writeLine("OK pc=" + hex64(_runtime.pc()));
        return true;
    }

    if (command == "reset") {
        _runtime.reset();
        _transport.writeLine("OK reset");
        return true;
    }

    if (command == "pc") {
        _transport.writeLine("OK pc=" + hex64(_runtime.pc()));
        return true;
    }

    if (command == "regs") {
        RegisterSnapshot snapshot = _runtime.registers();
        for (int i = 0; i < 16; ++i) {
            _transport.writeLine("R" + std::to_string(i) + "=" + hex64(snapshot.gpr[i]));
        }
        _transport.writeLine("FLAGS=" + hex64(snapshot.flags));
        _transport.writeLine("OK regs");
        return true;
    }

    if (command == "reg") {
        std::string idx_token;
        in >> idx_token;
        uint64_t idx = 0;
        if (idx_token.empty() || !parseUnsigned(idx_token, idx) || idx > 15) {
            _transport.writeLine("ERR usage: reg <0-15>");
            return false;
        }
        _transport.writeLine("OK R" + std::to_string((int)idx) + "=" + hex64(_runtime.reg((int)idx)));
        return true;
    }

    if (command == "mem8") {
        std::string addr_token;
        std::string count_token;
        in >> addr_token;
        in >> count_token;

        uint64_t addr = 0;
        if (addr_token.empty() || !parseUnsigned(addr_token, addr)) {
            _transport.writeLine("ERR usage: mem8 <addr> [count]");
            return false;
        }

        uint64_t count = 16;
        if (!count_token.empty()) {
            if (!parseUnsigned(count_token, count) || count == 0 || count > 256) {
                _transport.writeLine("ERR mem8 count must be 1..256");
                return false;
            }
        }

        std::ostringstream out;
        out << "OK ";
        for (uint64_t i = 0; i < count; ++i) {
            if (i != 0) out << ' ';
            out << std::hex << std::setw(2) << std::setfill('0')
                << static_cast<unsigned>(_runtime.memoryRead8(addr + i));
        }
        _transport.writeLine(out.str());
        return true;
    }

    _transport.writeLine("ERR unknown command");
    return false;
}

void DebugServer::printHelp() {
    _transport.writeLine("OK commands:");
    _transport.writeLine("  help");
    _transport.writeLine("  load <path>");
    _transport.writeLine("  run [max_cycles]");
    _transport.writeLine("  step [count]");
    _transport.writeLine("  reset");
    _transport.writeLine("  pc");
    _transport.writeLine("  regs");
    _transport.writeLine("  reg <0-15>");
    _transport.writeLine("  mem8 <addr> [count]");
    _transport.writeLine("  quit");
}
