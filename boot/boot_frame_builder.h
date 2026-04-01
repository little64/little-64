#pragma once

#include "boot_abi.h"

#include <stddef.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline void little64_bootinfo_init_common(Little64BootInfoFrame* frame) {
    if (!frame) {
        return;
    }
    memset(frame, 0, sizeof(*frame));
    frame->magic = LITTLE64_BOOTINFO_MAGIC;
    frame->abi_version = LITTLE64_BOOTINFO_ABI_VERSION;
    frame->frame_size = (uint32_t)sizeof(Little64BootInfoFrame);
}

static inline void little64_bootinfo_init_physical(
    Little64BootInfoFrame* frame,
    uint64_t physical_memory_base,
    uint64_t physical_memory_size,
    uint64_t kernel_physical_base,
    uint64_t kernel_physical_size,
    uint64_t boot_stack_physical_top
) {
    little64_bootinfo_init_common(frame);
    if (!frame) {
        return;
    }

    frame->boot_flags = LITTLE64_BOOT_FLAG_PHYSICAL_MODE;
    frame->physical_memory_base = physical_memory_base;
    frame->physical_memory_size = physical_memory_size;
    frame->kernel_physical_base = kernel_physical_base;
    frame->kernel_physical_size = kernel_physical_size;
    frame->boot_stack_physical_top = boot_stack_physical_top;
}

static inline void little64_bootinfo_init_virtual(
    Little64BootInfoFrame* frame,
    uint64_t physical_memory_base,
    uint64_t physical_memory_size,
    uint64_t kernel_physical_base,
    uint64_t kernel_physical_size,
    uint64_t kernel_virtual_base,
    uint64_t kernel_entry_virtual,
    uint64_t page_table_root_physical,
    uint64_t boot_stack_physical_top
) {
    little64_bootinfo_init_common(frame);
    if (!frame) {
        return;
    }

    frame->boot_flags = LITTLE64_BOOT_FLAG_VIRTUAL_MODE;
    frame->physical_memory_base = physical_memory_base;
    frame->physical_memory_size = physical_memory_size;
    frame->kernel_physical_base = kernel_physical_base;
    frame->kernel_physical_size = kernel_physical_size;
    frame->kernel_virtual_base = kernel_virtual_base;
    frame->kernel_entry_virtual = kernel_entry_virtual;
    frame->page_table_root_physical = page_table_root_physical;
    frame->boot_stack_physical_top = boot_stack_physical_top;
}

static inline int little64_bootinfo_add_memory_region(
    Little64BootInfoFrame* frame,
    uint64_t base,
    uint64_t size,
    uint32_t type,
    uint32_t flags
) {
    if (!frame) {
        return -1;
    }
    if (frame->memory_region_count >= LITTLE64_BOOTINFO_MAX_REGIONS) {
        return -1;
    }

    const uint32_t idx = frame->memory_region_count;
    frame->memory_regions[idx].base = base;
    frame->memory_regions[idx].size = size;
    frame->memory_regions[idx].type = type;
    frame->memory_regions[idx].flags = flags;
    frame->memory_region_count = idx + 1;
    return 0;
}

#ifdef __cplusplus
}
#endif
