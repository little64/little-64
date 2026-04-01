#pragma once

#include "frontend_api.hpp"
#include <cstdint>
#include <string>

struct HeadlessRunOptions {
    bool stream_serial_stdout = true;
    uint64_t max_cycles = 0;
};

bool loadRuntimeImageFromPath(IEmulatorRuntime& runtime, const std::string& path, std::string& error);
int runRuntimeUntilStop(IEmulatorRuntime& runtime, const HeadlessRunOptions& options, std::string& error);
