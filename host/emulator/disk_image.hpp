#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

class DiskImage {
public:
    static constexpr uint64_t kSectorSize = 512;

    static std::unique_ptr<DiskImage> open(const std::string& path, bool force_read_only = false);

    DiskImage() = default;
    DiskImage(const DiskImage&) = delete;
    DiskImage& operator=(const DiskImage&) = delete;
    DiskImage(DiskImage&& other) noexcept;
    DiskImage& operator=(DiskImage&& other) noexcept;
    ~DiskImage();

    bool isValid() const { return _fd >= 0; }
    bool isReadOnly() const { return _read_only; }
    const std::string& path() const { return _path; }
    const std::string& lastError() const { return _last_error; }

    uint64_t sizeBytes() const { return _logical_size_bytes; }
    uint64_t sectorCount() const { return sizeBytes() / kSectorSize; }

    bool read(uint64_t offset, void* dest, size_t len, std::string* error_out = nullptr) const;
    bool write(uint64_t offset, const void* src, size_t len, std::string* error_out = nullptr);
    bool flush(std::string* error_out = nullptr);

private:
    std::string _path;
    int _fd = -1;
    uint64_t _file_size_bytes = 0;
    uint64_t _logical_size_bytes = 0;
    bool _read_only = false;
    bool _dirty = false;
    std::string _last_error;

    static std::string _formatRangeError(uint64_t offset, size_t len, uint64_t size_bytes);
    static uint64_t _roundUpToSectorSize(uint64_t size_bytes);
    void _close();
    void _setError(std::string error) { _last_error = std::move(error); }
};