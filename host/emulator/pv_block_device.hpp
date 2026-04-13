#pragma once

#include "device.hpp"
#include "disk_image.hpp"
#include "interrupt_vectors.hpp"

#include <memory>
#include <string>
#include <string_view>
#include <vector>

class MemoryBus;

class PvBlockDevice : public Device {
public:
    enum class RegisterOffset : uint64_t {
        Magic = 0x00,
        Version = 0x08,
        SectorSize = 0x10,
        SectorCount = 0x18,
        MaxSectorsPerRequest = 0x20,
        Features = 0x28,
        Status = 0x30,
        RequestAddress = 0x38,
        Kick = 0x40,
        InterruptAck = 0x48,
    };

    struct RequestHeader {
        uint64_t op;
        uint64_t status;
        uint64_t sector;
        uint64_t sector_count;
        uint64_t buffer_phys;
        uint64_t buffer_len;
        uint64_t reserved0;
        uint64_t reserved1;
    };

    enum : uint64_t {
        kMagic = 0x4B4C42505634364CULL,
        kVersion = 1,
        kFeatureReadOnly = 1ULL << 0,
        kFeatureFlush = 1ULL << 1,
        kStatusReady = 1ULL << 0,
        kStatusBusy = 1ULL << 1,
        kStatusError = 1ULL << 2,
        kStatusInterruptPending = 1ULL << 3,
        kRequestRead = 0,
        kRequestWrite = 1,
        kRequestFlush = 2,
        kRequestStatusOk = 0,
        kRequestStatusIoError = 1,
        kRequestStatusRangeError = 2,
        kRequestStatusUnsupported = 3,
        kRequestStatusReadOnly = 4,
        kRequestStatusInvalid = 5,
        kDefaultMaxSectorsPerRequest = 128,
    };

    PvBlockDevice(uint64_t base, std::unique_ptr<DiskImage> image,
                  std::string_view name = "PVBLK",
                  uint64_t irq_line = Little64Vectors::kPvBlockIrqVector);

    void setMemoryBus(MemoryBus* bus) { _bus = bus; }
    DiskImage* image() const { return _image.get(); }

    uint8_t read8(uint64_t addr) override;
    void write8(uint64_t addr, uint8_t value) override;
    uint64_t read64(uint64_t addr) override;
    void write64(uint64_t addr, uint64_t value) override;

    void reset() override;
    void tick() override {}

    std::string_view name() const override { return _name; }

private:
    bool _readRequestHeader(RequestHeader& header, std::string& error) const;
    bool _writeRequestStatus(uint64_t request_addr, uint64_t status, std::string& error);
    bool _transferBuffer(uint64_t guest_phys, void* host_buffer, size_t len, bool to_guest, std::string& error);
    void _submitRequest();
    void _setErrorState();
    void _clearInterruptPending();

    std::string _name;
    std::unique_ptr<DiskImage> _image;
    MemoryBus* _bus = nullptr;
    uint64_t _request_addr = 0;
    uint64_t _status = 0;
    uint64_t _max_sectors_per_request = kDefaultMaxSectorsPerRequest;
    std::string _last_error;
    std::vector<uint8_t> _bounce;
};