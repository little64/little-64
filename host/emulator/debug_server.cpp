#include "debug_server.hpp"
#include "register_layout.hpp"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <iomanip>
#include <sstream>
#include <string>

namespace {

constexpr uint64_t kGeneralPurposeRegisterCount = Little64RegisterLayout::kGeneralPurposeRegisterCount;
constexpr uint64_t kFlagsRegisterIndex = Little64RegisterLayout::kFlagsIndex;
constexpr uint64_t kFirstSpecialRegisterIndex = Little64RegisterLayout::kFirstSpecialRegisterIndex;
constexpr uint64_t kTotalRegisterCount = Little64RegisterLayout::kTotalRegisterCount;
constexpr size_t kHexCharsPerEncodedRegister = sizeof(uint64_t) * 2;

std::string encodeHexByteLocal(uint8_t value) {
    std::ostringstream out;
    out << std::hex << std::nouppercase << std::setw(2) << std::setfill('0')
        << static_cast<unsigned>(value);
    return out.str();
}

std::string encodeHexU64LELocal(uint64_t value) {
    std::string out;
    out.reserve(kHexCharsPerEncodedRegister);
    for (int i = 0; i < 8; ++i) {
        const uint8_t b = static_cast<uint8_t>((value >> (i * 8)) & 0xFFu);
        out += encodeHexByteLocal(b);
    }
    return out;
}

std::string registerNameForIndex(uint64_t reg_index) {
    if (reg_index < kGeneralPurposeRegisterCount) {
        switch (reg_index) {
            case Little64RegisterLayout::kStackPointerIndex: return "sp";
            case Little64RegisterLayout::kLinkRegisterIndex: return "lr";
            case Little64RegisterLayout::kProgramCounterIndex: return "pc";
            default: return "r" + std::to_string(reg_index);
        }
    }

    if (reg_index == kFlagsRegisterIndex) {
        return "flags";
    }

    const uint64_t selector = Little64SpecialRegisters::selectorForDebugOrdinal(
        reg_index - kFirstSpecialRegisterIndex);
    if (selector == Little64SpecialRegisters::kUserThreadPointer) {
        return "utp";
    }

    return "sr" + std::to_string(selector);
}

const char* altNameForRegisterIndex(uint64_t reg_index) {
    switch (reg_index) {
        case Little64RegisterLayout::kFramePointerIndex: return "fp";
        case Little64RegisterLayout::kLinkRegisterIndex: return "ra";
        default: break;
    }

    if (reg_index >= kFirstSpecialRegisterIndex) {
        const uint64_t selector = Little64SpecialRegisters::selectorForDebugOrdinal(
            reg_index - kFirstSpecialRegisterIndex);
        return Little64SpecialRegisters::nameForSelector(selector);
    }

    return nullptr;
}

const char* genericRoleForRegisterIndex(uint64_t reg_index) {
    switch (reg_index) {
        case Little64RegisterLayout::kArgument5Index: return "arg5";
        case Little64RegisterLayout::kArgument4Index: return "arg4";
        case Little64RegisterLayout::kArgument3Index: return "arg3";
        case Little64RegisterLayout::kArgument2Index: return "arg2";
        case Little64RegisterLayout::kArgument1Index: return "arg1";
        case Little64RegisterLayout::kFramePointerIndex: return "fp";
        case Little64RegisterLayout::kStackPointerIndex: return "sp";
        case Little64RegisterLayout::kLinkRegisterIndex: return "ra";
        case Little64RegisterLayout::kProgramCounterIndex: return "pc";
        case kFlagsRegisterIndex: return "flags";
        default: return nullptr;
    }
}

void appendStopReplyRegisterFields(std::ostringstream& out, const RegisterSnapshot& snapshot) {
    for (uint64_t reg_index = 0; reg_index < kGeneralPurposeRegisterCount; ++reg_index) {
        out << std::hex << reg_index << ":"
            << encodeHexU64LELocal(snapshot.gpr[static_cast<size_t>(reg_index)]) << ";";
    }

    out << std::hex << kFlagsRegisterIndex << ":" << encodeHexU64LELocal(snapshot.flags) << ";";

    for (uint64_t special_index = 0; special_index < RegisterSnapshot::kSpecialRegisterCount; ++special_index) {
        out << std::hex << (kFirstSpecialRegisterIndex + special_index) << ":"
            << encodeHexU64LELocal(snapshot.getSpecialRegisterByID(special_index)) << ";";
    }
}

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
    : _runtime(runtime), _transport(transport) {
    setLastStopReply("S05");
}

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
        uint64_t query_addr = 0;
        if (!parseHexU64(payload.substr(std::string("qMemoryRegionInfo:").size()), query_addr)) {
            _transport.writePacket("E01");
            return true;
        }

        // Debugging interoperability:
        // Always return a small finite region around the queried address.
        // LLDB expression evaluation can assert if memory-region queries are
        // non-contiguous or alternate between success/failure while it scans.
        const uint64_t start = query_addr & ~0xFFFULL;
        constexpr uint64_t size = 0x1000ULL;
        std::ostringstream out;
        out << std::hex;
        out << "start:" << start << ";size:" << size << ";permissions:rwx;";
        _transport.writePacket(out.str());
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
        _transport.writePacket("");
        return true;
    }

    if (payload.starts_with("jThreadExtendedInfo")) {
        _transport.writePacket("");
        return true;
    }

    if (payload.starts_with("qRegisterInfo")) {
        uint64_t reg_index = 0;
        if (!parseRegisterInfoIndex(payload, reg_index)) {
            _transport.writePacket("E01");
            return true;
        }

        if (reg_index >= kTotalRegisterCount) {
            _transport.writePacket("E45");
            return true;
        }

        std::ostringstream out;
        out << "name:" << registerNameForIndex(reg_index)
            << ";bitsize:64;offset:" << (reg_index * 8)
            << ";encoding:uint;format:hex;set:General Purpose Registers;"
            << "gcc:" << reg_index << ";dwarf:" << reg_index << ";";

        if (const char* alt_name = altNameForRegisterIndex(reg_index)) {
            out << "alt-name:" << alt_name << ";";
        }

        if (const char* generic_role = genericRoleForRegisterIndex(reg_index)) {
            out << "generic:" << generic_role << ";";
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
        if (reg_index < kGeneralPurposeRegisterCount) {
            _transport.writePacket(encodeHexU64LE(snapshot.gpr[static_cast<size_t>(reg_index)]));
            return true;
        }
        if (reg_index == kFlagsRegisterIndex) {
            _transport.writePacket(encodeHexU64LE(snapshot.flags));
            return true;
        }
        if (reg_index >= kFirstSpecialRegisterIndex && reg_index < kTotalRegisterCount) {
            _transport.writePacket(encodeHexU64LE(snapshot.getSpecialRegisterByID(reg_index - kFirstSpecialRegisterIndex)));
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

    bool skip_breakpoint_check_once = false;
    if (_resume_past_breakpoint_once && _runtime.pc() == _resume_breakpoint_pc) {
        skip_breakpoint_check_once = true;
    }
    _resume_past_breakpoint_once = false;

    while (_runtime.isRunning()) {
        uint64_t matched_breakpoint = 0;
        if (!skip_breakpoint_check_once && findMatchingBreakpoint(_runtime.pc(), matched_breakpoint)) {
            setLastStopReplyWithReason("05", "swbreak");
            _transport.writePacket(_last_stop_reply);
            return true;
        }
        skip_breakpoint_check_once = false;

        _runtime.cycle();

        if (!emitSerialOutput()) {
            return false;
        }

        if (_transport.pollInterrupt()) {
            setLastStopReply("S02");
            _transport.writePacket(_last_stop_reply);
            return true;
        }
    }

    if (!emitSerialOutput()) {
        return false;
    }

    // Program-level STOP should behave like a debugger stop, not process exit.
    setLastStopReply("S05");
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

    if (!emitSerialOutput()) {
        return false;
    }

    setLastStopReplyWithReason("05", "trace");
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
    _resume_past_breakpoint_once = false;

    if (reply.size() == 3 && reply[0] == 'S') {
        const RegisterSnapshot snapshot = _runtime.registers();
        std::ostringstream out;
        out << "T" << reply.substr(1) << "thread:1;threads:1;";

        appendStopReplyRegisterFields(out, snapshot);

        _last_stop_reply = out.str();
        return;
    }
    _last_stop_reply = reply;
}

void DebugServer::setLastStopReplyWithReason(const std::string& signal_hex, const std::string& reason_key) {
    if (signal_hex.size() != 2) {
        setLastStopReply("S05");
        return;
    }

    _resume_past_breakpoint_once = false;
    if (reason_key == "swbreak") {
        _resume_past_breakpoint_once = true;
        _resume_breakpoint_pc = _runtime.pc();
    }

    const RegisterSnapshot snapshot = _runtime.registers();
    std::ostringstream out;
    out << "T" << signal_hex << reason_key << ":;thread:1;threads:1;";

    appendStopReplyRegisterFields(out, snapshot);

    _last_stop_reply = out.str();
}

std::string DebugServer::registerPayload() const {
    const RegisterSnapshot snapshot = _runtime.registers();
    std::string out;
    out.reserve(static_cast<size_t>(kTotalRegisterCount) * kHexCharsPerEncodedRegister);
    for (uint64_t reg_index = 0; reg_index < kGeneralPurposeRegisterCount; ++reg_index) {
        out += encodeHexU64LE(snapshot.gpr[static_cast<size_t>(reg_index)]);
    }
    out += encodeHexU64LE(snapshot.flags);
    for (uint64_t special_index = 0; special_index < RegisterSnapshot::kSpecialRegisterCount; ++special_index) {
        out += encodeHexU64LE(snapshot.getSpecialRegisterByID(special_index));
    }
    return out;
}

std::string DebugServer::targetXml() const {
    std::ostringstream out;
    out << R"(<?xml version="1.0"?>
<!DOCTYPE target SYSTEM "gdb-target.dtd">
<target>
  <architecture>little64</architecture>
  <feature name="org.gnu.gdb.little64.core">
)";

    for (uint64_t reg_index = 0; reg_index < kTotalRegisterCount; ++reg_index) {
        out << "        <reg name=\"" << registerNameForIndex(reg_index) << "\"";
        if (const char* alt_name = altNameForRegisterIndex(reg_index)) {
            out << " altname=\"" << alt_name << "\"";
        }
        out << " bitsize=\"64\" regnum=\"" << reg_index
            << "\" dwarf_regnum=\"" << reg_index
            << "\" ehframe_regnum=\"" << reg_index << "\"";
        if (const char* generic_role = genericRoleForRegisterIndex(reg_index)) {
            out << " generic=\"" << generic_role << "\"";
        }
        out << "/>\n";
    }

    out << R"(  </feature>
</target>
)";
    return out.str();
}

bool DebugServer::findMatchingBreakpoint(uint64_t pc, uint64_t& matched_addr) const {
    if (_breakpoints.contains(pc)) {
        matched_addr = pc;
        return true;
    }

    return false;
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

bool DebugServer::emitSerialOutput() {
    const std::string output = _runtime.drainSerialTx();
    if (output.empty()) {
        return true;
    }

    constexpr size_t kChunkBytes = 256;
    size_t offset = 0;
    while (offset < output.size()) {
        const size_t count = std::min(kChunkBytes, output.size() - offset);
        std::string payload;
        payload.reserve(1 + count * 2);
        payload.push_back('O');
        for (size_t i = 0; i < count; ++i) {
            const auto c = static_cast<uint8_t>(output[offset + i]);
            payload += encodeHexByte(c);
        }

        if (!_transport.writePacket(payload)) {
            return false;
        }

        offset += count;
    }

    return true;
}

std::string DebugServer::encodeHexU64LE(uint64_t value) {
    return encodeHexU64LELocal(value);
}

std::string DebugServer::encodeHexByte(uint8_t value) {
    return encodeHexByteLocal(value);
}
