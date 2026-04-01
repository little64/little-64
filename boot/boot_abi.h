#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LITTLE64_BOOTINFO_MAGIC UINT64_C(0x4C3634424F4F5446)
#define LITTLE64_BOOTINFO_ABI_VERSION 1u
#define LITTLE64_BOOTINFO_MAX_REGIONS 32u

#define LITTLE64_BOOT_FLAG_PHYSICAL_MODE UINT64_C(1)
#define LITTLE64_BOOT_FLAG_VIRTUAL_MODE  UINT64_C(2)

#define LITTLE64_MEM_REGION_USABLE   1u
#define LITTLE64_MEM_REGION_RESERVED 2u
#define LITTLE64_MEM_REGION_MMIO     3u

#pragma pack(push, 1)
typedef struct Little64MemoryRegion {
    uint64_t base;
    uint64_t size;
    uint32_t type;
    uint32_t flags;
} Little64MemoryRegion;

typedef struct Little64BootInfoFrame {
    uint64_t magic;
    uint32_t abi_version;
    uint32_t frame_size;

    uint64_t boot_flags;

    uint64_t physical_memory_base;
    uint64_t physical_memory_size;

    uint64_t kernel_physical_base;
    uint64_t kernel_physical_size;

    uint64_t kernel_virtual_base;
    uint64_t kernel_entry_virtual;

    uint64_t page_table_root_physical;
    uint64_t boot_stack_physical_top;

    uint64_t reserved0;

    uint32_t memory_region_count;
    uint32_t reserved1;

    Little64MemoryRegion memory_regions[LITTLE64_BOOTINFO_MAX_REGIONS];
} Little64BootInfoFrame;
#pragma pack(pop)

#ifdef __cplusplus
}
#endif
