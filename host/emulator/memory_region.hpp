#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <string_view>

enum class MemoryAccessType : uint8_t {
    Read,
    Write,
    Execute,
};

class MemoryRegion {
public:
    virtual ~MemoryRegion() = default;

    virtual uint8_t read8(uint64_t addr) = 0;
    virtual void    write8(uint64_t addr, uint8_t val) = 0;

    // Default wide-access implementations compose read8/write8 in little-endian order.
    // Subclasses may override with memcpy for performance (e.g. RamRegion, RomRegion).
    virtual uint16_t read16(uint64_t addr);
    virtual void     write16(uint64_t addr, uint16_t val);
    virtual uint32_t read32(uint64_t addr);
    virtual void     write32(uint64_t addr, uint32_t val);
    virtual uint64_t read64(uint64_t addr);
    virtual void     write64(uint64_t addr, uint64_t val);

    virtual bool allows(uint64_t addr, size_t width, MemoryAccessType access) const;

    virtual std::string_view name() const = 0;

    // Access notification hooks for MMIO tracing.  No-op by default;
    // Device overrides these so MemoryBus never needs dynamic_cast.
    virtual void notifyRead(uint64_t /*addr*/, size_t /*width*/, uint64_t /*value*/) const {}
    virtual void notifyWrite(uint64_t /*addr*/, size_t /*width*/, uint64_t /*value*/) const {}

    // Fast non-virtual check: does this region want notifyRead/notifyWrite calls?
    bool wantsAccessNotification() const { return _notify_access; }

    uint64_t base() const { return _base; }
    uint64_t size() const { return _size; }
    uint64_t end()  const { return _base + _size; }  // exclusive

protected:
    MemoryRegion(uint64_t base, uint64_t size) : _base(base), _size(size) {}

    void setNotifyAccess(bool v) { _notify_access = v; }

    uint64_t _base;
    uint64_t _size;

private:
    bool _notify_access = false;
};
