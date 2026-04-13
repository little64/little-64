#pragma once

#include "device.hpp"
#include "disk_image.hpp"
#include "memory_bus.hpp"
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

class EmulatorClock;  // forward declaration

class MachineConfig {
public:
    using RegionFactory = std::function<std::unique_ptr<MemoryRegion>()>;
    using DeviceFactory = std::function<std::unique_ptr<Device>()>;

    MachineConfig& addRegion(RegionFactory factory);
    MachineConfig& addRam(uint64_t base, uint64_t size, std::string_view name = "RAM");
    MachineConfig& addPreloadedRam(uint64_t base, std::vector<uint8_t> init_data,
                                   uint64_t total_size, std::string_view name = "MEM");
    MachineConfig& addRom(uint64_t base, std::vector<uint8_t> data, std::string_view name = "ROM");
    MachineConfig& addSerial(uint64_t base, std::string_view name = "SERIAL");
    MachineConfig& addTimer(uint64_t base, std::string_view name = "TIMER");
    MachineConfig& addPvBlock(uint64_t base, std::string_view image_path,
                              bool force_read_only = false,
                              std::string_view name = "PVBLK");
    MachineConfig& addDevice(DeviceFactory factory);

    void applyTo(MemoryBus& bus, std::vector<Device*>& devices, InterruptSink* interrupt_sink = nullptr,
                 const EmulatorClock* clock = nullptr) const;

private:
    std::vector<RegionFactory> _region_factories;
    std::vector<DeviceFactory> _device_factories;
};
