#include "disk_image.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <sstream>

namespace {

std::string makeIoError(const std::string& path, const char* action) {
    std::ostringstream out;
    out << action << " '" << path << "': " << std::strerror(errno);
    return out.str();
}

} // namespace

std::unique_ptr<DiskImage> DiskImage::open(const std::string& path, bool force_read_only) {
    auto image = std::make_unique<DiskImage>();
    image->_path = path;

    std::ifstream in(path, std::ios::binary);
    if (!in.is_open()) {
        image->_setError(makeIoError(path, "failed to open disk image"));
        return image;
    }

    image->_bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    if (!in.good() && !in.eof()) {
        image->_setError(makeIoError(path, "failed to read disk image"));
        return image;
    }

    if ((image->_bytes.size() % kSectorSize) != 0) {
        image->_bytes.resize((image->_bytes.size() + kSectorSize - 1) & ~(kSectorSize - 1), 0);
    }

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

    std::memcpy(dest, _bytes.data() + offset, len);
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

    std::memcpy(_bytes.data() + offset, src, len);
    _dirty = true;
    return true;
}

bool DiskImage::flush(std::string* error_out) {
    if (_read_only || !_dirty) {
        return true;
    }

    std::ofstream out(_path, std::ios::binary | std::ios::trunc);
    if (!out.is_open()) {
        const std::string error = makeIoError(_path, "failed to write disk image");
        _setError(error);
        if (error_out) {
            *error_out = error;
        }
        return false;
    }

    out.write(reinterpret_cast<const char*>(_bytes.data()), static_cast<std::streamsize>(_bytes.size()));
    if (!out.good()) {
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