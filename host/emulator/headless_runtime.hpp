#pragma once

#include "frontend_api.hpp"
#include <cstdint>
#include <string>

struct HeadlessRunOptions {
    bool stream_serial_stdout = true;
    uint64_t max_cycles = 0;
};

enum class HeadlessBootMode {
    Auto,
    Bios,
    Direct,
};

struct HeadlessLoadOptions {
    HeadlessBootMode boot_mode = HeadlessBootMode::Auto;
    uint64_t direct_kernel_physical_base = 0x100000;
    uint64_t direct_map_virtual_base = 0xFFFFFFC000000000ULL;
};

bool loadRuntimeImageFromPath(IEmulatorRuntime& runtime,
                              const std::string& path,
                              std::string& error,
                              const HeadlessLoadOptions& options = HeadlessLoadOptions{});
int runRuntimeUntilStop(IEmulatorRuntime& runtime, const HeadlessRunOptions& options, std::string& error);
