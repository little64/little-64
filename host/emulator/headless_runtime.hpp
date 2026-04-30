#pragma once

#include "frontend_api.hpp"
#include <csignal>
#include <cstdint>
#include <string>
#include <string>

struct HeadlessRunOptions {
    bool stream_serial_stdout = true;
    uint64_t max_cycles = 0;
    const volatile std::sig_atomic_t* stop_signal = nullptr;
};

enum class HeadlessBootMode {
    Auto,
    Bios,
    Direct,
    LiteXBootRom,
    LiteXFlash,
};

struct HeadlessLoadOptions {
    HeadlessBootMode boot_mode = HeadlessBootMode::Auto;
    uint64_t direct_kernel_physical_base = 0x40000000;
    std::string direct_dtb_path;
    uint64_t direct_stack_reserve_bytes = 0;
    // Note: direct_map_virtual_base is no longer used by the direct boot mode
    // (Linux kernels manage their own page tables)
};

bool loadRuntimeImageFromPath(IEmulatorRuntime& runtime,
                              const std::string& path,
                              std::string& error,
                              const HeadlessLoadOptions& options = HeadlessLoadOptions{});
int runRuntimeUntilStop(IEmulatorRuntime& runtime, const HeadlessRunOptions& options, std::string& error);
