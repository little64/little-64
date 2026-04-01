#pragma once

#include "debug_transport.hpp"
#include "frontend_api.hpp"

#include <cstdint>
#include <set>
#include <string>

class DebugServer {
public:
    explicit DebugServer(IEmulatorRuntime& runtime, IDebugTransport& transport);

    int run();

private:
    bool handlePacket(const std::string& payload, bool& should_exit);
    bool handleQueryPacket(const std::string& payload);
    bool handleSetBreakpoint(const std::string& payload);
    bool handleClearBreakpoint(const std::string& payload);
    bool handleReadMemory(const std::string& payload);
    bool handleContinue(const std::string& payload);
    bool handleStep(const std::string& payload);
    bool handleVCont(const std::string& payload);

    void setLastStopReply(const std::string& reply);
    std::string registerPayload() const;
    std::string targetXml() const;

    static bool parseHexU64(const std::string& text, uint64_t& out);
    static std::string encodeHexU64LE(uint64_t value);
    static std::string encodeHexByte(uint8_t value);

    IEmulatorRuntime& _runtime;
    IDebugTransport& _transport;
    std::set<uint64_t> _breakpoints;
    std::string _last_stop_reply = "T05thread:1;threads:1;";
};
