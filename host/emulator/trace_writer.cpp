#include "trace_writer.hpp"

#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <csignal>
#include <fcntl.h>
#include <unistd.h>

// ---------------------------------------------------------------------------
// Crash-safe flush: global pointer for async-signal-safe buffer drain
// ---------------------------------------------------------------------------
static TraceWriter* g_crash_flush_writer = nullptr;

static void crashSignalHandler(int sig) {
    if (g_crash_flush_writer) {
        g_crash_flush_writer->signalFlush();
        g_crash_flush_writer = nullptr;
    }
    // Restore default and re-raise
    signal(sig, SIG_DFL);
    raise(sig);
}

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------

TraceWriter::TraceWriter(Config config)
    : _config(std::move(config)),
      _start_cycle(_config.start_cycle),
      _end_cycle(_config.end_cycle) {}

TraceWriter::~TraceWriter() {
    close();
}

// ---------------------------------------------------------------------------
// Open / close
// ---------------------------------------------------------------------------

bool TraceWriter::open() {
    if (_fd >= 0) return true;

    _fd = ::open(_config.path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (_fd < 0) return false;

    _buffer_pos = 0;
    _events_written = 0;
    _events_dropped = 0;
    _bytes_written = 0;
    _cap_reached = false;
    _tags.clear();
    _live_tag_count = 0;
    _last_tag_ptr = nullptr;

    _writeHeaderPlaceholder();

    // Install crash handlers so the buffer is flushed on SIGSEGV/SIGABRT.
    g_crash_flush_writer = this;
    struct sigaction sa{};
    sa.sa_handler = crashSignalHandler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_RESETHAND; // one-shot
    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGABRT, &sa, nullptr);

    return true;
}

void TraceWriter::close() {
    if (_fd < 0) return;

    _flushBuffer();
    _finalizeFile();

    if (g_crash_flush_writer == this) {
        g_crash_flush_writer = nullptr;
    }

    ::close(_fd);
    _fd = -1;
}

void TraceWriter::flush() {
    _flushBuffer();
}

void TraceWriter::signalFlush() noexcept {
    // Async-signal-safe: raw write(), no allocations.
    if (_fd >= 0 && _buffer_pos > 0) {
        (void)::write(_fd, _buffer, _buffer_pos);
        _buffer_pos = 0;
    }
}

// ---------------------------------------------------------------------------
// Tag ID resolution
// ---------------------------------------------------------------------------

uint8_t TraceWriter::_resolveTagId(const char* tag) {
    // Fast path: same tag as last call (common for burst writes)
    if (tag == _last_tag_ptr) return _last_tag_id;

    // Linear scan — typically < 40 entries, pointer compare first
    for (size_t i = 0; i < _tags.size(); ++i) {
        if (_tags[i].ptr == tag) {
            _last_tag_ptr = tag;
            _last_tag_id = static_cast<uint8_t>(i);
            return _last_tag_id;
        }
    }

    // Fallback: strcmp (handles tags from different translation units)
    for (size_t i = 0; i < _tags.size(); ++i) {
        if (_tags[i].name == tag) {
            // Update pointer cache for this tag
            _tags[i].ptr = tag;
            _last_tag_ptr = tag;
            _last_tag_id = static_cast<uint8_t>(i);
            return _last_tag_id;
        }
    }

    // New tag — register it (max 255)
    if (_tags.size() >= 255) {
        _last_tag_ptr = tag;
        _last_tag_id = 255;
        return 255;
    }

    uint8_t id = static_cast<uint8_t>(_tags.size());
    _tags.push_back({tag, std::string(tag)});
    _last_tag_ptr = tag;
    _last_tag_id = id;
    return id;
}

// ---------------------------------------------------------------------------
// Event writing
// ---------------------------------------------------------------------------

void TraceWriter::_writeEventImpl(const char* tag, uint64_t cycle, uint64_t pc,
                                  uint64_t a, uint64_t b, uint64_t c) {
    // Size cap check (approximate — checked per event, updated per flush)
    if (_config.max_bytes > 0 &&
        _bytes_written + _buffer_pos >= _config.max_bytes) {
        _cap_reached = true;
        ++_events_dropped;
        return;
    }

    uint8_t tag_id = _resolveTagId(tag);

    if (_buffer_pos + kBinaryRecordSize > kBufferSize) {
        _flushBuffer();
    }

    uint8_t* p = _buffer + _buffer_pos;
    *p = tag_id;                    p += 1;
    std::memcpy(p, &cycle, 8);      p += 8;
    std::memcpy(p, &pc, 8);         p += 8;
    std::memcpy(p, &a, 8);          p += 8;
    std::memcpy(p, &b, 8);          p += 8;
    std::memcpy(p, &c, 8);

    _buffer_pos += kBinaryRecordSize;

    ++_events_written;
}

// ---------------------------------------------------------------------------
// Buffer management
// ---------------------------------------------------------------------------

void TraceWriter::_flushBuffer() {
    if (_fd < 0 || _buffer_pos == 0) return;

    ssize_t written = ::write(_fd, _buffer, _buffer_pos);
    if (written > 0) {
        _bytes_written += static_cast<uint64_t>(written);
    }
    _buffer_pos = 0;

    // Update the on-disk tag table + header so live watchers can decode tags.
    // The tag table is written just past the events; the next flush will
    // overwrite it with new event data, then append a fresh tag table.
    if (!_tags.empty()) {
        _writeLiveTagTable();
    }
}

// ---------------------------------------------------------------------------
// Binary format: header and tag table
// ---------------------------------------------------------------------------

void TraceWriter::_writeHeaderPlaceholder() {
    // Write 64 bytes of zeros — will be overwritten on close().
    uint8_t header[kHeaderSize];
    std::memset(header, 0, kHeaderSize);

    // Write magic + version so partial files are identifiable
    std::memcpy(header + 0, kMagic, 4);
    uint32_t ver = kFormatVersion;
    std::memcpy(header + 4, &ver, 4);

    // events_offset = 64 (events start right after header)
    uint64_t events_offset = kHeaderSize;
    std::memcpy(header + 40, &events_offset, 8);

    (void)::write(_fd, header, kHeaderSize);
    _bytes_written += kHeaderSize;
}

void TraceWriter::_writeLiveTagTable() {
    // Write the tag table at the current position (just past events).
    uint64_t tag_table_offset = _bytes_written;

    // Batch the tag entries into a single write to minimise syscall overhead
    // (this is called on every flush, not just when new tags appear).
    uint8_t tag_buf[4096];
    size_t tag_pos = 0;
    for (const auto& entry : _tags) {
        uint8_t name_len = static_cast<uint8_t>(
            std::min<size_t>(entry.name.size(), 255));
        if (tag_pos + 1 + name_len > sizeof(tag_buf)) break;
        tag_buf[tag_pos++] = name_len;
        std::memcpy(tag_buf + tag_pos, entry.name.data(), name_len);
        tag_pos += name_len;
    }
    (void)::write(_fd, tag_buf, tag_pos);

    // Update the header with current counts so watchers see tag info.
    if (::lseek(_fd, 0, SEEK_SET) < 0) return;

    uint8_t header[kHeaderSize];
    std::memset(header, 0, kHeaderSize);
    std::memcpy(header + 0, kMagic, 4);
    uint32_t ver = kFormatVersion;
    std::memcpy(header + 4, &ver, 4);
    uint32_t tag_count = static_cast<uint32_t>(_tags.size());
    std::memcpy(header + 12, &tag_count, 4);
    std::memcpy(header + 16, &_events_written, 8);
    uint64_t total = _events_written + _events_dropped;
    std::memcpy(header + 24, &total, 8);
    std::memcpy(header + 32, &tag_table_offset, 8);
    uint64_t events_offset = kHeaderSize;
    std::memcpy(header + 40, &events_offset, 8);
    (void)::write(_fd, header, kHeaderSize);

    // Seek back to events end.  The next flush will overwrite the tag table
    // with fresh event data, then append a new tag table.
    (void)::lseek(_fd, static_cast<off_t>(_bytes_written), SEEK_SET);

    _live_tag_count = _tags.size();
}

void TraceWriter::_finalizeFile() {
    // Seek to events end to ensure correct position after any live tag table.
    (void)::lseek(_fd, static_cast<off_t>(_bytes_written), SEEK_SET);

    // 1. Remember where the tag table starts
    uint64_t tag_table_offset = _bytes_written;

    // 2. Write tag table
    for (const auto& entry : _tags) {
        uint8_t name_len = static_cast<uint8_t>(
            entry.name.size() > 255 ? 255 : entry.name.size());
        (void)::write(_fd, &name_len, 1);
        (void)::write(_fd, entry.name.data(), name_len);
    }

    // 3. Seek to start and write final header
    if (::lseek(_fd, 0, SEEK_SET) < 0) return;

    uint8_t header[kHeaderSize];
    std::memset(header, 0, kHeaderSize);

    std::memcpy(header + 0, kMagic, 4);

    uint32_t ver = kFormatVersion;
    std::memcpy(header + 4, &ver, 4);

    uint32_t flags = 0;
    std::memcpy(header + 8, &flags, 4);

    uint32_t tag_count = static_cast<uint32_t>(_tags.size());
    std::memcpy(header + 12, &tag_count, 4);

    std::memcpy(header + 16, &_events_written, 8);

    uint64_t total = _events_written + _events_dropped;
    std::memcpy(header + 24, &total, 8);

    std::memcpy(header + 32, &tag_table_offset, 8);

    uint64_t events_offset = kHeaderSize;
    std::memcpy(header + 40, &events_offset, 8);

    (void)::write(_fd, header, kHeaderSize);
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

void TraceWriter::printStats() const {
    double mb = static_cast<double>(_bytes_written) / (1024.0 * 1024.0);

    if (_events_dropped > 0) {
        std::fprintf(stderr,
            "[little64] trace: %" PRIu64 " events written (%.1f MB), "
            "%" PRIu64 " events dropped (cap reached)\n",
            _events_written, mb, _events_dropped);
    } else {
        std::fprintf(stderr,
            "[little64] trace: %" PRIu64 " events written (%.1f MB)\n",
            _events_written, mb);
    }

    std::fprintf(stderr, "[little64] trace: file=%s\n",
                 _config.path.c_str());
}
