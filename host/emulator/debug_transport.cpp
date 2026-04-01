#include "debug_transport.hpp"

#include <arpa/inet.h>
#include <cstdio>
#include <cerrno>
#include <cstring>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {

constexpr int kBacklog = 1;

} // namespace

TcpRspTransport::TcpRspTransport(uint16_t port)
    : _port(port) {}

TcpRspTransport::~TcpRspTransport() {
    if (_client_fd >= 0) {
        ::close(_client_fd);
        _client_fd = -1;
    }
    if (_listen_fd >= 0) {
        ::close(_listen_fd);
        _listen_fd = -1;
    }
}

bool TcpRspTransport::ensureConnected() {
    if (_client_fd >= 0) {
        return true;
    }

    if (_listen_fd < 0) {
        _listen_fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (_listen_fd < 0) {
            return false;
        }

        int opt = 1;
        ::setsockopt(_listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        addr.sin_port = htons(_port);

        if (::bind(_listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
            return false;
        }
        if (::listen(_listen_fd, kBacklog) < 0) {
            return false;
        }
    }

    _client_fd = ::accept(_listen_fd, nullptr, nullptr);
    return _client_fd >= 0;
}

bool TcpRspTransport::readByteBlocking(uint8_t& byte) {
    ssize_t n = ::recv(_client_fd, &byte, 1, 0);
    if (n == 1) {
        return true;
    }
    return false;
}

bool TcpRspTransport::sendAll(const uint8_t* data, size_t size) {
    size_t sent = 0;
    while (sent < size) {
        const ssize_t n = ::send(_client_fd, data + sent, size - sent, 0);
        if (n <= 0) {
            return false;
        }
        sent += static_cast<size_t>(n);
    }
    return true;
}

bool TcpRspTransport::sendByte(uint8_t byte) {
    return sendAll(&byte, 1);
}

uint8_t TcpRspTransport::checksum(const std::string& payload) {
    uint8_t sum = 0;
    for (const char c : payload) {
        sum = static_cast<uint8_t>(sum + static_cast<uint8_t>(c));
    }
    return sum;
}

uint8_t TcpRspTransport::fromHexNibble(uint8_t c) {
    if (c >= '0' && c <= '9') return static_cast<uint8_t>(c - '0');
    if (c >= 'a' && c <= 'f') return static_cast<uint8_t>(10 + c - 'a');
    if (c >= 'A' && c <= 'F') return static_cast<uint8_t>(10 + c - 'A');
    return 0xFF;
}

bool TcpRspTransport::decodeHexByte(uint8_t hi, uint8_t lo, uint8_t& out) {
    const uint8_t n1 = fromHexNibble(hi);
    const uint8_t n2 = fromHexNibble(lo);
    if (n1 == 0xFF || n2 == 0xFF) {
        return false;
    }
    out = static_cast<uint8_t>((n1 << 4) | n2);
    return true;
}

bool TcpRspTransport::readPacket(std::string& payload, bool& is_interrupt) {
    payload.clear();
    is_interrupt = false;

    if (!ensureConnected()) {
        return false;
    }

    while (true) {
        uint8_t first = 0;
        if (!readByteBlocking(first)) {
            return false;
        }

        if (first == 0x03) {
            is_interrupt = true;
            return true;
        }
        if (first == '+' || first == '-') {
            continue;
        }
        if (first != '$') {
            continue;
        }

        std::string candidate;
        uint8_t b = 0;
        while (true) {
            if (!readByteBlocking(b)) {
                return false;
            }
            if (b == '#') {
                break;
            }
            candidate.push_back(static_cast<char>(b));
        }

        uint8_t hi = 0;
        uint8_t lo = 0;
        if (!readByteBlocking(hi) || !readByteBlocking(lo)) {
            return false;
        }

        uint8_t expected = 0;
        if (!decodeHexByte(hi, lo, expected)) {
            if (!sendByte('-')) {
                return false;
            }
            continue;
        }

        const uint8_t actual = checksum(candidate);
        if (actual != expected) {
            if (!sendByte('-')) {
                return false;
            }
            continue;
        }

        if (!sendByte('+')) {
            return false;
        }
        payload = std::move(candidate);
        return true;
    }
}

bool TcpRspTransport::writePacket(const std::string& payload) {
    if (!ensureConnected()) {
        return false;
    }

    char checksum_buf[3]{};
    const uint8_t sum = checksum(payload);
    std::snprintf(checksum_buf, sizeof(checksum_buf), "%02x", sum);

    const std::string framed = "$" + payload + "#" + checksum_buf;
    return sendAll(reinterpret_cast<const uint8_t*>(framed.data()), framed.size());
}

bool TcpRspTransport::pollInterrupt() {
    if (_client_fd < 0) {
        return false;
    }

    pollfd pfd{};
    pfd.fd = _client_fd;
    pfd.events = POLLIN;
    const int rc = ::poll(&pfd, 1, 0);
    if (rc <= 0) {
        return false;
    }

    if (pfd.revents & (POLLHUP | POLLERR | POLLNVAL)) {
        ::close(_client_fd);
        _client_fd = -1;
        return true;
    }

    if (!(pfd.revents & POLLIN)) {
        return false;
    }

    uint8_t byte = 0;
    const ssize_t n = ::recv(_client_fd, &byte, 1, MSG_DONTWAIT);
    if (n == 0) {
        ::close(_client_fd);
        _client_fd = -1;
        return true;
    }
    if (n != 1) {
        return false;
    }
    return byte == 0x03;
}
