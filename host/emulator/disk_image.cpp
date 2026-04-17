#include "disk_image.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

namespace {

std::string makeIoError(const std::string& path, const char* action) {
    std::ostringstream out;
    out << action << " '" << path << "': " << std::strerror(errno);
    return out.str();
}

bool preadAll(int fd, uint64_t offset, void* dest, size_t len) {
    auto* bytes = static_cast<uint8_t*>(dest);
    size_t total = 0;
    while (total < len) {
        const ssize_t rc = ::pread(fd, bytes + total, len - total,
                                   static_cast<off_t>(offset + total));
        if (rc < 0 && errno == EINTR) {
            continue;
        }
        if (rc < 0) {
            return false;
        }
        if (rc == 0) {
            break;
        }
        total += static_cast<size_t>(rc);
    }
    return true;
}

bool pwriteAll(int fd, uint64_t offset, const void* src, size_t len) {
    const auto* bytes = static_cast<const uint8_t*>(src);
    size_t total = 0;
    while (total < len) {
        const ssize_t rc = ::pwrite(fd, bytes + total, len - total,
                                    static_cast<off_t>(offset + total));
        if (rc < 0 && errno == EINTR) {
            continue;
        }
        if (rc <= 0) {
            return false;
        }
        total += static_cast<size_t>(rc);
    }
    return true;
}

} // namespace

DiskImage::DiskImage(DiskImage&& other) noexcept
    : _path(std::move(other._path)),
      _fd(other._fd),
      _file_size_bytes(other._file_size_bytes),
      _logical_size_bytes(other._logical_size_bytes),
      _read_only(other._read_only),
      _dirty(other._dirty),
      _last_error(std::move(other._last_error)) {
    other._fd = -1;
    other._file_size_bytes = 0;
    other._logical_size_bytes = 0;
    other._read_only = false;
    other._dirty = false;
}

DiskImage& DiskImage::operator=(DiskImage&& other) noexcept {
    if (this == &other) {
        return *this;
    }

    _close();
    _path = std::move(other._path);
    _fd = other._fd;
    _file_size_bytes = other._file_size_bytes;
    _logical_size_bytes = other._logical_size_bytes;
    _read_only = other._read_only;
    _dirty = other._dirty;
    _last_error = std::move(other._last_error);

    other._fd = -1;
    other._file_size_bytes = 0;
    other._logical_size_bytes = 0;
    other._read_only = false;
    other._dirty = false;
    return *this;
}

DiskImage::~DiskImage() {
    _close();
}

std::unique_ptr<DiskImage> DiskImage::open(const std::string& path, bool force_read_only) {
    auto image = std::make_unique<DiskImage>();
    image->_path = path;

    const int open_flags = force_read_only ? O_RDONLY : O_RDWR;
    image->_fd = ::open(path.c_str(), open_flags | O_CLOEXEC);
    if (image->_fd < 0) {
        image->_setError(makeIoError(path, "failed to open disk image"));
        return image;
    }

    struct stat st {};
    if (::fstat(image->_fd, &st) != 0) {
        image->_setError(makeIoError(path, "failed to stat disk image"));
        image->_close();
        return image;
    }

    image->_file_size_bytes = static_cast<uint64_t>(st.st_size);
    image->_logical_size_bytes = _roundUpToSectorSize(image->_file_size_bytes);
    image->_read_only = force_read_only;
    image->_setError({});
    return image;
}

bool DiskImage::read(uint64_t offset, void* dest, size_t len, std::string* error_out) const {
    if (len == 0) {
        return true;
    }

    if (offset > sizeBytes() || len > sizeBytes() - offset) {
        const std::string error = _formatRangeError(offset, len, sizeBytes());
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    std::memset(dest, 0, len);
    if (_fd < 0 || offset >= _file_size_bytes) {
        return true;
    }

    const size_t backed_len = static_cast<size_t>(
        std::min<uint64_t>(static_cast<uint64_t>(len), _file_size_bytes - offset));
    if (!preadAll(_fd, offset, dest, backed_len)) {
        const std::string error = makeIoError(_path, "failed to read disk image");
        if (error_out) {
            *error_out = error;
        }
        return false;
    }
    return true;
}

bool DiskImage::write(uint64_t offset, const void* src, size_t len, std::string* error_out) {
    if (_read_only) {
        const std::string error = "disk image is read-only";
        _setError(error);
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    if (len == 0) {
        return true;
    }

    if (offset > sizeBytes() || len > sizeBytes() - offset) {
        const std::string error = _formatRangeError(offset, len, sizeBytes());
        _setError(error);
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    if (_fd < 0 || !pwriteAll(_fd, offset, src, len)) {
        const std::string error = makeIoError(_path, "failed to write disk image");
        _setError(error);
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    _file_size_bytes = std::max<uint64_t>(_file_size_bytes, offset + len);
    _logical_size_bytes = _roundUpToSectorSize(_file_size_bytes);
    _dirty = true;
    return true;
}

bool DiskImage::flush(std::string* error_out) {
    if (_read_only || !_dirty) {
        return true;
    }

    if (_fd < 0 || ::fsync(_fd) != 0) {
        const std::string error = makeIoError(_path, "failed to flush disk image");
        _setError(error);
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    _dirty = false;
    return true;
}

std::string DiskImage::_formatRangeError(uint64_t offset, size_t len, uint64_t size_bytes) {
    std::ostringstream out;
    out << "disk range out of bounds: offset=0x" << std::hex << offset
        << " len=0x" << len
        << " size=0x" << size_bytes;
    return out.str();
}

uint64_t DiskImage::_roundUpToSectorSize(uint64_t size_bytes) {
    if (size_bytes == 0) {
        return 0;
    }
    return (size_bytes + kSectorSize - 1) & ~(kSectorSize - 1);
}

void DiskImage::_close() {
    if (_fd >= 0) {
        ::close(_fd);
        _fd = -1;
    }
}