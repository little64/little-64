#include <elf.h>

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <deque>
#include <cstring>
#include <span>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include <verilated.h>

#include "Vlittle64_linux_boot_top.h"
#include "Vlittle64_linux_boot_top___024root.h"

namespace {

namespace fs = std::filesystem;

constexpr uint64_t KERNEL_PHYSICAL_BASE = 0x0010'0000ULL;
constexpr uint64_t RAM_EXTRA_BYTES = 64ULL * 1024ULL * 1024ULL;
constexpr uint64_t PAGE_SIZE = 4096ULL;
constexpr uint64_t EARLY_PT_SCRATCH_PAGES = 30ULL;

constexpr uint64_t UART_BASE = 0x0800'0000ULL;
constexpr uint64_t UART_SIZE = 0x8ULL;
constexpr uint64_t TIMER_BASE = 0x0800'1000ULL;
constexpr uint64_t TIMER_SIZE = 0x20ULL;
constexpr uint64_t PVBLK_BASE = 0x0800'2000ULL;
constexpr uint64_t PVBLK_SIZE = 0x100ULL;

constexpr uint64_t TIMER_IRQ_MASK = 1ULL << 1;
constexpr uint64_t PVBLK_IRQ_MASK = 1ULL << 2;

constexpr uint64_t TIME_SCALE_NS = 10'000ULL;

constexpr uint64_t L64_PVBLK_MAGIC_VALUE = 0x4B4C42505634364CULL;
constexpr uint64_t L64_PVBLK_VERSION_VALUE = 1ULL;
constexpr uint64_t L64_PVBLK_F_READ_ONLY = 1ULL << 0;
constexpr uint64_t L64_PVBLK_S_READY = 1ULL << 0;
constexpr uint64_t L64_PVBLK_S_BUSY = 1ULL << 1;
constexpr uint64_t L64_PVBLK_S_ERROR = 1ULL << 2;
constexpr uint64_t L64_PVBLK_S_IRQ_PENDING = 1ULL << 3;
constexpr uint64_t L64_PVBLK_REQ_READ = 0ULL;
constexpr uint64_t L64_PVBLK_REQ_WRITE = 1ULL;
constexpr uint64_t L64_PVBLK_REQ_FLUSH = 2ULL;
constexpr uint64_t L64_PVBLK_REQ_ST_OK = 0ULL;
constexpr uint64_t L64_PVBLK_REQ_ST_IOERR = 1ULL;
constexpr uint64_t L64_PVBLK_REQ_ST_UNSUPPORTED = 3ULL;
constexpr uint64_t L64_PVBLK_REQ_ST_READ_ONLY = 4ULL;
constexpr uint64_t L64_PVBLK_REQ_ST_INVALID = 5ULL;

uint64_t alignUp(uint64_t value, uint64_t alignment) {
    return (value + alignment - 1) & ~(alignment - 1);
}

bool envFlagEnabled(const char* name) {
    const char* value = std::getenv(name);
    if (value == nullptr) {
        return false;
    }
    return value[0] != '\0' && value[0] != '0';
}

std::vector<uint8_t> readBinaryFile(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("failed to open file: " + path.string());
    }

    stream.seekg(0, std::ios::end);
    const auto size = static_cast<size_t>(stream.tellg());
    stream.seekg(0, std::ios::beg);

    std::vector<uint8_t> bytes(size);
    if (size != 0) {
        stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    }
    return bytes;
}

struct LoadedLinuxImage {
    uint64_t entryPhysical = 0;
    uint64_t virtBase = 0;
    uint64_t virtEnd = 0;
    uint64_t imageSpan = 0;
    uint64_t totalRam = 0;
    std::vector<uint8_t> ramImage;
};

LoadedLinuxImage loadLinuxImage(const fs::path& path) {
    const auto elfBytes = readBinaryFile(path);
    if (elfBytes.size() < sizeof(Elf64_Ehdr)) {
        throw std::runtime_error("ELF image too small: " + path.string());
    }

    const auto* header = reinterpret_cast<const Elf64_Ehdr*>(elfBytes.data());
    if (header->e_ident[EI_MAG0] != ELFMAG0 || header->e_ident[EI_MAG1] != ELFMAG1 ||
        header->e_ident[EI_MAG2] != ELFMAG2 || header->e_ident[EI_MAG3] != ELFMAG3) {
        throw std::runtime_error("unsupported ELF magic: " + path.string());
    }
    if (header->e_ident[EI_CLASS] != ELFCLASS64 || header->e_ident[EI_DATA] != ELFDATA2LSB) {
        throw std::runtime_error("unsupported ELF format: " + path.string());
    }
    if (header->e_phentsize != sizeof(Elf64_Phdr)) {
        throw std::runtime_error("unexpected ELF program-header size");
    }
    if (header->e_phoff + (static_cast<uint64_t>(header->e_phnum) * sizeof(Elf64_Phdr)) > elfBytes.size()) {
        throw std::runtime_error("truncated ELF program headers");
    }

    uint64_t minVaddr = UINT64_MAX;
    uint64_t maxVaddr = 0;
    bool foundLoad = false;

    for (uint16_t index = 0; index < header->e_phnum; ++index) {
        const auto* programHeader = reinterpret_cast<const Elf64_Phdr*>(
            elfBytes.data() + header->e_phoff + (static_cast<uint64_t>(index) * sizeof(Elf64_Phdr))
        );
        if (programHeader->p_type != PT_LOAD) {
            continue;
        }
        if (programHeader->p_offset + programHeader->p_filesz > elfBytes.size()) {
            throw std::runtime_error("ELF segment exceeds file size");
        }
        minVaddr = std::min(minVaddr, programHeader->p_vaddr);
        maxVaddr = std::max(maxVaddr, programHeader->p_vaddr + programHeader->p_memsz);
        foundLoad = true;
    }

    if (!foundLoad) {
        throw std::runtime_error("ELF has no PT_LOAD segments");
    }

    const uint64_t virtBase = minVaddr & ~(PAGE_SIZE - 1ULL);
    const uint64_t imageSpan = alignUp(maxVaddr - virtBase, PAGE_SIZE);
    std::vector<uint8_t> ramImage(static_cast<size_t>(imageSpan), 0);

    for (uint16_t index = 0; index < header->e_phnum; ++index) {
        const auto* programHeader = reinterpret_cast<const Elf64_Phdr*>(
            elfBytes.data() + header->e_phoff + (static_cast<uint64_t>(index) * sizeof(Elf64_Phdr))
        );
        if (programHeader->p_type != PT_LOAD) {
            continue;
        }

        const auto offset = static_cast<size_t>(programHeader->p_vaddr - virtBase);
        std::copy_n(
            elfBytes.data() + programHeader->p_offset,
            static_cast<size_t>(programHeader->p_filesz),
            ramImage.data() + offset
        );
    }

    uint64_t entryPhysical = 0;
    if (header->e_entry >= virtBase && header->e_entry < virtBase + imageSpan) {
        entryPhysical = KERNEL_PHYSICAL_BASE + (header->e_entry - virtBase);
    } else if (header->e_entry >= KERNEL_PHYSICAL_BASE && header->e_entry < KERNEL_PHYSICAL_BASE + imageSpan) {
        entryPhysical = header->e_entry;
    } else {
        throw std::runtime_error("ELF entry point is outside loaded image");
    }

    return LoadedLinuxImage{
        .entryPhysical = entryPhysical,
        .virtBase = virtBase,
        .virtEnd = virtBase + imageSpan,
        .imageSpan = imageSpan,
        .totalRam = imageSpan + RAM_EXTRA_BYTES,
        .ramImage = std::move(ramImage),
    };
}

struct SerialDevice {
    uint8_t dll = 0;
    uint8_t dlm = 0;
    uint8_t ier = 0;
    uint8_t fcr = 0;
    uint8_t lcr = 0;
    uint8_t mcr = 0;
    uint8_t scr = 0;
    std::string output;
    std::string tail;

    void appendOutput(uint8_t value) {
        if (value == '\r') {
            return;
        }
        const char ch = static_cast<char>(value);
        output.push_back(ch);
        tail.push_back(ch);
        std::cout.put(ch);
        std::cout.flush();
        if (tail.size() > 16384) {
            tail.erase(0, tail.size() - 8192);
        }
    }

    uint8_t read8(uint64_t offset) const {
        const auto reg = offset & 0x7ULL;
        const bool dlab = (lcr & 0x80U) != 0;
        if (dlab && reg == 0) return dll;
        if (dlab && reg == 1) return dlm;
        switch (reg) {
            case 0: return 0;
            case 1: return ier;
            case 2: return 0x01;
            case 3: return lcr;
            case 4: return mcr;
            case 5: return 0x60;
            case 6: return 0xB0;
            case 7: return scr;
            default: return 0;
        }
    }

    void write8(uint64_t offset, uint8_t value) {
        const auto reg = offset & 0x7ULL;
        const bool dlab = (lcr & 0x80U) != 0;
        if (dlab && reg == 0) {
            dll = value;
            return;
        }
        if (dlab && reg == 1) {
            dlm = value;
            return;
        }
        switch (reg) {
            case 0: appendOutput(value); break;
            case 1: ier = value; break;
            case 2: fcr = value; break;
            case 3: lcr = value; break;
            case 4: mcr = value; break;
            case 7: scr = value; break;
            default: break;
        }
    }
};

struct TimerDevice {
    uint64_t tickNs = TIME_SCALE_NS;
    uint64_t cycleCounter = 0;
    uint64_t nsCounter = 0;
    uint64_t cycleInterval = 0;
    uint64_t nsInterval = 0;
    std::optional<uint64_t> cycleDeadline;
    std::optional<uint64_t> nsDeadline;

    uint64_t readReg(uint64_t reg) const {
        switch (reg) {
            case 0x00: return cycleCounter;
            case 0x08: return nsCounter;
            case 0x10: return cycleInterval;
            case 0x18: return nsInterval;
            default: return 0;
        }
    }

    void writeReg(uint64_t reg, uint64_t value) {
        switch (reg) {
            case 0x10:
                cycleInterval = value;
                cycleDeadline = value == 0 ? std::nullopt : std::optional<uint64_t>(cycleCounter + value);
                break;
            case 0x18:
                nsInterval = value;
                nsDeadline = value == 0 ? std::nullopt : std::optional<uint64_t>(nsCounter + value);
                break;
            default:
                break;
        }
    }

    uint8_t read8(uint64_t offset) const {
        const auto reg = offset & ~0x7ULL;
        const auto shift = static_cast<unsigned>((offset & 0x7ULL) * 8ULL);
        return static_cast<uint8_t>((readReg(reg) >> shift) & 0xFFULL);
    }

    void write8(uint64_t offset, uint8_t value) {
        const auto reg = offset & ~0x7ULL;
        const auto shift = static_cast<unsigned>((offset & 0x7ULL) * 8ULL);
        uint64_t current = readReg(reg);
        current &= ~(0xFFULL << shift);
        current |= static_cast<uint64_t>(value) << shift;
        writeReg(reg, current);
    }

    bool tick() {
        cycleCounter += 1;
        nsCounter += tickNs;

        bool fired = false;
        if (cycleDeadline && cycleCounter >= *cycleDeadline) {
            fired = true;
            *cycleDeadline += std::max<uint64_t>(1, cycleInterval);
        }
        if (nsDeadline && nsCounter >= *nsDeadline) {
            fired = true;
            *nsDeadline += std::max<uint64_t>(1, nsInterval);
        }
        return fired;
    }
};

struct Platform;

struct PvBlockDevice {
    Platform* platform = nullptr;
    uint64_t sectorSize = 512;
    uint64_t sectorCount = (8ULL * 1024ULL * 1024ULL) / 512ULL;
    uint64_t maxSectors = 128;
    uint64_t features = L64_PVBLK_F_READ_ONLY | (1ULL << 1);
    uint64_t status = L64_PVBLK_S_READY;
    uint64_t requestAddr = 0;
    std::vector<uint8_t> disk = std::vector<uint8_t>(static_cast<size_t>(sectorCount * sectorSize), 0);

    uint64_t readReg(uint64_t reg) const {
        switch (reg) {
            case 0x00: return L64_PVBLK_MAGIC_VALUE;
            case 0x08: return L64_PVBLK_VERSION_VALUE;
            case 0x10: return sectorSize;
            case 0x18: return sectorCount;
            case 0x20: return maxSectors;
            case 0x28: return features;
            case 0x30: return status;
            case 0x38: return requestAddr;
            default: return 0;
        }
    }

    void writeReg(uint64_t reg, uint64_t value);
    uint64_t processRequest();

    uint8_t read8(uint64_t offset) const {
        const auto reg = offset & ~0x7ULL;
        const auto shift = static_cast<unsigned>((offset & 0x7ULL) * 8ULL);
        return static_cast<uint8_t>((readReg(reg) >> shift) & 0xFFULL);
    }

    void write8(uint64_t offset, uint8_t value) {
        const auto reg = offset & ~0x7ULL;
        const auto shift = static_cast<unsigned>((offset & 0x7ULL) * 8ULL);
        uint64_t current = readReg(reg);
        current &= ~(0xFFULL << shift);
        current |= static_cast<uint64_t>(value) << shift;
        writeReg(reg, current);
    }

    bool interruptPending() const {
        return (status & L64_PVBLK_S_IRQ_PENDING) != 0;
    }

    void tick() {
    }
};

struct Platform {
    explicit Platform(LoadedLinuxImage image_, std::vector<uint8_t> dtbBytes)
        : image(std::move(image_)), ram(static_cast<size_t>(image.totalRam), 0) {
        std::copy(image.ramImage.begin(), image.ramImage.end(), ram.begin());

        if (!dtbBytes.empty()) {
            const auto dtbOffset = alignUp(image.imageSpan + (EARLY_PT_SCRATCH_PAGES * PAGE_SIZE), PAGE_SIZE);
            const auto candidate = KERNEL_PHYSICAL_BASE + dtbOffset;
            if (ramContains(candidate, dtbBytes.size())) {
                writeBytes(candidate, dtbBytes);
                dtbPhysical = candidate;
            }
        }

        pvblk.platform = this;
    }

    LoadedLinuxImage image;
    std::vector<uint8_t> ram;
    uint64_t dtbPhysical = 0;
    SerialDevice serial;
    TimerDevice timer;
    PvBlockDevice pvblk;

    const uint8_t* ramPointer(uint64_t address) const {
        return ram.data() + static_cast<size_t>(address - KERNEL_PHYSICAL_BASE);
    }

    uint8_t* ramPointer(uint64_t address) {
        return ram.data() + static_cast<size_t>(address - KERNEL_PHYSICAL_BASE);
    }

    bool ramContains(uint64_t address, size_t size) const {
        const uint64_t ramEnd = KERNEL_PHYSICAL_BASE + ram.size();
        return address >= KERNEL_PHYSICAL_BASE && address + size <= ramEnd;
    }

    void writeBytes(uint64_t address, std::span<const uint8_t> bytes) {
        if (!ramContains(address, bytes.size())) {
            throw std::runtime_error("RAM write out of range");
        }
        const auto offset = static_cast<size_t>(address - KERNEL_PHYSICAL_BASE);
        std::copy(bytes.begin(), bytes.end(), ram.begin() + static_cast<std::ptrdiff_t>(offset));
    }

    std::vector<uint8_t> readBytes(uint64_t address, size_t size) const {
        if (!ramContains(address, size)) {
            throw std::runtime_error("RAM read out of range");
        }
        const auto offset = static_cast<size_t>(address - KERNEL_PHYSICAL_BASE);
        return std::vector<uint8_t>(ram.begin() + static_cast<std::ptrdiff_t>(offset), ram.begin() + static_cast<std::ptrdiff_t>(offset + size));
    }

    uint64_t readU64(uint64_t address) const {
        if (!ramContains(address, 8)) {
            throw std::runtime_error("RAM read out of range");
        }
        uint64_t value = 0;
        std::memcpy(&value, ramPointer(address), sizeof(value));
        return value;
    }

    void writeU64(uint64_t address, uint64_t value) {
        if (!ramContains(address, 8)) {
            throw std::runtime_error("RAM write out of range");
        }
        std::memcpy(ramPointer(address), &value, sizeof(value));
    }

    uint8_t readDeviceByte(uint64_t address) const {
        if (address >= UART_BASE && address < UART_BASE + UART_SIZE) {
            return serial.read8(address - UART_BASE);
        }
        if (address >= TIMER_BASE && address < TIMER_BASE + TIMER_SIZE) {
            return timer.read8(address - TIMER_BASE);
        }
        if (address >= PVBLK_BASE && address < PVBLK_BASE + PVBLK_SIZE) {
            return pvblk.read8(address - PVBLK_BASE);
        }
        return 0;
    }

    void writeDeviceByte(uint64_t address, uint8_t value) {
        if (address >= UART_BASE && address < UART_BASE + UART_SIZE) {
            serial.write8(address - UART_BASE, value);
        } else if (address >= TIMER_BASE && address < TIMER_BASE + TIMER_SIZE) {
            timer.write8(address - TIMER_BASE, value);
        } else if (address >= PVBLK_BASE && address < PVBLK_BASE + PVBLK_SIZE) {
            pvblk.write8(address - PVBLK_BASE, value);
        }
    }

    uint64_t readBusQword(uint64_t address) const {
        if (ramContains(address, 8)) {
            uint64_t value = 0;
            std::memcpy(&value, ramPointer(address), sizeof(value));
            return value;
        }

        uint64_t value = 0;
        for (uint64_t index = 0; index < 8; ++index) {
            const auto byteAddress = address + index;
            uint8_t byteValue = 0;
            if (ramContains(byteAddress, 1)) {
                byteValue = ram[static_cast<size_t>(byteAddress - KERNEL_PHYSICAL_BASE)];
            } else {
                byteValue = readDeviceByte(byteAddress);
            }
            value |= static_cast<uint64_t>(byteValue) << (8U * index);
        }
        return value;
    }

    void writeBus(uint64_t address, uint64_t value, uint8_t selectMask) {
        if (ramContains(address, 8)) {
            uint64_t current = 0;
            std::memcpy(&current, ramPointer(address), sizeof(current));

            if (selectMask == 0xFF) {
                current = value;
            } else {
                uint64_t writeMask = 0;
                for (uint64_t index = 0; index < 8; ++index) {
                    if ((selectMask & (1U << index)) != 0) {
                        writeMask |= (0xFFULL << (8U * index));
                    }
                }
                current = (current & ~writeMask) | (value & writeMask);
            }

            std::memcpy(ramPointer(address), &current, sizeof(current));
            return;
        }

        for (uint64_t index = 0; index < 8; ++index) {
            if ((selectMask & (1U << index)) == 0) {
                continue;
            }
            const auto byteAddress = address + index;
            const auto byteValue = static_cast<uint8_t>((value >> (8U * index)) & 0xFFULL);
            if (ramContains(byteAddress, 1)) {
                ram[static_cast<size_t>(byteAddress - KERNEL_PHYSICAL_BASE)] = byteValue;
            } else {
                writeDeviceByte(byteAddress, byteValue);
            }
        }
    }
};

void PvBlockDevice::writeReg(uint64_t reg, uint64_t value) {
    switch (reg) {
        case 0x38:
            requestAddr = value;
            break;
        case 0x40:
            if (value != 0 && (status & L64_PVBLK_S_BUSY) == 0) {
                const auto requestStatus = processRequest();
                platform->writeU64(requestAddr + 0x08, requestStatus);
                status = L64_PVBLK_S_READY | L64_PVBLK_S_BUSY;
                if (requestStatus != L64_PVBLK_REQ_ST_OK) {
                    status |= L64_PVBLK_S_ERROR;
                }
                status &= ~L64_PVBLK_S_BUSY;
                status |= L64_PVBLK_S_IRQ_PENDING;
            }
            break;
        case 0x48:
            if (value != 0) {
                status &= ~L64_PVBLK_S_IRQ_PENDING;
                status &= ~L64_PVBLK_S_ERROR;
            }
            break;
        default:
            break;
    }
}

uint64_t PvBlockDevice::processRequest() {
    if (!platform->ramContains(requestAddr, 64)) {
        return L64_PVBLK_REQ_ST_IOERR;
    }

    const auto op = platform->readU64(requestAddr + 0x00);
    const auto sector = platform->readU64(requestAddr + 0x10);
    const auto sectorCountRequested = platform->readU64(requestAddr + 0x18);
    const auto bufferPhysical = platform->readU64(requestAddr + 0x20);
    const auto bufferLength = platform->readU64(requestAddr + 0x28);

    if (sectorCountRequested > maxSectors) {
        return L64_PVBLK_REQ_ST_IOERR;
    }
    if (bufferLength != sectorCountRequested * sectorSize) {
        return L64_PVBLK_REQ_ST_INVALID;
    }
    if (sector > sectorCount || sectorCountRequested > sectorCount - sector) {
        return L64_PVBLK_REQ_ST_IOERR;
    }
    if (!platform->ramContains(bufferPhysical, static_cast<size_t>(bufferLength))) {
        return L64_PVBLK_REQ_ST_IOERR;
    }

    const auto diskOffset = static_cast<size_t>(sector * sectorSize);
    const auto diskLength = static_cast<size_t>(bufferLength);

    switch (op) {
        case L64_PVBLK_REQ_READ:
            platform->writeBytes(bufferPhysical, std::span<const uint8_t>(disk.data() + diskOffset, diskLength));
            return L64_PVBLK_REQ_ST_OK;
        case L64_PVBLK_REQ_WRITE:
            return L64_PVBLK_REQ_ST_READ_ONLY;
        case L64_PVBLK_REQ_FLUSH:
            return L64_PVBLK_REQ_ST_OK;
        default:
            return L64_PVBLK_REQ_ST_UNSUPPORTED;
    }
}

struct BootResult {
    bool success = false;
    bool timedOut = false;
    bool lockedUp = false;
    bool halted = false;
    bool invalidPc = false;
    bool zeroInstruction = false;
    uint64_t cycles = 0;
};

struct TraceEntry {
    uint64_t cycle = 0;
    uint64_t fetchPc = 0;
    uint64_t fetchPhys = 0;
    uint32_t instruction = 0;
    uint8_t state = 0;
    uint64_t r2 = 0;
    uint64_t r3 = 0;
    uint64_t r4 = 0;
    uint64_t r9 = 0;
    uint64_t r10 = 0;
    uint64_t r13 = 0;
    uint64_t r15 = 0;
};

struct PageWalkDump {
    uint64_t root = 0;
    uint64_t rootEntry0 = 0;
    uint64_t rootEntry100 = 0;
    uint64_t idx2 = 0;
    uint64_t idx1 = 0;
    uint64_t idx0 = 0;
    uint64_t l2PteAddr = 0;
    uint64_t l2Pte = 0;
    uint64_t l1Table = 0;
    uint64_t l1PteAddr = 0;
    uint64_t l1Pte = 0;
    uint64_t l0Table = 0;
    uint64_t l0PteAddr = 0;
    uint64_t l0Pte = 0;
    uint64_t resolvedPhys = 0;
    bool valid = false;
};

class SimulatorRunner {
  public:
    explicit SimulatorRunner(Platform platform_)
        : context(std::make_unique<VerilatedContext>()),
          top(std::make_unique<Vlittle64_linux_boot_top>(context.get(), "little64_linux_boot_top")),
                    platform(std::move(platform_)),
                    debugTraceEnabled(envFlagEnabled("LITTLE64_VERILATOR_DEBUG_TRACE")) {
        context->traceEverOn(false);
        top->boot_r1 = platform.dtbPhysical;
        top->boot_r13 = KERNEL_PHYSICAL_BASE + platform.image.totalRam - 8ULL;
        top->irq_lines = 0;
        top->i_bus_ack = 0;
        top->i_bus_err = 0;
        top->i_bus_dat_r = 0;
        top->d_bus_ack = 0;
        top->d_bus_err = 0;
        top->d_bus_dat_r = 0;
        top->clk = 0;
        top->rst = 1;
        top->eval();
    }

    BootResult run(uint64_t maxCycles, const std::vector<std::string>& requiredMarkers) {
        resetDesign();
        BootResult result{};
        std::vector<bool> markerSeen(requiredMarkers.size(), requiredMarkers.empty());
        size_t markersSatisfied = requiredMarkers.empty() ? requiredMarkers.size() : 0;
        size_t lastSerialSize = 0;

        for (uint64_t cycle = 0; cycle < maxCycles; ++cycle) {
            driveNextInputs();
            tick();
            result.cycles = cycle + 1;
            recordTrace(result.cycles);

            if (isZeroInstructionExecution()) {
                result.zeroInstruction = true;
                break;
            }

            if (isInvalidFetchPc()) {
                result.invalidPc = true;
                break;
            }

            if (top->locked_up) {
                result.lockedUp = true;
                break;
            }
            if (top->halted) {
                result.halted = true;
                break;
            }

            if (platform.serial.output.size() != lastSerialSize) {
                const size_t newSearchStartBase = lastSerialSize == 0 ? 0 : lastSerialSize - 1;
                for (size_t index = 0; index < requiredMarkers.size(); ++index) {
                    if (markerSeen[index]) {
                        continue;
                    }
                    const auto& marker = requiredMarkers[index];
                    const size_t searchStart = (lastSerialSize > marker.size())
                        ? (lastSerialSize - marker.size())
                        : 0;
                    if (platform.serial.output.find(marker, searchStart) != std::string::npos) {
                        markerSeen[index] = true;
                        ++markersSatisfied;
                    }
                }
                lastSerialSize = platform.serial.output.size();
            }

            if (markersSatisfied == requiredMarkers.size()) {
                result.success = true;
                break;
            }
        }

        if (!result.success && !result.lockedUp && !result.halted) {
            result.timedOut = true;
        }

        return result;
    }

    const std::string& serialOutput() const {
        return platform.serial.output;
    }

    void printDiagnostics(std::ostream& stream) const {
        stream << "state=" << static_cast<unsigned>(top->state)
               << " current_instruction=0x" << std::hex << top->current_instruction
               << " fetch_pc=0x" << top->fetch_pc
               << " fetch_phys_addr=0x" << top->fetch_phys_addr
               << " commit_valid=" << std::dec << static_cast<unsigned>(top->commit_valid)
               << " commit_pc=0x" << std::hex << top->commit_pc
               << "\n";

         if (isZeroInstructionExecution()) {
             stream << "zero_instruction_fetch_pc=0x" << std::hex << top->fetch_pc
                 << " zero_instruction_fetch_phys=0x" << top->fetch_phys_addr
                 << "\n";
         }

        if (isInvalidFetchPc()) {
            stream << "invalid_fetch_pc=0x" << std::hex << top->fetch_pc
                   << " image_phys=[0x" << KERNEL_PHYSICAL_BASE
                   << ", 0x" << (KERNEL_PHYSICAL_BASE + platform.image.imageSpan)
                   << ") image_virt=[0x" << platform.image.virtBase
                   << ", 0x" << platform.image.virtEnd
                   << ")\n";

            const auto walk = dumpPageWalk(top->fetch_pc);
            if (walk.valid) {
                stream << "page_walk:\n"
                       << "  root=0x" << std::hex << walk.root
                      << " root[0]=0x" << walk.rootEntry0
                      << " root[0x100]=0x" << walk.rootEntry100
                       << " idx2=0x" << walk.idx2
                       << " idx1=0x" << walk.idx1
                       << " idx0=0x" << walk.idx0
                       << "\n  l2_pte_addr=0x" << walk.l2PteAddr
                       << " l2_pte=0x" << walk.l2Pte
                       << "\n  l1_table=0x" << walk.l1Table
                       << " l1_pte_addr=0x" << walk.l1PteAddr
                       << " l1_pte=0x" << walk.l1Pte
                       << "\n  l0_table=0x" << walk.l0Table
                       << " l0_pte_addr=0x" << walk.l0PteAddr
                       << " l0_pte=0x" << walk.l0Pte
                       << "\n  resolved_phys=0x" << walk.resolvedPhys
                       << "\n";
            }
        }

        if (!recentTrace.empty()) {
            stream << "recent_execute_trace:\n";
            for (const auto& entry : recentTrace) {
                stream << "  cycle=" << std::dec << entry.cycle
                       << " state=" << static_cast<unsigned>(entry.state)
                       << " pc=0x" << std::hex << entry.fetchPc
                       << " phys=0x" << entry.fetchPhys
                       << " insn=0x" << entry.instruction
                      << " r2=0x" << entry.r2
                      << " r3=0x" << entry.r3
                      << " r4=0x" << entry.r4
                      << " r9=0x" << entry.r9
                      << " r10=0x" << entry.r10
                      << " r13=0x" << entry.r13
                      << " r15=0x" << entry.r15
                       << "\n";
            }
        }

        if (!platform.serial.tail.empty()) {
            stream << "serial_tail:\n" << platform.serial.tail << "\n";
        }
    }

  private:
    void resetDesign() {
        for (unsigned step = 0; step < 2; ++step) {
            top->rst = 1;
            driveIdleInputs();
            tick();
        }
        top->rst = 0;
    }

    void driveIdleInputs() {
        top->irq_lines = 0;
        top->i_bus_ack = 0;
        top->i_bus_err = 0;
        top->i_bus_dat_r = 0;
        top->d_bus_ack = 0;
        top->d_bus_err = 0;
        top->d_bus_dat_r = 0;
    }

    void driveNextInputs() {
        uint64_t irqLines = 0;
        if (platform.timer.tick()) {
            irqLines |= TIMER_IRQ_MASK;
        }
        platform.pvblk.tick();
        if (platform.pvblk.interruptPending()) {
            irqLines |= PVBLK_IRQ_MASK;
        }
        top->irq_lines = irqLines;

        if (top->i_bus_cyc && top->i_bus_stb) {
            top->i_bus_dat_r = platform.readBusQword(top->i_bus_adr);
            top->i_bus_ack = 1;
            top->i_bus_err = 0;
        } else {
            top->i_bus_dat_r = 0;
            top->i_bus_ack = 0;
            top->i_bus_err = 0;
        }

        if (top->d_bus_cyc && top->d_bus_stb) {
            if (top->d_bus_we) {
                platform.writeBus(top->d_bus_adr, top->d_bus_dat_w, top->d_bus_sel);
            } else {
                top->d_bus_dat_r = platform.readBusQword(top->d_bus_adr);
            }
            top->d_bus_ack = 1;
            top->d_bus_err = 0;
        } else {
            top->d_bus_dat_r = 0;
            top->d_bus_ack = 0;
            top->d_bus_err = 0;
        }
    }

    void tick() {
        top->clk = 0;
        top->eval();
        context->timeInc(1);
        top->clk = 1;
        top->eval();
        context->timeInc(1);
    }

    bool isInvalidFetchPc() const {
        const uint64_t fetchPc = top->fetch_pc;
        if (fetchPc == 0) {
            return false;
        }

        const bool inPhysicalImage =
            fetchPc >= KERNEL_PHYSICAL_BASE &&
            fetchPc < KERNEL_PHYSICAL_BASE + platform.image.imageSpan;
        const bool inVirtualImage =
            fetchPc >= platform.image.virtBase &&
            fetchPc < platform.image.virtEnd;
        return !inPhysicalImage && !inVirtualImage;
    }

    bool isZeroInstructionExecution() const {
        return top->state == 3 && top->fetch_pc != 0 && top->current_instruction == 0;
    }

    PageWalkDump dumpPageWalk(uint64_t virtualAddress) const {
        auto readPte = [this](uint64_t address) -> uint64_t {
            if (!platform.ramContains(address, 8)) {
                return 0;
            }
            return platform.readU64(address);
        };

        PageWalkDump dump{};
        dump.root = top->rootp->little64_linux_boot_top__DOT__core__DOT__page_table_root_physical;
        if (dump.root == 0 || !platform.ramContains(dump.root, 8)) {
            return dump;
        }

        dump.rootEntry0 = readPte(dump.root);
        dump.rootEntry100 = readPte(dump.root + (0x100ULL * 8ULL));

        dump.idx2 = (virtualAddress >> 30) & 0x1ffULL;
        dump.idx1 = (virtualAddress >> 21) & 0x1ffULL;
        dump.idx0 = (virtualAddress >> 12) & 0x1ffULL;

        dump.l2PteAddr = dump.root + (dump.idx2 * 8ULL);
        dump.l2Pte = readPte(dump.l2PteAddr);
        dump.l1Table = ((dump.l2Pte >> 10) << 12);
        dump.l1PteAddr = dump.l1Table + (dump.idx1 * 8ULL);
        dump.l1Pte = readPte(dump.l1PteAddr);
        dump.l0Table = ((dump.l1Pte >> 10) << 12);
        dump.l0PteAddr = dump.l0Table + (dump.idx0 * 8ULL);
        dump.l0Pte = readPte(dump.l0PteAddr);
        dump.resolvedPhys = (((dump.l0Pte >> 10) << 12) | (virtualAddress & 0xfffULL));
        dump.valid = true;
        return dump;
    }

    void recordTrace(uint64_t cycle) {
        if (!debugTraceEnabled || top->state != 3) {
            return;
        }

        recentTrace.push_back(TraceEntry{
            .cycle = cycle,
            .fetchPc = top->fetch_pc,
            .fetchPhys = top->fetch_phys_addr,
            .instruction = top->current_instruction,
            .state = static_cast<uint8_t>(top->state),
            .r2 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r2,
            .r3 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r3,
            .r4 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r4,
            .r9 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r9,
            .r10 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r10,
            .r13 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r13,
            .r15 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r15,
        });
        if (recentTrace.size() > 64) {
            recentTrace.pop_front();
        }
    }

    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vlittle64_linux_boot_top> top;
    Platform platform;
    bool debugTraceEnabled;
    std::deque<TraceEntry> recentTrace;
};

struct Options {
    fs::path kernel;
    fs::path dtb;
    uint64_t maxCycles = 200'000'000ULL;
    std::vector<std::string> requiredMarkers;
};

Options parseArguments(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view arg(argv[index]);
        auto nextValue = [&](std::string_view flag) -> std::string_view {
            if (index + 1 >= argc) {
                throw std::runtime_error("missing value for " + std::string(flag));
            }
            ++index;
            return argv[index];
        };

        if (arg == "--kernel") {
            options.kernel = fs::path(nextValue(arg));
        } else if (arg == "--dtb") {
            options.dtb = fs::path(nextValue(arg));
        } else if (arg == "--max-cycles") {
            options.maxCycles = std::stoull(std::string(nextValue(arg)));
        } else if (arg == "--require") {
            options.requiredMarkers.emplace_back(nextValue(arg));
        } else {
            throw std::runtime_error("unknown argument: " + std::string(arg));
        }
    }

    if (options.kernel.empty()) {
        throw std::runtime_error("--kernel is required");
    }
    if (options.dtb.empty()) {
        throw std::runtime_error("--dtb is required");
    }
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        Verilated::commandArgs(argc, argv);
        const auto options = parseArguments(argc, argv);

        Platform platform(loadLinuxImage(options.kernel), readBinaryFile(options.dtb));
        SimulatorRunner runner(std::move(platform));
        const auto result = runner.run(options.maxCycles, options.requiredMarkers);

        if (result.success) {
            return 0;
        }

        std::cerr << "Verilator Linux boot smoke failed: cycles=" << result.cycles
                  << " timed_out=" << result.timedOut
                  << " locked_up=" << result.lockedUp
                  << " halted=" << result.halted
                  << " invalid_pc=" << result.invalidPc
                  << " zero_instruction=" << result.zeroInstruction << "\n";
        runner.printDiagnostics(std::cerr);
        return 1;
    } catch (const std::exception& exception) {
        std::cerr << exception.what() << "\n";
        return 1;
    }
}