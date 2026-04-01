#pragma once

#include "boot/boot_abi.h"
#include "boot/boot_frame_builder.h"

#include <vector>

struct BootRegionSpec {
    uint64_t base = 0;
    uint64_t size = 0;
    uint32_t type = LITTLE64_MEM_REGION_RESERVED;
    uint32_t flags = 0;
};

class BootFrameBuilder {
public:
    static Little64BootInfoFrame makePhysical(
        uint64_t physical_memory_base,
        uint64_t physical_memory_size,
        uint64_t kernel_physical_base,
        uint64_t kernel_physical_size,
        uint64_t boot_stack_physical_top,
        const std::vector<BootRegionSpec>& regions
    );

    static Little64BootInfoFrame makeVirtualHigherHalf(
        uint64_t physical_memory_base,
        uint64_t physical_memory_size,
        uint64_t kernel_physical_base,
        uint64_t kernel_physical_size,
        uint64_t kernel_virtual_base,
        uint64_t kernel_entry_virtual,
        uint64_t page_table_root_physical,
        uint64_t boot_stack_physical_top,
        const std::vector<BootRegionSpec>& regions
    );
};
