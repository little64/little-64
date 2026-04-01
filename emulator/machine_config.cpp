#include "machine_config.hpp"

#include "ram_region.hpp"
#include "rom_region.hpp"
#include "serial_device.hpp"

MachineConfig& MachineConfig::addRegion(RegionFactory factory) {
    _region_factories.push_back(std::move(factory));
    return *this;
}

MachineConfig& MachineConfig::addRam(uint64_t base, uint64_t size, std::string_view name) {
    std::string region_name(name);
    return addRegion([base, size, region_name]() {
        return std::make_unique<RamRegion>(base, size, region_name);
    });
}

MachineConfig& MachineConfig::addPreloadedRam(uint64_t base, std::vector<uint8_t> init_data,
                                               uint64_t total_size, std::string_view name) {
    std::string region_name(name);
    return addRegion([base, init_data = std::move(init_data), total_size, region_name]() mutable {
        return std::make_unique<RamRegion>(base, std::move(init_data), total_size, region_name);
    });
}

MachineConfig& MachineConfig::addRom(uint64_t base, std::vector<uint8_t> data, std::string_view name) {
    std::string region_name(name);
    return addRegion([base, data = std::move(data), region_name]() mutable {
        return std::make_unique<RomRegion>(base, std::move(data), region_name);
    });
}

MachineConfig& MachineConfig::addSerial(uint64_t base, std::string_view name) {
    std::string region_name(name);
    return addRegion([base, region_name]() {
        return std::make_unique<SerialDevice>(base, region_name);
    });
}

void MachineConfig::applyTo(MemoryBus& bus, std::vector<Device*>& devices) const {
    bus.clearRegions();
    devices.clear();

    for (const auto& factory : _region_factories) {
        std::unique_ptr<MemoryRegion> region = factory();
        if (auto* dev = dynamic_cast<Device*>(region.get())) {
            devices.push_back(dev);
        }
        bus.addRegion(std::move(region));
    }
}
