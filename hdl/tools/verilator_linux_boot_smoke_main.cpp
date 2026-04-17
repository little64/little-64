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

#ifndef LITTLE64_HARNESS_ENABLE_DEBUG
#define LITTLE64_HARNESS_ENABLE_DEBUG 1
#endif

static constexpr bool kHarnessDebug = LITTLE64_HARNESS_ENABLE_DEBUG != 0;

constexpr uint64_t KERNEL_PHYSICAL_BASE = 0x0010'0000ULL;
constexpr uint64_t PAGE_OFFSET = 0xFFFF'FFC0'0000'0000ULL;
constexpr uint64_t RAM_BASE = 0x0000'0000ULL;
constexpr uint64_t PAGE_SIZE = 4096ULL;
constexpr uint64_t EARLY_PT_SCRATCH_PAGES = 30ULL;
constexpr uint64_t FLASH_BASE = 0x2000'0000ULL;
constexpr uint64_t FLASH_BOOT_MAGIC = 0x4C3634464C415348ULL;
constexpr uint64_t FLASH_BOOT_HEADER_OFFSET = 0x2000ULL;

constexpr uint64_t UART_BASE = 0xF000'1000ULL;
constexpr uint64_t UART_SIZE = 0x100ULL;
constexpr uint64_t TIMER_BASE = 0x0800'1000ULL;
constexpr uint64_t TIMER_SIZE = 0x20ULL;
constexpr uint64_t PVBLK_BASE = 0x0800'2000ULL;
constexpr uint64_t PVBLK_SIZE = 0x100ULL;

constexpr uint64_t TIMER_IRQ_MASK = 1ULL << 1;
constexpr uint64_t PVBLK_IRQ_MASK = 1ULL << 2;

constexpr uint64_t DEFAULT_TIME_SCALE_NS = 10ULL;

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

uint64_t envU64(const char* name, uint64_t defaultValue) {
    const char* value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
        return defaultValue;
    }

    char* end = nullptr;
    const unsigned long long parsed = std::strtoull(value, &end, 0);
    if (end == value || (end != nullptr && *end != '\0')) {
        return defaultValue;
    }
    return parsed == 0 ? defaultValue : static_cast<uint64_t>(parsed);
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
#if LITTLE64_HARNESS_ENABLE_DEBUG
    std::optional<uint64_t> panicSymbol;
    std::optional<uint64_t> vpanicSymbol;
    std::optional<uint64_t> printkSymbol;
    std::optional<uint64_t> pcpuSetupFirstChunkSymbol;
#endif
    std::vector<uint8_t> ramImage;
};

#if LITTLE64_HARNESS_ENABLE_DEBUG
std::optional<uint64_t> findElfSymbolValue(
    const std::vector<uint8_t>& elfBytes,
    std::string_view symbolName
) {
    if (elfBytes.size() < sizeof(Elf64_Ehdr)) {
        return std::nullopt;
    }

    const auto* header = reinterpret_cast<const Elf64_Ehdr*>(elfBytes.data());
    if (header->e_shentsize != sizeof(Elf64_Shdr) ||
        header->e_shoff + (static_cast<uint64_t>(header->e_shnum) * sizeof(Elf64_Shdr)) > elfBytes.size()) {
        return std::nullopt;
    }

    const auto* sectionHeaders = reinterpret_cast<const Elf64_Shdr*>(elfBytes.data() + header->e_shoff);
    for (uint16_t sectionIndex = 0; sectionIndex < header->e_shnum; ++sectionIndex) {
        const auto& section = sectionHeaders[sectionIndex];
        if (section.sh_type != SHT_SYMTAB || section.sh_entsize != sizeof(Elf64_Sym) || section.sh_link >= header->e_shnum) {
            continue;
        }
        if (section.sh_offset + section.sh_size > elfBytes.size()) {
            continue;
        }

        const auto& stringSection = sectionHeaders[section.sh_link];
        if (stringSection.sh_offset + stringSection.sh_size > elfBytes.size()) {
            continue;
        }

        const auto* symbols = reinterpret_cast<const Elf64_Sym*>(elfBytes.data() + section.sh_offset);
        const auto* stringTable = reinterpret_cast<const char*>(elfBytes.data() + stringSection.sh_offset);
        const size_t symbolCount = static_cast<size_t>(section.sh_size / sizeof(Elf64_Sym));

        for (size_t symbolIndex = 0; symbolIndex < symbolCount; ++symbolIndex) {
            const auto& symbol = symbols[symbolIndex];
            if (symbol.st_name >= stringSection.sh_size) {
                continue;
            }
            const std::string_view currentName(stringTable + symbol.st_name);
            if (currentName == symbolName) {
                return symbol.st_value;
            }
        }
    }

    return std::nullopt;
}
#endif

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

    LoadedLinuxImage image{
        .entryPhysical = entryPhysical,
        .virtBase = virtBase,
        .virtEnd = virtBase + imageSpan,
        .imageSpan = imageSpan,
        .ramImage = std::move(ramImage),
    };

#if LITTLE64_HARNESS_ENABLE_DEBUG
    image.panicSymbol = findElfSymbolValue(elfBytes, "panic");
    image.vpanicSymbol = findElfSymbolValue(elfBytes, "vpanic");
    image.printkSymbol = findElfSymbolValue(elfBytes, "_printk");
    image.pcpuSetupFirstChunkSymbol = findElfSymbolValue(elfBytes, "pcpu_setup_first_chunk");
#endif

    return image;
}

struct FlashBootImage {
    uint64_t abiVersion = 0;
    uint64_t kernelFlashOffset = 0;
    uint64_t kernelCopySize = 0;
    uint64_t kernelPhysicalBase = 0;
    uint64_t kernelEntryPhysical = 0;
    uint64_t dtbFlashOffset = 0;
    uint64_t dtbSize = 0;
    uint64_t dtbPhysical = 0;
    uint64_t kernelBootStackTop = 0;
    uint64_t flashImageSize = 0;
    std::vector<uint8_t> bytes;
};

uint64_t readLe64(const uint8_t* bytes) {
    uint64_t value = 0;
    for (unsigned index = 0; index < 8; ++index) {
        value |= static_cast<uint64_t>(bytes[index]) << (8U * index);
    }
    return value;
}

FlashBootImage loadFlashBootImage(const fs::path& path) {
    auto bytes = readBinaryFile(path);
    if (bytes.size() < FLASH_BOOT_HEADER_OFFSET + (16ULL * sizeof(uint64_t))) {
        throw std::runtime_error("flash image too small: " + path.string());
    }

    const uint8_t* header = bytes.data() + FLASH_BOOT_HEADER_OFFSET;
    if (readLe64(header + 0x00) != FLASH_BOOT_MAGIC) {
        throw std::runtime_error("flash image has invalid Little64 boot magic");
    }

    FlashBootImage image;
    image.abiVersion = readLe64(header + 0x08);
    image.kernelFlashOffset = readLe64(header + 0x10);
    image.kernelCopySize = readLe64(header + 0x18);
    image.kernelPhysicalBase = readLe64(header + 0x20);
    image.kernelEntryPhysical = readLe64(header + 0x28);
    image.dtbFlashOffset = readLe64(header + 0x30);
    image.dtbSize = readLe64(header + 0x38);
    image.dtbPhysical = readLe64(header + 0x40);
    image.kernelBootStackTop = readLe64(header + 0x48);
    image.flashImageSize = readLe64(header + 0x50);
    image.bytes = std::move(bytes);

    if (image.flashImageSize > image.bytes.size()) {
        throw std::runtime_error("flash image header exceeds file size");
    }
    if (image.kernelFlashOffset + image.kernelCopySize > image.flashImageSize) {
        throw std::runtime_error("flash image kernel payload exceeds file size");
    }
    if (image.dtbFlashOffset + image.dtbSize > image.flashImageSize) {
        throw std::runtime_error("flash image DTB payload exceeds file size");
    }
    return image;
}

struct SerialDevice {
    static constexpr uint64_t OFF_RXTX = 0x00;
    static constexpr uint64_t OFF_TXFULL = 0x04;
    static constexpr uint64_t OFF_RXEMPTY = 0x08;
    static constexpr uint64_t OFF_EV_STATUS = 0x0C;
    static constexpr uint64_t OFF_EV_PENDING = 0x10;
    static constexpr uint64_t OFF_EV_ENABLE = 0x14;

    uint8_t evPending = 0;
    uint8_t evEnable = 0;
    std::string output;
    std::string tail;
    uint64_t readCount = 0;
    uint64_t writeCount = 0;
    uint64_t txWriteCount = 0;
    uint64_t lastReadOffset = 0;
    uint64_t lastWriteOffset = 0;
    uint8_t lastReadValue = 0;
    uint8_t lastWriteValue = 0;

    void appendOutput(uint8_t value) {
        if (value == '\r') {
            return;
        }
        const char ch = static_cast<char>(value);
        output.push_back(ch);
        tail.push_back(ch);
        std::cout.put(ch);
        if (ch == '\n') {
            std::cout.flush();
        }
        if (tail.size() > 16384) {
            tail.erase(0, tail.size() - 8192);
        }
    }

    uint8_t read8(uint64_t offset) const {
        switch (offset) {
            case OFF_RXTX: return 0;
            case OFF_TXFULL: return 0;
            case OFF_RXEMPTY: return 1;
            case OFF_EV_STATUS: return evPending;
            case OFF_EV_PENDING: return evPending;
            case OFF_EV_ENABLE: return evEnable;
            default: return 0;
        }
    }

    void write8(uint64_t offset, uint8_t value) {
        ++writeCount;
        lastWriteOffset = offset;
        lastWriteValue = value;
        switch (offset) {
            case OFF_RXTX:
                ++txWriteCount;
                appendOutput(value);
                break;
            case OFF_EV_PENDING:
                evPending &= static_cast<uint8_t>(~value);
                break;
            case OFF_EV_ENABLE:
                evEnable = value;
                break;
            default: break;
        }
    }
};

struct TimerDevice {
    uint64_t tickNs = envU64("LITTLE64_VERILATOR_TIME_SCALE_NS", DEFAULT_TIME_SCALE_NS);
    uint64_t cycleCounter = 0;
    uint64_t nsCounter = 0;
    uint64_t cycleInterval = 0;
    uint64_t nsInterval = 0;
    uint64_t fireCount = 0;
    uint64_t cycleFireCount = 0;
    uint64_t nsFireCount = 0;
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
            ++fireCount;
            ++cycleFireCount;
            *cycleDeadline += std::max<uint64_t>(1, cycleInterval);
        }
        if (nsDeadline && nsCounter >= *nsDeadline) {
            fired = true;
            ++fireCount;
            ++nsFireCount;
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
    explicit Platform(LoadedLinuxImage image_, FlashBootImage flash_)
        : image(std::move(image_)), flash(std::move(flash_)) {
        const uint64_t ramEnd = std::max(
            std::max(
                static_cast<uint64_t>(flash.kernelBootStackTop + 8ULL),
                static_cast<uint64_t>(flash.kernelPhysicalBase + flash.kernelCopySize)
            ),
            static_cast<uint64_t>(flash.dtbPhysical + flash.dtbSize)
        );
        ram.resize(static_cast<size_t>(alignUp(ramEnd, PAGE_SIZE)), 0);
        ramLimit = RAM_BASE + ram.size();
        flashLimit = FLASH_BASE + flash.bytes.size();
        pvblk.platform = this;
    }

    LoadedLinuxImage image;
    FlashBootImage flash;
    std::vector<uint8_t> ram;
    uint64_t ramLimit = RAM_BASE;
    uint64_t flashLimit = FLASH_BASE;
    SerialDevice serial;
    TimerDevice timer;
    PvBlockDevice pvblk;

    const uint8_t* ramPointer(uint64_t address) const {
        return ram.data() + static_cast<size_t>(address - RAM_BASE);
    }

    uint8_t* ramPointer(uint64_t address) {
        return ram.data() + static_cast<size_t>(address - RAM_BASE);
    }

    bool ramContains(uint64_t address, size_t size) const {
        return address >= RAM_BASE && address + size <= ramLimit;
    }

    bool flashContains(uint64_t address, size_t size) const {
        return address >= FLASH_BASE && address + size <= flashLimit;
    }

    uint8_t readFlashByte(uint64_t address) const {
        if (!flashContains(address, 1)) {
            return 0xFF;
        }
        return flash.bytes[static_cast<size_t>(address - FLASH_BASE)];
    }

    void writeBytes(uint64_t address, std::span<const uint8_t> bytes) {
        if (!ramContains(address, bytes.size())) {
            throw std::runtime_error("RAM write out of range");
        }
        const auto offset = static_cast<size_t>(address - RAM_BASE);
        std::copy(bytes.begin(), bytes.end(), ram.begin() + static_cast<std::ptrdiff_t>(offset));
    }

    std::vector<uint8_t> readBytes(uint64_t address, size_t size) const {
        if (!ramContains(address, size)) {
            throw std::runtime_error("RAM read out of range");
        }
        const auto offset = static_cast<size_t>(address - RAM_BASE);
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
            auto& serialDevice = const_cast<SerialDevice&>(serial);
            const auto offset = address - UART_BASE;
            const auto value = serial.read8(offset);
            ++serialDevice.readCount;
            serialDevice.lastReadOffset = offset & 0x7ULL;
            serialDevice.lastReadValue = value;
            return value;
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
        if (flashContains(address, 8)) {
            uint64_t value = 0;
            std::memcpy(&value, flash.bytes.data() + static_cast<size_t>(address - FLASH_BASE), sizeof(value));
            return value;
        }

        uint64_t value = 0;
        for (uint64_t index = 0; index < 8; ++index) {
            const auto byteAddress = address + index;
            uint8_t byteValue = 0;
            if (ramContains(byteAddress, 1)) {
                byteValue = ram[static_cast<size_t>(byteAddress - RAM_BASE)];
            } else if (flashContains(byteAddress, 1)) {
                byteValue = readFlashByte(byteAddress);
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
                ram[static_cast<size_t>(byteAddress - RAM_BASE)] = byteValue;
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
    bool panicCaptured = false;
    uint64_t cycles = 0;
};

struct IBusRequestTracker {
    bool active = false;
    bool responseIssued = false;
    uint64_t address = 0;
};

struct DBusRequestTracker {
    bool active = false;
    bool responseIssued = false;
    uint64_t address = 0;
    uint64_t data = 0;
    uint8_t selectMask = 0;
    bool write = false;
};

#if LITTLE64_HARNESS_ENABLE_DEBUG
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
    uint64_t r14 = 0;
    uint64_t r15 = 0;
};

struct SymbolHitSnapshot {
    std::string symbolName;
    uint64_t cycle = 0;
    uint64_t pc = 0;
    uint64_t r1 = 0;
    uint64_t r2 = 0;
    uint64_t r3 = 0;
    uint64_t r4 = 0;
    uint64_t r5 = 0;
    uint64_t r6 = 0;
    uint64_t r7 = 0;
    uint64_t r8 = 0;
    uint64_t r9 = 0;
    uint64_t r10 = 0;
    uint64_t r11 = 0;
    uint64_t r13 = 0;
    uint64_t r14 = 0;
    uint64_t r15 = 0;
    std::optional<std::string> r1String;
    std::optional<std::string> r2String;
    std::optional<std::string> r3String;
    std::optional<std::string> r4String;
    std::optional<std::string> r5String;
    std::optional<std::string> r6String;
    std::optional<std::string> r7String;
    std::optional<std::string> r8String;
    std::optional<std::string> r9String;
    std::optional<std::string> r10String;
};

struct PcpuAllocInfoDump {
    uint64_t address = 0;
    uint64_t staticSize = 0;
    uint64_t reservedSize = 0;
    uint64_t dynSize = 0;
    uint64_t unitSize = 0;
    uint64_t atomSize = 0;
    uint64_t allocSize = 0;
    uint64_t aiSize = 0;
    uint32_t nrGroups = 0;
    uint32_t group0NrUnits = 0;
    uint64_t group0BaseOffset = 0;
    uint64_t group0CpuMap = 0;
    uint32_t group0Cpu0 = 0;
};

struct PcpuEntrySnapshot {
    uint64_t cycle = 0;
    uint64_t pc = 0;
    uint64_t aiVirtual = 0;
    uint64_t baseVirtual = 0;
    std::optional<uint64_t> aiPhysical;
    std::optional<uint64_t> basePhysical;
    std::array<uint64_t, 8> aiWords{};
    std::array<uint64_t, 8> baseWords{};
    PcpuAllocInfoDump aiDump{};
    bool aiWordsValid = false;
    bool baseWordsValid = false;
    bool aiDumpValid = false;
    bool overlapsBase = false;
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
#endif

class SimulatorRunner {
  public:
    explicit SimulatorRunner(Platform platform_)
        : context(std::make_unique<VerilatedContext>()),
          top(std::make_unique<Vlittle64_linux_boot_top>(context.get(), "little64_linux_boot_top")),
                    platform(std::move(platform_)),
                                        debugTraceEnabled(kHarnessDebug && envFlagEnabled("LITTLE64_VERILATOR_DEBUG_TRACE")) {
        context->traceEverOn(false);
                top->boot_r1 = 0;
                top->boot_r13 = 0;
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
#if LITTLE64_HARNESS_ENABLE_DEBUG
        const uint64_t panicExitGraceCycles = 100'000ULL;
#endif

        for (uint64_t cycle = 0; cycle < maxCycles; ++cycle) {
            driveNextInputs();
            tick();
            result.cycles = cycle + 1;
#if LITTLE64_HARNESS_ENABLE_DEBUG
            recordTrace(result.cycles);
#endif

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

#if LITTLE64_HARNESS_ENABLE_DEBUG
            if (panicCaptureComplete(result.cycles, panicExitGraceCycles)) {
                result.panicCaptured = true;
                break;
            }
#endif
        }

        if (!result.success && !result.lockedUp && !result.halted && !result.panicCaptured) {
            result.timedOut = true;
        }

        return result;
    }

    const std::string& serialOutput() const {
        return platform.serial.output;
    }

    void printDiagnostics(std::ostream& stream) const {
         const uint64_t currentSp = top->rootp->little64_linux_boot_top__DOT__core__DOT__r13;
         const uint64_t currentFp = top->rootp->little64_linux_boot_top__DOT__core__DOT__r11;
         const uint64_t currentRa = top->rootp->little64_linux_boot_top__DOT__core__DOT__r14;

        stream << "state=" << static_cast<unsigned>(top->state)
               << " current_instruction=0x" << std::hex << top->current_instruction
               << " fetch_pc=0x" << top->fetch_pc
               << " fetch_phys_addr=0x" << top->fetch_phys_addr
               << " commit_valid=" << std::dec << static_cast<unsigned>(top->commit_valid)
               << " commit_pc=0x" << std::hex << top->commit_pc
               << "\n";
         stream << "live_regs: sp=0x" << std::hex << currentSp
             << " fp=0x" << currentFp
             << " ra=0x" << currentRa
             << "\n";
         stream << "uart_stats: reads=" << std::dec << platform.serial.readCount
             << " writes=" << platform.serial.writeCount
             << " tx_writes=" << platform.serial.txWriteCount
             << " last_read=[0x" << std::hex << platform.serial.lastReadOffset
             << "]=0x" << static_cast<unsigned>(platform.serial.lastReadValue)
             << " last_write=[0x" << platform.serial.lastWriteOffset
             << "]=0x" << static_cast<unsigned>(platform.serial.lastWriteValue)
             << "\n";
         stream << "timer_stats: tick_ns=" << std::dec << platform.timer.tickNs
             << " cycle_counter=" << platform.timer.cycleCounter
             << " ns_counter=" << platform.timer.nsCounter
             << " cycle_interval=" << platform.timer.cycleInterval
             << " ns_interval=" << platform.timer.nsInterval
             << " fire_count=" << platform.timer.fireCount
             << " cycle_fire_count=" << platform.timer.cycleFireCount
             << " ns_fire_count=" << platform.timer.nsFireCount
             << "\n";

#if LITTLE64_HARNESS_ENABLE_DEBUG
        printSymbolHit(stream, firstPanicHit);
        printSymbolHit(stream, firstVpanicHit);
        if (!recentPrintkHits.empty()) {
            for (const auto& snapshot : recentPrintkHits) {
                printSymbolHit(stream, snapshot);
            }
        }

        if (const auto percpuInfo = findCapturedPcpuAllocInfo()) {
            stream << "pcpu_alloc_info: addr=0x" << std::hex << percpuInfo->address
                   << " static=0x" << percpuInfo->staticSize
                   << " reserved=0x" << percpuInfo->reservedSize
                   << " dyn=0x" << percpuInfo->dynSize
                   << " unit=0x" << percpuInfo->unitSize
                   << " atom=0x" << percpuInfo->atomSize
                   << " alloc=0x" << percpuInfo->allocSize
                   << " ai_size=0x" << percpuInfo->aiSize
                   << " nr_groups=" << std::dec << percpuInfo->nrGroups
                   << " group0.nr_units=" << percpuInfo->group0NrUnits
                   << " group0.base_offset=0x" << std::hex << percpuInfo->group0BaseOffset
                   << " group0.cpu_map=0x" << percpuInfo->group0CpuMap
                   << " cpu_map[0]=" << std::dec << percpuInfo->group0Cpu0
                   << "\n";
        }

        if (pcpuEntrySnapshot) {
            stream << "pcpu_setup_first_chunk_entry: cycle=" << std::dec << pcpuEntrySnapshot->cycle
                   << " pc=0x" << std::hex << pcpuEntrySnapshot->pc
                   << " ai_va=0x" << pcpuEntrySnapshot->aiVirtual
                   << " ai_pa=";
            if (pcpuEntrySnapshot->aiPhysical) {
                stream << "0x" << *pcpuEntrySnapshot->aiPhysical;
            } else {
                stream << "<unmapped>";
            }
            stream << " base_va=0x" << pcpuEntrySnapshot->baseVirtual
                   << " base_pa=";
            if (pcpuEntrySnapshot->basePhysical) {
                stream << "0x" << *pcpuEntrySnapshot->basePhysical;
            } else {
                stream << "<unmapped>";
            }
            stream << " overlaps_base=" << std::dec << static_cast<unsigned>(pcpuEntrySnapshot->overlapsBase)
                   << "\n";
            if (pcpuEntrySnapshot->aiDumpValid) {
                stream << "  ai_dump: static=0x" << std::hex << pcpuEntrySnapshot->aiDump.staticSize
                       << " reserved=0x" << pcpuEntrySnapshot->aiDump.reservedSize
                       << " dyn=0x" << pcpuEntrySnapshot->aiDump.dynSize
                       << " unit=0x" << pcpuEntrySnapshot->aiDump.unitSize
                       << " atom=0x" << pcpuEntrySnapshot->aiDump.atomSize
                       << " alloc=0x" << pcpuEntrySnapshot->aiDump.allocSize
                       << " ai_size=0x" << pcpuEntrySnapshot->aiDump.aiSize
                       << " nr_groups=" << std::dec << pcpuEntrySnapshot->aiDump.nrGroups
                       << " group0.nr_units=" << pcpuEntrySnapshot->aiDump.group0NrUnits
                       << " group0.base_offset=0x" << std::hex << pcpuEntrySnapshot->aiDump.group0BaseOffset
                       << " group0.cpu_map=0x" << pcpuEntrySnapshot->aiDump.group0CpuMap
                       << " cpu_map[0]=" << std::dec << pcpuEntrySnapshot->aiDump.group0Cpu0
                       << "\n";
            }
            if (pcpuEntrySnapshot->aiWordsValid) {
                stream << "  ai_words:";
                for (const auto word : pcpuEntrySnapshot->aiWords) {
                    stream << " 0x" << std::hex << word;
                }
                stream << "\n";
            }
            if (pcpuEntrySnapshot->baseWordsValid) {
                stream << "  base_words:";
                for (const auto word : pcpuEntrySnapshot->baseWords) {
                    stream << " 0x" << std::hex << word;
                }
                stream << "\n";
            }
        }

         if (isZeroInstructionExecution()) {
             stream << "zero_instruction_fetch_pc=0x" << std::hex << top->fetch_pc
                 << " zero_instruction_fetch_phys=0x" << top->fetch_phys_addr
                 << "\n";
         }

        if (isInvalidFetchPc()) {
            stream << "invalid_fetch_pc=0x" << std::hex << top->fetch_pc
                   << " image_phys=[0x" << platform.flash.kernelPhysicalBase
                   << ", 0x" << (platform.flash.kernelPhysicalBase + platform.image.imageSpan)
                   << ") flash_phys=[0x" << FLASH_BASE
                   << ", 0x" << (FLASH_BASE + platform.flash.flashImageSize)
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
                      << " r14=0x" << entry.r14
                      << " r15=0x" << entry.r15
                       << "\n";
            }
        }
#else
        if (isInvalidFetchPc()) {
            stream << "invalid_fetch_pc=0x" << std::hex << top->fetch_pc
                   << " image_phys=[0x" << platform.flash.kernelPhysicalBase
                   << ", 0x" << (platform.flash.kernelPhysicalBase + platform.image.imageSpan)
                   << ") flash_phys=[0x" << FLASH_BASE
                   << ", 0x" << (FLASH_BASE + platform.flash.flashImageSize)
                   << ") image_virt=[0x" << platform.image.virtBase
                   << ", 0x" << platform.image.virtEnd
                   << ")\n";
        }
#endif

        const auto stackPhysical = virtualToKernelPhysical(currentSp);
        if (stackPhysical && platform.ramContains(*stackPhysical, 8)) {
            stream << "stack_qwords:\n";
            for (unsigned index = 0; index < 8; ++index) {
                const uint64_t virtualAddress = currentSp + (index * 8ULL);
                const uint64_t physicalAddress = *stackPhysical + (index * 8ULL);
                if (!platform.ramContains(physicalAddress, 8)) {
                    break;
                }
                stream << "  [sp+0x" << std::hex << (index * 8ULL)
                       << "] va=0x" << virtualAddress
                       << " pa=0x" << physicalAddress
                       << " =0x" << platform.readU64(physicalAddress)
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
        iBusRequest = {};
        dBusRequest = {};
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
            const bool newRequest = !iBusRequest.active || iBusRequest.address != top->i_bus_adr;
            if (newRequest) {
                iBusRequest = {
                    .active = true,
                    .responseIssued = false,
                    .address = top->i_bus_adr,
                };
                top->i_bus_dat_r = 0;
                top->i_bus_ack = 0;
            } else if (!iBusRequest.responseIssued) {
                top->i_bus_dat_r = platform.readBusQword(top->i_bus_adr);
                top->i_bus_ack = 1;
                iBusRequest.responseIssued = true;
            } else {
                top->i_bus_dat_r = 0;
                top->i_bus_ack = 0;
            }
            top->i_bus_err = 0;
        } else {
            top->i_bus_dat_r = 0;
            top->i_bus_ack = 0;
            top->i_bus_err = 0;
            iBusRequest = {};
        }

        if (top->d_bus_cyc && top->d_bus_stb) {
            const bool newRequest = !dBusRequest.active ||
                dBusRequest.address != top->d_bus_adr ||
                dBusRequest.data != top->d_bus_dat_w ||
                dBusRequest.selectMask != top->d_bus_sel ||
                dBusRequest.write != static_cast<bool>(top->d_bus_we);
            if (newRequest) {
                dBusRequest = {
                    .active = true,
                    .responseIssued = false,
                    .address = top->d_bus_adr,
                    .data = top->d_bus_dat_w,
                    .selectMask = static_cast<uint8_t>(top->d_bus_sel),
                    .write = static_cast<bool>(top->d_bus_we),
                };
                top->d_bus_dat_r = 0;
                top->d_bus_ack = 0;
            } else if (!dBusRequest.responseIssued) {
                if (top->d_bus_we) {
                    platform.writeBus(top->d_bus_adr, top->d_bus_dat_w, top->d_bus_sel);
                } else {
                    top->d_bus_dat_r = platform.readBusQword(top->d_bus_adr);
                }
                top->d_bus_ack = 1;
                dBusRequest.responseIssued = true;
            } else {
                top->d_bus_dat_r = 0;
                top->d_bus_ack = 0;
            }
            top->d_bus_err = 0;
        } else {
            top->d_bus_dat_r = 0;
            top->d_bus_ack = 0;
            top->d_bus_err = 0;
            dBusRequest = {};
        }
    }

    void tick() {
        top->clk = 0;
        top->eval();
        top->clk = 1;
        top->eval();
        context->timeInc(2);
    }

    bool isInvalidFetchPc() const {
        const uint64_t fetchPc = top->fetch_pc;
        if (fetchPc == 0) {
            return false;
        }

        const bool inPhysicalImage =
            fetchPc >= platform.flash.kernelPhysicalBase &&
            fetchPc < platform.flash.kernelPhysicalBase + platform.image.imageSpan;
        const bool inFlashImage =
            fetchPc >= FLASH_BASE &&
            fetchPc < FLASH_BASE + platform.flash.flashImageSize;
        const bool inVirtualImage =
            fetchPc >= platform.image.virtBase &&
            fetchPc < platform.image.virtEnd;
        return !inPhysicalImage && !inVirtualImage && !inFlashImage;
    }

    bool isZeroInstructionExecution() const {
        return top->state == 3 && top->fetch_pc != 0 && top->current_instruction == 0;
    }

    std::optional<uint64_t> virtualToKernelPhysical(uint64_t address) const {
        if (address >= PAGE_OFFSET) {
            const uint64_t physical = address - PAGE_OFFSET + KERNEL_PHYSICAL_BASE;
            if (platform.ramContains(physical, 1)) {
                return physical;
            }
        }
        if (platform.ramContains(address, 1)) {
            return address;
        }
        return std::nullopt;
    }

#if LITTLE64_HARNESS_ENABLE_DEBUG
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

        maybeCaptureSymbolHit(cycle, platform.image.panicSymbol, "panic", firstPanicHit);
        maybeCaptureSymbolHit(cycle, platform.image.vpanicSymbol, "vpanic", firstVpanicHit);
        maybeCapturePrintkHit(cycle);
        maybeCapturePcpuSetupEntry(cycle);

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
            .r14 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r14,
            .r15 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r15,
        });
        if (recentTrace.size() > 64) {
            recentTrace.pop_front();
        }
    }

    std::optional<std::string> readVirtualString(uint64_t address) const {
        if (address == 0) {
            return std::nullopt;
        }

        std::string result;
        for (size_t index = 0; index < 160; ++index) {
            const auto physical = virtualToKernelPhysical(address + index);
            if (!physical || !platform.ramContains(*physical, 1)) {
                break;
            }
            const char ch = static_cast<char>(platform.ram[static_cast<size_t>(*physical - RAM_BASE)]);
            if (ch == '\0') {
                return result.empty() ? std::nullopt : std::optional<std::string>(result);
            }
            const unsigned char byte = static_cast<unsigned char>(ch);
            if ((byte < 0x20 || byte > 0x7e) && ch != '\n' && ch != '\r' && ch != '\t') {
                break;
            }
            result.push_back(ch);
        }

        if (result.empty()) {
            return std::nullopt;
        }
        if (result.size() == 160) {
            result += "...";
        }
        return result;
    }

    std::optional<uint64_t> readVirtualU64(uint64_t address) const {
        const auto physical = virtualToKernelPhysical(address);
        if (!physical || !platform.ramContains(*physical, 8)) {
            return std::nullopt;
        }
        return platform.readU64(*physical);
    }

    std::optional<uint32_t> readVirtualU32(uint64_t address) const {
        const auto physical = virtualToKernelPhysical(address);
        if (!physical || !platform.ramContains(*physical, 4)) {
            return std::nullopt;
        }
        uint32_t value = 0;
        std::memcpy(&value, platform.ramPointer(*physical), sizeof(value));
        return value;
    }

    std::optional<PcpuAllocInfoDump> readRawPcpuAllocInfo(uint64_t address) const {
        const auto staticSize = readVirtualU64(address + 0x00);
        const auto reservedSize = readVirtualU64(address + 0x08);
        const auto dynSize = readVirtualU64(address + 0x10);
        const auto unitSize = readVirtualU64(address + 0x18);
        const auto atomSize = readVirtualU64(address + 0x20);
        const auto allocSize = readVirtualU64(address + 0x28);
        const auto aiSize = readVirtualU64(address + 0x30);
        const auto nrGroups = readVirtualU32(address + 0x38);
        const auto group0NrUnits = readVirtualU32(address + 0x40);
        const auto group0BaseOffset = readVirtualU64(address + 0x48);
        const auto group0CpuMap = readVirtualU64(address + 0x50);
        if (!staticSize.has_value() || !reservedSize.has_value() || !dynSize.has_value() ||
            !unitSize.has_value() || !atomSize.has_value() || !allocSize.has_value() ||
            !aiSize.has_value() || !nrGroups.has_value() || !group0NrUnits.has_value() ||
            !group0BaseOffset.has_value() || !group0CpuMap.has_value()) {
            return std::nullopt;
        }
        uint32_t cpu0 = 0;
        if (const auto maybeCpu0 = readVirtualU32(*group0CpuMap)) {
            cpu0 = *maybeCpu0;
        }
        return PcpuAllocInfoDump{
            .address = address,
            .staticSize = *staticSize,
            .reservedSize = *reservedSize,
            .dynSize = *dynSize,
            .unitSize = *unitSize,
            .atomSize = *atomSize,
            .allocSize = *allocSize,
            .aiSize = *aiSize,
            .nrGroups = *nrGroups,
            .group0NrUnits = *group0NrUnits,
            .group0BaseOffset = *group0BaseOffset,
            .group0CpuMap = *group0CpuMap,
            .group0Cpu0 = cpu0,
        };
    }

    bool readVirtualWords(uint64_t address, std::array<uint64_t, 8>& words) const {
        for (size_t index = 0; index < words.size(); ++index) {
            const auto value = readVirtualU64(address + (index * 8ULL));
            if (!value.has_value()) {
                return false;
            }
            words[index] = *value;
        }
        return true;
    }

    std::optional<PcpuAllocInfoDump> tryDecodePcpuAllocInfo(uint64_t address) const {
        const auto dump = readRawPcpuAllocInfo(address);
        if (!dump.has_value()) {
            return std::nullopt;
        }
        if (dump->nrGroups == 0 || dump->nrGroups > 8 || dump->group0NrUnits == 0 || dump->group0NrUnits > 64) {
            return std::nullopt;
        }
        if (dump->unitSize == 0 || (dump->unitSize & (PAGE_SIZE - 1ULL)) != 0 || dump->atomSize == 0 || dump->allocSize == 0) {
            return std::nullopt;
        }
        return dump;
    }

    std::optional<PcpuAllocInfoDump> findCapturedPcpuAllocInfo() const {
        for (const auto& snapshot : recentPrintkHits) {
            if (const auto fromR10 = tryDecodePcpuAllocInfo(snapshot.r10)) {
                return fromR10;
            }
            if (const auto fromR9 = tryDecodePcpuAllocInfo(snapshot.r9)) {
                return fromR9;
            }
        }
        return std::nullopt;
    }

    void maybeCaptureSymbolHit(
        uint64_t cycle,
        const std::optional<uint64_t>& symbol,
        std::string_view name,
        std::optional<SymbolHitSnapshot>& snapshot
    ) {
        if (snapshot || !symbol || top->fetch_pc != *symbol) {
            return;
        }

        snapshot = SymbolHitSnapshot{
            .symbolName = std::string(name),
            .cycle = cycle,
            .pc = top->fetch_pc,
            .r1 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r1,
            .r2 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r2,
            .r3 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r3,
            .r4 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r4,
            .r5 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r5,
            .r6 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r6,
            .r7 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r7,
            .r8 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r8,
            .r9 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r9,
            .r10 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r10,
            .r11 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r11,
            .r13 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r13,
            .r14 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r14,
            .r15 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r15,
            .r1String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r1),
            .r2String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r2),
            .r3String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r3),
            .r4String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r4),
            .r5String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r5),
            .r6String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r6),
            .r7String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r7),
            .r8String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r8),
            .r9String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r9),
            .r10String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r10),
        };
    }

    void maybeCapturePrintkHit(uint64_t cycle) {
        if (!platform.image.printkSymbol || top->fetch_pc != *platform.image.printkSymbol) {
            return;
        }

        recentPrintkHits.push_back(SymbolHitSnapshot{
            .symbolName = "_printk",
            .cycle = cycle,
            .pc = top->fetch_pc,
            .r1 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r1,
            .r2 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r2,
            .r3 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r3,
            .r4 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r4,
            .r5 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r5,
            .r6 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r6,
            .r7 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r7,
            .r8 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r8,
            .r9 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r9,
            .r10 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r10,
            .r11 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r11,
            .r13 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r13,
            .r14 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r14,
            .r15 = top->rootp->little64_linux_boot_top__DOT__core__DOT__r15,
            .r1String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r1),
            .r2String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r2),
            .r3String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r3),
            .r4String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r4),
            .r5String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r5),
            .r6String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r6),
            .r7String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r7),
            .r8String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r8),
            .r9String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r9),
            .r10String = readVirtualString(top->rootp->little64_linux_boot_top__DOT__core__DOT__r10),
        });
        if (recentPrintkHits.size() > 8) {
            recentPrintkHits.pop_front();
        }
    }

    void maybeCapturePcpuSetupEntry(uint64_t cycle) {
        if (pcpuEntrySnapshot || !platform.image.pcpuSetupFirstChunkSymbol ||
            top->fetch_pc != *platform.image.pcpuSetupFirstChunkSymbol) {
            return;
        }

        PcpuEntrySnapshot snapshot{
            .cycle = cycle,
            .pc = top->fetch_pc,
            .aiVirtual = top->rootp->little64_linux_boot_top__DOT__core__DOT__r10,
            .baseVirtual = top->rootp->little64_linux_boot_top__DOT__core__DOT__r9,
            .aiPhysical = virtualToKernelPhysical(top->rootp->little64_linux_boot_top__DOT__core__DOT__r10),
            .basePhysical = virtualToKernelPhysical(top->rootp->little64_linux_boot_top__DOT__core__DOT__r9),
        };
        snapshot.aiWordsValid = readVirtualWords(snapshot.aiVirtual, snapshot.aiWords);
        snapshot.baseWordsValid = readVirtualWords(snapshot.baseVirtual, snapshot.baseWords);
        if (const auto rawDump = readRawPcpuAllocInfo(snapshot.aiVirtual)) {
            snapshot.aiDump = *rawDump;
            snapshot.aiDumpValid = true;
            if (snapshot.basePhysical.has_value()) {
                const uint64_t baseStart = *snapshot.basePhysical;
                const uint64_t baseEnd = baseStart + snapshot.aiDump.unitSize;
                snapshot.overlapsBase = snapshot.aiPhysical.has_value() &&
                    *snapshot.aiPhysical >= baseStart && *snapshot.aiPhysical < baseEnd;
            }
        }
        pcpuEntrySnapshot = snapshot;
    }

    bool panicCaptureComplete(uint64_t cycle, uint64_t graceCycles) const {
        if (!firstVpanicHit || !pcpuEntrySnapshot) {
            return false;
        }
        return cycle >= firstVpanicHit->cycle + graceCycles;
    }

    void printSymbolHit(std::ostream& stream, const SymbolHitSnapshot& snapshot) const {
        stream << "symbol_hit[" << snapshot.symbolName << "]: cycle=" << std::dec << snapshot.cycle
               << " pc=0x" << std::hex << snapshot.pc
               << " r1=0x" << snapshot.r1
               << " r2=0x" << snapshot.r2
               << " r3=0x" << snapshot.r3
               << " r4=0x" << snapshot.r4
               << " r5=0x" << snapshot.r5
               << " r6=0x" << snapshot.r6
               << " r7=0x" << snapshot.r7
               << " r8=0x" << snapshot.r8
               << " r9=0x" << snapshot.r9
               << " r10=0x" << snapshot.r10
               << " r11=0x" << snapshot.r11
               << " r13=0x" << snapshot.r13
               << " r14=0x" << snapshot.r14
               << " r15=0x" << snapshot.r15
               << "\n";
        if (snapshot.r1String) {
            stream << "  r1_str=\"" << *snapshot.r1String << "\"\n";
        }
        if (snapshot.r2String) {
            stream << "  r2_str=\"" << *snapshot.r2String << "\"\n";
        }
        if (snapshot.r3String) {
            stream << "  r3_str=\"" << *snapshot.r3String << "\"\n";
        }
        if (snapshot.r4String) {
            stream << "  r4_str=\"" << *snapshot.r4String << "\"\n";
        }
        if (snapshot.r5String) {
            stream << "  r5_str=\"" << *snapshot.r5String << "\"\n";
        }
        if (snapshot.r6String) {
            stream << "  r6_str=\"" << *snapshot.r6String << "\"\n";
        }
        if (snapshot.r7String) {
            stream << "  r7_str=\"" << *snapshot.r7String << "\"\n";
        }
        if (snapshot.r8String) {
            stream << "  r8_str=\"" << *snapshot.r8String << "\"\n";
        }
        if (snapshot.r10String) {
            stream << "  r10_str=\"" << *snapshot.r10String << "\"\n";
        }
        if (snapshot.r9String) {
            stream << "  r9_str=\"" << *snapshot.r9String << "\"\n";
        }
    }

    void printSymbolHit(std::ostream& stream, const std::optional<SymbolHitSnapshot>& snapshot) const {
        if (!snapshot) {
            return;
        }
        printSymbolHit(stream, *snapshot);
    }
#endif

    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vlittle64_linux_boot_top> top;
    Platform platform;
    bool debugTraceEnabled;
    IBusRequestTracker iBusRequest;
    DBusRequestTracker dBusRequest;
#if LITTLE64_HARNESS_ENABLE_DEBUG
    std::deque<TraceEntry> recentTrace;
    std::optional<SymbolHitSnapshot> firstPanicHit;
    std::optional<SymbolHitSnapshot> firstVpanicHit;
    std::optional<PcpuEntrySnapshot> pcpuEntrySnapshot;
    std::deque<SymbolHitSnapshot> recentPrintkHits;
#endif
};

struct Options {
    fs::path kernel;
    fs::path flash;
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
        } else if (arg == "--flash") {
            options.flash = fs::path(nextValue(arg));
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
    if (options.flash.empty()) {
        throw std::runtime_error("--flash is required");
    }
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        Verilated::commandArgs(argc, argv);
        const auto options = parseArguments(argc, argv);

        Platform platform(loadLinuxImage(options.kernel), loadFlashBootImage(options.flash));
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