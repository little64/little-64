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

MachineConfig& MachineConfig::addDevice(DeviceFactory factory) {
    _device_factories.push_back(std::move(factory));
    return *this;
}

MachineConfig& MachineConfig::addSerial(uint64_t base, std::string_view name) {
    std::string region_name(name);
    return addDevice([base, region_name]() {
        return std::make_unique<SerialDevice>(base, region_name);
    });
}

void MachineConfig::applyTo(MemoryBus& bus, std::vector<Device*>& devices, InterruptSink* interrupt_sink) const {
    bus.clearRegions();
    devices.clear();

    for (const auto& factory : _region_factories) {
        std::unique_ptr<MemoryRegion> region = factory();
        bus.addRegion(std::move(region));
    }

    for (const auto& factory : _device_factories) {
        std::unique_ptr<Device> device = factory();
        if (interrupt_sink) {
            device->connectInterruptSink(interrupt_sink);
        }
        devices.push_back(device.get());
        std::unique_ptr<MemoryRegion> region(std::move(device));
        bus.addRegion(std::move(region));
    }
}
