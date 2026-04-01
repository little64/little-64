#include "debug_server.hpp"
#include "debug_transport.hpp"
#include "emulator_session.hpp"

int main() {
    EmulatorSession runtime;
    StdioDebugTransport transport;
    DebugServer server(runtime, transport);
    return server.run();
}
