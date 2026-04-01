#pragma once

#include "../emulator/frontend_api.hpp"

#include <cstdint>
#include <string>

class DebuggerExecutionController {
public:
    explicit DebuggerExecutionController(IEmulatorRuntime& runtime)
        : _runtime(runtime) {}

    void step(std::string* error_text = nullptr) {
        clearError(error_text);
        try {
            _runtime.cycle();
        } catch (const std::exception& e) {
            setError(error_text, e.what());
        }
    }

    void reset() {
        _runtime.reset();
    }

    void assertInterrupt(uint64_t num) {
        _runtime.assertInterrupt(num);
    }

    void runCycles(int cycles, std::string* error_text = nullptr) {
        clearError(error_text);
        try {
            for (int i = 0; i < cycles && _runtime.isRunning(); ++i) {
                _runtime.cycle();
            }
        } catch (const std::exception& e) {
            setError(error_text, e.what());
        }
    }

    bool isRunning() const {
        return _runtime.isRunning();
    }

private:
    static void clearError(std::string* error_text) {
        if (error_text) error_text->clear();
    }

    static void setError(std::string* error_text, const std::string& text) {
        if (error_text) *error_text = text;
    }

    IEmulatorRuntime& _runtime;
};
