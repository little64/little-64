#include "debug_server.hpp"
#include "debug_transport.hpp"
#include "emulator_session.hpp"
#include "headless_runtime.hpp"

#include <cstdint>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    uint16_t port = 9000;
    std::string image_path;
    if (argc >= 2) {
        try {
            const unsigned long parsed = std::stoul(argv[1], nullptr, 10);
            if (parsed > 0 && parsed <= 65535) {
                port = static_cast<uint16_t>(parsed);
            }
        } catch (...) {
            return 2;
        }
    }
    if (argc >= 3) {
        image_path = argv[2];
    }

    EmulatorSession runtime;
    if (!image_path.empty()) {
        std::string error;
        if (!loadRuntimeImageFromPath(runtime, image_path, error)) {
            std::cerr << error << '\n';
            return 2;
        }
    }

    TcpRspTransport transport(port);
    DebugServer server(runtime, transport);
    return server.run();
}
