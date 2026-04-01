#pragma once

#include <cstdint>
#include <string>

class IDebugTransport {
public:
    virtual ~IDebugTransport() = default;

    virtual bool readPacket(std::string& payload, bool& is_interrupt) = 0;
    virtual bool writePacket(const std::string& payload) = 0;
    virtual bool pollInterrupt() = 0;
};

class TcpRspTransport : public IDebugTransport {
public:
    explicit TcpRspTransport(uint16_t port);
    ~TcpRspTransport() override;

    bool readPacket(std::string& payload, bool& is_interrupt) override;
    bool writePacket(const std::string& payload) override;
    bool pollInterrupt() override;

private:
    bool ensureConnected();
    bool readByteBlocking(uint8_t& byte);
    bool sendByte(uint8_t byte);
    bool sendAll(const uint8_t* data, size_t size);
    static uint8_t checksum(const std::string& payload);
    static uint8_t fromHexNibble(uint8_t c);
    static bool decodeHexByte(uint8_t hi, uint8_t lo, uint8_t& out);

    uint16_t _port;
    int _listen_fd = -1;
    int _client_fd = -1;
};
