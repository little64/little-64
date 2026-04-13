#include "pv_block_device.hpp"

#include "memory_bus.hpp"

#include <algorithm>
#include <cstring>

PvBlockDevice::PvBlockDevice(uint64_t base, std::unique_ptr<DiskImage> image,
                             std::string_view name, uint64_t irq_line)
    : Device(base, 0x100), _name(name), _image(std::move(image)) {
    setInterruptLine(static_cast<int>(irq_line));
    _bounce.resize(static_cast<size_t>(_max_sectors_per_request * DiskImage::kSectorSize), 0);
    reset();
}

void PvBlockDevice::reset() {
    _request_addr = 0;
    _status = kStatusReady;
    _last_error.clear();
    clearInterruptLine();
}

uint8_t PvBlockDevice::read8(uint64_t addr) {
    return static_cast<uint8_t>((read64(addr & ~0x7ULL) >> ((addr & 0x7ULL) * 8)) & 0xFFULL);
}

void PvBlockDevice::write8(uint64_t addr, uint8_t value) {
    const uint64_t aligned = addr & ~0x7ULL;
    const uint64_t shift = (addr & 0x7ULL) * 8;
    uint64_t current = read64(aligned);
    current &= ~(0xFFULL << shift);
    current |= static_cast<uint64_t>(value) << shift;
    write64(aligned, current);
}

uint64_t PvBlockDevice::read64(uint64_t addr) {
    switch (static_cast<RegisterOffset>(addr - base())) {
        case RegisterOffset::Magic:
            return kMagic;
        case RegisterOffset::Version:
            return kVersion;
        case RegisterOffset::SectorSize:
            return DiskImage::kSectorSize;
        case RegisterOffset::SectorCount:
            return _image ? _image->sectorCount() : 0;
        case RegisterOffset::MaxSectorsPerRequest:
            return _max_sectors_per_request;
        case RegisterOffset::Features: {
            uint64_t features = kFeatureFlush;
            if (_image && _image->isReadOnly()) {
                features |= kFeatureReadOnly;
            }
            return features;
        }
        case RegisterOffset::Status:
            return _status;
        case RegisterOffset::RequestAddress:
            return _request_addr;
        case RegisterOffset::Kick:
        case RegisterOffset::InterruptAck:
            return 0;
        default:
            return 0;
    }
}

void PvBlockDevice::write64(uint64_t addr, uint64_t value) {
    switch (static_cast<RegisterOffset>(addr - base())) {
        case RegisterOffset::RequestAddress:
            _request_addr = value;
            break;
        case RegisterOffset::Kick:
            if (value == 1) {
                _submitRequest();
            }
            break;
        case RegisterOffset::InterruptAck:
            if (value == 1) {
                _clearInterruptPending();
            }
            break;
        default:
            break;
    }
}

bool PvBlockDevice::_readRequestHeader(RequestHeader& header, std::string& error) const {
    if (!_bus) {
        error = "device has no memory bus";
        return false;
    }
    if ((_request_addr & 0x7ULL) != 0) {
        error = "request descriptor address must be 8-byte aligned";
        return false;
    }

    uint64_t* fields = reinterpret_cast<uint64_t*>(&header);
    for (size_t i = 0; i < sizeof(RequestHeader) / sizeof(uint64_t); ++i) {
        fields[i] = _bus->read64(_request_addr + i * sizeof(uint64_t), MemoryAccessType::Read);
    }
    return true;
}

bool PvBlockDevice::_writeRequestStatus(uint64_t request_addr, uint64_t status, std::string& error) {
    if (!_bus) {
        error = "device has no memory bus";
        return false;
    }

    _bus->write64(request_addr + offsetof(RequestHeader, status), status, MemoryAccessType::Write);
    return true;
}

bool PvBlockDevice::_transferBuffer(uint64_t guest_phys, void* host_buffer, size_t len, bool to_guest,
                                    std::string& error) {
    if (!_bus) {
        error = "device has no memory bus";
        return false;
    }

    auto* bytes = static_cast<uint8_t*>(host_buffer);
    for (size_t i = 0; i < len; ++i) {
        if (to_guest) {
            _bus->write8(guest_phys + i, bytes[i], MemoryAccessType::Write);
        } else {
            bytes[i] = _bus->read8(guest_phys + i, MemoryAccessType::Read);
        }
    }
    return true;
}

void PvBlockDevice::_setErrorState() {
    _status |= kStatusError;
    _status &= ~kStatusBusy;
}

void PvBlockDevice::_clearInterruptPending() {
    _status &= ~kStatusInterruptPending;
    clearInterruptLine();
}

void PvBlockDevice::_submitRequest() {
    _status |= kStatusBusy;
    _status &= ~kStatusError;

    RequestHeader header{};
    std::string error;
    uint64_t completion_status = kRequestStatusInvalid;
    uint64_t transfer_bytes = 0;

    if (!_image || !_image->isValid()) {
        error = "no disk image configured";
        goto finish;
    }

    if (!_readRequestHeader(header, error)) {
        goto finish;
    }

    if (header.sector_count > _max_sectors_per_request) {
        error = "request exceeds max sectors per request";
        completion_status = kRequestStatusRangeError;
        goto finish;
    }

    transfer_bytes = header.sector_count * DiskImage::kSectorSize;
    if (header.buffer_len < transfer_bytes) {
        error = "request buffer shorter than sector count";
        completion_status = kRequestStatusInvalid;
        goto finish;
    }
    if (header.sector > _image->sectorCount() || header.sector_count > _image->sectorCount() - header.sector) {
        error = "request beyond end of disk";
        completion_status = kRequestStatusRangeError;
        goto finish;
    }

    switch (header.op) {
        case kRequestRead:
            if (!_image->read(header.sector * DiskImage::kSectorSize, _bounce.data(),
                              static_cast<size_t>(transfer_bytes), &error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            if (!_transferBuffer(header.buffer_phys, _bounce.data(), static_cast<size_t>(transfer_bytes), true, error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            completion_status = kRequestStatusOk;
            break;
        case kRequestWrite:
            if (_image->isReadOnly()) {
                error = "disk image is read-only";
                completion_status = kRequestStatusReadOnly;
                goto finish;
            }
            if (!_transferBuffer(header.buffer_phys, _bounce.data(), static_cast<size_t>(transfer_bytes), false, error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            if (!_image->write(header.sector * DiskImage::kSectorSize, _bounce.data(),
                               static_cast<size_t>(transfer_bytes), &error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            if (!_image->flush(&error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            completion_status = kRequestStatusOk;
            break;
        case kRequestFlush:
            if (!_image->flush(&error)) {
                completion_status = kRequestStatusIoError;
                goto finish;
            }
            completion_status = kRequestStatusOk;
            break;
        default:
            error = "unsupported request opcode";
            completion_status = kRequestStatusUnsupported;
            break;
    }

finish:
    if (!_writeRequestStatus(_request_addr, completion_status, error)) {
        _last_error = error;
        _setErrorState();
    } else if (completion_status != kRequestStatusOk) {
        _last_error = error;
        _setErrorState();
    }

    _status &= ~kStatusBusy;
    _status |= kStatusInterruptPending;
    assertInterruptLine();
}