#include "debug_server.hpp"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <iomanip>
#include <sstream>
#include <string>

namespace {

bool parseRegisterInfoIndex(const std::string& payload, uint64_t& out_index) {
    static constexpr const char* kPrefix = "qRegisterInfo";
    if (!payload.starts_with(kPrefix)) {
        return false;
    }

    const std::string index_text = payload.substr(std::char_traits<char>::length(kPrefix));
    if (index_text.empty()) {
        return false;
    }

    const char* begin = index_text.data();
    const char* end = begin + index_text.size();
    auto [ptr, ec] = std::from_chars(begin, end, out_index, 16);
    return ec == std::errc() && ptr == end;
}

} // namespace

DebugServer::DebugServer(IEmulatorRuntime& runtime, IDebugTransport& transport)
    : _runtime(runtime), _transport(transport) {}

int DebugServer::run() {
    bool should_exit = false;
    std::string payload;
    while (!should_exit) {
        bool is_interrupt = false;
        if (!_transport.readPacket(payload, is_interrupt)) {
            break;
        }
        if (is_interrupt) {
            setLastStopReply("S02");
            _transport.writePacket(_last_stop_reply);
            continue;
        }
        handlePacket(payload, should_exit);
    }

    return 0;
}

bool DebugServer::handlePacket(const std::string& payload, bool& should_exit) {
    if (payload.empty()) {
        _transport.writePacket("");
        return true;
    }

    if (payload == "?") {
        _transport.writePacket(_last_stop_reply);
        return true;
    }

    if (payload == "qSupported" || payload.starts_with("qSupported:")) {
        _transport.writePacket(
            "PacketSize=4000;"
            "qXfer:features:read+;"
            "QStartNoAckMode+;"
            "QThreadSuffixSupported+;"
            "QListThreadsInStopReply+;"
            "swbreak+;hwbreak+;vContSupported+");
        return true;
    }

    if (payload == "QStartNoAckMode") {
        _transport.writePacket("OK");
        _transport.setNoAckMode(true);
        return true;
    }

    if (payload == "QThreadSuffixSupported") {
        _transport.writePacket("OK");
        return true;
    }

    if (payload == "QListThreadsInStopReply") {
        _transport.writePacket("OK");
        return true;
    }

    if (payload == "vMustReplyEmpty") {
        _transport.writePacket("");
        return true;
    }

    if (payload == "qAttached") {
        _transport.writePacket("1");
        return true;
    }

    if (payload == "qProcessInfo") {
        _transport.writePacket("pid:1;endian:little;ptrsize:8;triple:little64-unknown-unknown;");
        return true;
    }

    if (payload == "qHostInfo") {
        _transport.writePacket("triple:little64-unknown-unknown;endian:little;ptrsize:8;");
        return true;
    }

    if (payload == "qC") {
        _transport.writePacket("QC1");
        return true;
    }

    if (payload == "qOffsets") {
        _transport.writePacket("Text=0;Data=0;Bss=0");
        return true;
    }

    if (payload.starts_with("qMemoryRegionInfo:")) {
        _transport.writePacket("start:0;size:ffffffffffffffff;permissions:rwx;");
        return true;
    }

    if (payload.starts_with("qThreadStopInfo")) {
        _transport.writePacket(_last_stop_reply);
        return true;
    }

    if (payload == "qTStatus") {
        _transport.writePacket("");
        return true;
    }

    if (payload == "qSymbol::") {
        _transport.writePacket("OK");
        return true;
    }

    if (payload == "jThreadsInfo") {
        _transport.writePacket(R"([{"tid":1,"name":"main"}])");
        return true;
    }

    if (payload.starts_with("jThreadExtendedInfo")) {
        _transport.writePacket(R"({"name":"main","reason":"none"})");
        return true;
    }

    if (payload.starts_with("qRegisterInfo")) {
        uint64_t reg_index = 0;
        if (!parseRegisterInfoIndex(payload, reg_index)) {
            _transport.writePacket("E01");
            return true;
        }

        if (reg_index > 16) {
            _transport.writePacket("E45");
            return true;
        }

        static constexpr const char* kNames[17] = {
            "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
            "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc", "flags"
        };

        std::ostringstream out;
        out << "name:" << kNames[reg_index]
            << ";bitsize:64;offset:" << (reg_index * 8)
            << ";encoding:uint;format:hex;set:General Purpose Registers;"
            << "gcc:" << reg_index << ";dwarf:" << reg_index << ";";

        if (reg_index == 13) {
            out << "generic:sp;";
        } else if (reg_index == 14) {
            out << "generic:ra;";
        } else if (reg_index == 15) {
            out << "generic:pc;";
        }

        _transport.writePacket(out.str());
        return true;
    }

    if (payload == "qfThreadInfo") {
        _transport.writePacket("m1");
        return true;
    }

    if (payload == "qsThreadInfo") {
        _transport.writePacket("l");
        return true;
    }

    if (payload.size() >= 3 && payload[0] == 'H' && (payload[1] == 'c' || payload[1] == 'g')) {
        _transport.writePacket("OK");
        return true;
    }

    if (payload == "g" || payload.starts_with("g;")) {
        _transport.writePacket(registerPayload());
        return true;
    }

    if (payload.starts_with("p")) {
        const size_t suffix_pos = payload.find(';');
        const std::string reg_text = suffix_pos == std::string::npos
            ? payload.substr(1)
            : payload.substr(1, suffix_pos - 1);

        uint64_t reg_index = 0;
        if (!parseHexU64(reg_text, reg_index)) {
            _transport.writePacket("E01");
            return true;
        }

        const RegisterSnapshot snapshot = _runtime.registers();
        if (reg_index < 16) {
            _transport.writePacket(encodeHexU64LE(snapshot.gpr[static_cast<size_t>(reg_index)]));
            return true;
        }
        if (reg_index == 16) {
            _transport.writePacket(encodeHexU64LE(snapshot.flags));
            return true;
        }

        _transport.writePacket("E45");
        return true;
    }

    if (payload.starts_with("m")) {
        return handleReadMemory(payload.substr(1));
    }

    if (payload.starts_with("Z0,")) {
        return handleSetBreakpoint(payload.substr(3));
    }

    if (payload.starts_with("z0,")) {
        return handleClearBreakpoint(payload.substr(3));
    }

    if (payload == "c" || payload.starts_with("c")) {
        return handleContinue(payload);
    }

    if (payload == "s" || payload.starts_with("s")) {
        return handleStep(payload);
    }

    if (payload == "vCont?") {
        _transport.writePacket("vCont;c;C;s;S;t");
        return true;
    }

    if (payload == "vCtrlC") {
        setLastStopReply("S02");
        _transport.writePacket(_last_stop_reply);
        return true;
    }

    if (payload.starts_with("vCont;")) {
        return handleVCont(payload);
    }

    if (payload.starts_with("qXfer:features:read:target.xml:")) {
        return handleQueryPacket(payload);
    }

    if (payload == "!") {
        _transport.writePacket("OK");
        return true;
    }

    if (payload == "D") {
        _transport.writePacket("OK");
        should_exit = true;
        return true;
    }

    if (payload == "k") {
        should_exit = true;
        return true;
    }

    _transport.writePacket("");
    return true;
}

bool DebugServer::handleQueryPacket(const std::string& payload) {
    const std::string prefix = "qXfer:features:read:target.xml:";
    if (!payload.starts_with(prefix)) {
        _transport.writePacket("");
        return true;
    }

    const std::string tail = payload.substr(prefix.size());
    const size_t comma = tail.find(',');
    if (comma == std::string::npos) {
        _transport.writePacket("E01");
        return false;
    }

    uint64_t offset = 0;
    uint64_t length = 0;
    if (!parseHexU64(tail.substr(0, comma), offset) ||
        !parseHexU64(tail.substr(comma + 1), length)) {
        _transport.writePacket("E01");
        return false;
    }

    const std::string xml = targetXml();
    if (offset >= xml.size()) {
        _transport.writePacket("l");
        return true;
    }

    const size_t start = static_cast<size_t>(offset);
    const size_t span = static_cast<size_t>(std::min<uint64_t>(length, xml.size() - start));
    const std::string chunk = xml.substr(start, span);
    const bool end = (start + span) >= xml.size();
    _transport.writePacket(std::string(end ? "l" : "m") + chunk);
    return true;
}

bool DebugServer::handleSetBreakpoint(const std::string& payload) {
    const size_t comma = payload.find(',');
    if (comma == std::string::npos) {
        _transport.writePacket("E01");
        return false;
    }
    uint64_t addr = 0;
    if (!parseHexU64(payload.substr(0, comma), addr)) {
        _transport.writePacket("E01");
        return false;
    }
    _breakpoints.insert(addr);
    _transport.writePacket("OK");
    return true;
}

bool DebugServer::handleClearBreakpoint(const std::string& payload) {
    const size_t comma = payload.find(',');
    if (comma == std::string::npos) {
        _transport.writePacket("E01");
        return false;
    }
    uint64_t addr = 0;
    if (!parseHexU64(payload.substr(0, comma), addr)) {
        _transport.writePacket("E01");
        return false;
    }
    _breakpoints.erase(addr);
    _transport.writePacket("OK");
    return true;
}

bool DebugServer::handleReadMemory(const std::string& payload) {
    const size_t comma = payload.find(',');
    if (comma == std::string::npos) {
        _transport.writePacket("E01");
        return false;
    }

    uint64_t addr = 0;
    uint64_t length = 0;
    if (!parseHexU64(payload.substr(0, comma), addr) ||
        !parseHexU64(payload.substr(comma + 1), length)) {
        _transport.writePacket("E01");
        return false;
    }

    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (uint64_t i = 0; i < length; ++i) {
        out << std::setw(2) << static_cast<unsigned>(_runtime.memoryRead8(addr + i));
    }
    _transport.writePacket(out.str());
    return true;
}

bool DebugServer::handleContinue(const std::string& payload) {
    if (payload.size() > 1) {
        uint64_t new_pc = 0;
        if (!parseHexU64(payload.substr(1), new_pc)) {
            _transport.writePacket("E01");
            return false;
        }
    }

    while (_runtime.isRunning()) {
        if (_breakpoints.contains(_runtime.pc())) {
            setLastStopReply("S05");
            _transport.writePacket(_last_stop_reply);
            return true;
        }

        _runtime.cycle();

        if (_transport.pollInterrupt()) {
            setLastStopReply("S02");
            _transport.writePacket(_last_stop_reply);
            return true;
        }
    }

    setLastStopReply("W00");
    _transport.writePacket(_last_stop_reply);
    return true;
}

bool DebugServer::handleStep(const std::string& payload) {
    if (payload.size() > 1) {
        uint64_t new_pc = 0;
        if (!parseHexU64(payload.substr(1), new_pc)) {
            _transport.writePacket("E01");
            return false;
        }
    }

    if (_runtime.isRunning()) {
        _runtime.cycle();
    }
    setLastStopReply(_runtime.isRunning() ? "S05" : "W00");
    _transport.writePacket(_last_stop_reply);
    return true;
}

bool DebugServer::handleVCont(const std::string& payload) {
    if (!payload.starts_with("vCont;")) {
        _transport.writePacket("E01");
        return false;
    }

    const std::string actions = payload.substr(6);
    if (actions.empty()) {
        _transport.writePacket("E01");
        return false;
    }

    size_t start = 0;
    while (start < actions.size()) {
        const size_t end = actions.find(';', start);
        const std::string action = actions.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (!action.empty()) {
            const char kind = action[0];
            if (kind == 'c' || kind == 'C') {
                return handleContinue("c");
            }
            if (kind == 's' || kind == 'S') {
                return handleStep("s");
            }
            if (kind == 't' || kind == 'T') {
                setLastStopReply("S02");
                _transport.writePacket(_last_stop_reply);
                return true;
            }
        }

        if (end == std::string::npos) {
            break;
        }
        start = end + 1;
    }

    _transport.writePacket("E01");
    return false;
}

void DebugServer::setLastStopReply(const std::string& reply) {
    if (reply.size() == 3 && reply[0] == 'S') {
        _last_stop_reply = "T" + reply.substr(1) + "thread:1;threads:1;";
        return;
    }
    _last_stop_reply = reply;
}

std::string DebugServer::registerPayload() const {
    const RegisterSnapshot snapshot = _runtime.registers();
    std::string out;
    out.reserve((16 + 1) * 16);
    for (int i = 0; i < 16; ++i) {
        out += encodeHexU64LE(snapshot.gpr[i]);
    }
    out += encodeHexU64LE(snapshot.flags);
    return out;
}

std::string DebugServer::targetXml() const {
    return R"(<?xml version="1.0"?>
<!DOCTYPE target SYSTEM "gdb-target.dtd">
<target>
  <architecture>little64</architecture>
  <feature name="org.gnu.gdb.little64.core">
    <reg name="r0" bitsize="64" regnum="0"/>
    <reg name="r1" bitsize="64" regnum="1"/>
    <reg name="r2" bitsize="64" regnum="2"/>
    <reg name="r3" bitsize="64" regnum="3"/>
    <reg name="r4" bitsize="64" regnum="4"/>
    <reg name="r5" bitsize="64" regnum="5"/>
    <reg name="r6" bitsize="64" regnum="6"/>
    <reg name="r7" bitsize="64" regnum="7"/>
    <reg name="r8" bitsize="64" regnum="8"/>
    <reg name="r9" bitsize="64" regnum="9"/>
    <reg name="r10" bitsize="64" regnum="10"/>
    <reg name="r11" bitsize="64" regnum="11"/>
    <reg name="r12" bitsize="64" regnum="12"/>
    <reg name="sp" bitsize="64" regnum="13"/>
    <reg name="lr" bitsize="64" regnum="14"/>
    <reg name="pc" bitsize="64" regnum="15"/>
    <reg name="flags" bitsize="64" regnum="16"/>
  </feature>
</target>
)";
}

bool DebugServer::parseHexU64(const std::string& text, uint64_t& out) {
    if (text.empty()) {
        return false;
    }
    const char* begin = text.data();
    const char* end = text.data() + text.size();
    auto [ptr, ec] = std::from_chars(begin, end, out, 16);
    return ec == std::errc() && ptr == end;
}

std::string DebugServer::encodeHexU64LE(uint64_t value) {
    std::string out;
    out.reserve(16);
    for (int i = 0; i < 8; ++i) {
        const uint8_t b = static_cast<uint8_t>((value >> (i * 8)) & 0xFFu);
        out += encodeHexByte(b);
    }
    return out;
}

std::string DebugServer::encodeHexByte(uint8_t value) {
    std::ostringstream out;
    out << std::hex << std::nouppercase << std::setw(2) << std::setfill('0')
        << static_cast<unsigned>(value);
    return out.str();
}
