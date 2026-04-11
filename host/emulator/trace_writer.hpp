#pragma once

#include <cstdint>
#include <cstddef>
#include <cstring>
#include <string>
#include <vector>
#include <memory>

/// High-performance binary trace event writer (L64T format).
///
/// Format:
///   [Header: 64 bytes] [Event records: 41 bytes each] [Tag table: at EOF]
///   Use l64trace.py to decode.
///
/// Supports cycle-window filtering and file size caps.
class TraceWriter {
public:
    struct Config {
        std::string path;
        uint64_t max_bytes = 0;            // 0 = unlimited
        uint64_t start_cycle = 0;          // skip events before this cycle
        uint64_t end_cycle = UINT64_MAX;   // skip events after this cycle
    };

    explicit TraceWriter(Config config);
    ~TraceWriter();

    TraceWriter(const TraceWriter&) = delete;
    TraceWriter& operator=(const TraceWriter&) = delete;

    bool open();
    void flush();
    void close();
    bool isOpen() const { return _fd >= 0; }

    /// Write a trace event.  Inlined fast-path rejects events outside the
    /// cycle window or after the size cap with zero function-call overhead.
    inline void writeEvent(const char* tag, uint64_t cycle, uint64_t pc,
                           uint64_t a, uint64_t b, uint64_t c) {
        if (__builtin_expect(cycle < _start_cycle, 0)) return;
        if (__builtin_expect(cycle > _end_cycle, 0)) return;
        if (__builtin_expect(_cap_reached, 0)) return;
        _writeEventImpl(tag, cycle, pc, a, b, c);
    }

    /// Async-signal-safe flush: raw write() of current buffer contents.
    void signalFlush() noexcept;

    uint64_t eventsWritten() const { return _events_written; }
    uint64_t eventsDropped() const { return _events_dropped; }
    uint64_t bytesWritten() const { return _bytes_written; }

    /// Print a one-line summary of trace statistics to stderr.
    void printStats() const;

private:
    // Binary format constants
    static constexpr uint8_t kMagic[4] = {'L', '6', '4', 'T'};
    static constexpr uint32_t kFormatVersion = 1;
    static constexpr size_t kHeaderSize = 64;
    static constexpr size_t kBinaryRecordSize = 41; // 1 + 5*8

    // Write buffer (64 KB ≈ 1560 events per flush)
    static constexpr size_t kBufferSize = 64 * 1024;

    void _writeEventImpl(const char* tag, uint64_t cycle, uint64_t pc,
                         uint64_t a, uint64_t b, uint64_t c);

    uint8_t _resolveTagId(const char* tag);
    void _flushBuffer();
    void _writeHeaderPlaceholder();
    void _writeLiveTagTable();
    void _finalizeFile();

    Config _config;
    int _fd = -1;

    // Cycle-window filter values (copied from config for cache locality)
    uint64_t _start_cycle;
    uint64_t _end_cycle;

    // Write buffer
    uint8_t _buffer[kBufferSize];
    size_t _buffer_pos = 0;

    // Statistics
    uint64_t _events_written = 0;
    uint64_t _events_dropped = 0;
    uint64_t _bytes_written = 0;
    bool _cap_reached = false;

    // Tag string → ID mapping (pointer comparison for string literals)
    struct TagEntry {
        const char* ptr;   // string literal pointer
        std::string name;  // copy for file output
    };
    std::vector<TagEntry> _tags;
    size_t _live_tag_count = 0;
    const char* _last_tag_ptr = nullptr;
    uint8_t _last_tag_id = 0;
};
