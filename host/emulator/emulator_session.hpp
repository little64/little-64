#pragma once

#include "cpu.hpp"
#include "disk_image.hpp"
#include "trace_writer.hpp"
#include "frontend_api.hpp"
#include <cstdint>
#include <string>
#include <vector>

class EmulatorSession : public IEmulatorRuntime {
public:
    EmulatorSession() = default;

    void loadProgram(const std::vector<uint16_t>& words, uint64_t base = 0, uint64_t entry_offset = 0) override;
    bool loadProgramElf(const std::vector<uint8_t>& elf_bytes, uint64_t base = 0) override;
    bool loadProgramElfDirectPaged(const std::vector<uint8_t>& elf_bytes,
                                   uint64_t kernel_physical_base = 0x40000000,
                                   uint64_t direct_map_virtual_base = 0xFFFFFFC000000000ULL) override;
    bool loadProgramLiteXBootRomImage(const std::vector<uint8_t>& bootrom_bytes) override;
    bool loadProgramLiteXFlashImage(const std::vector<uint8_t>& flash_bytes) override;
    void cycle() override;
    void reset() override;
    void assertInterrupt(uint64_t num) override;

    bool isRunning() const override;
    uint64_t pc() const override;
    uint64_t reg(int index) const override;
    RegisterSnapshot registers() const override;

    uint8_t memoryRead8(uint64_t addr) const override;
    std::vector<MemoryRegionView> memoryRegions() const override;

    std::string drainSerialTx() override;

    void setMmioTrace(bool enabled);
    void setControlFlowTrace(bool enabled);
    void setDiskImage(std::unique_ptr<DiskImage> image);
    void dumpBootLog(const char* reason);
    bool setBootEventOutputFile(const std::string& path);
    bool setTraceWriter(std::unique_ptr<TraceWriter> writer);
    bool dumpBootLogToFile(const char* reason, const std::string& path);

private:
    Little64CPU _cpu;
};
