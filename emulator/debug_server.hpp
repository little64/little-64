#pragma once

#include "debug_transport.hpp"
#include "frontend_api.hpp"

class DebugServer {
public:
    explicit DebugServer(IEmulatorRuntime& runtime, IDebugTransport& transport);

    int run();

private:
    bool handleCommand(const std::string& line, bool& should_exit);
    void printHelp();

    IEmulatorRuntime& _runtime;
    IDebugTransport& _transport;
};
