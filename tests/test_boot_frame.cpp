#include "support/test_harness.hpp"
#include "project/boot_frame_builder.hpp"

#include <vector>

int main() {
    CHECK_EQ(sizeof(Little64MemoryRegion), 24ULL, "Boot ABI memory region size is stable");
    CHECK_EQ(sizeof(Little64BootInfoFrame), 872ULL, "Boot ABI frame size is stable");

    {
        std::vector<BootRegionSpec> regions = {
            { .base = 0x0, .size = 0x100000, .type = LITTLE64_MEM_REGION_RESERVED, .flags = 0 },
            { .base = 0x100000, .size = 0x3F00000, .type = LITTLE64_MEM_REGION_USABLE, .flags = 0 },
        };

        const Little64BootInfoFrame frame = BootFrameBuilder::makePhysical(
            0x0,
            0x4000000,
            0x0,
            0x20000,
            0x400000,
            regions);

        CHECK_EQ(frame.magic, LITTLE64_BOOTINFO_MAGIC, "Physical frame magic");
        CHECK_EQ(frame.abi_version, LITTLE64_BOOTINFO_ABI_VERSION, "Physical frame ABI version");
        CHECK_EQ(frame.boot_flags, LITTLE64_BOOT_FLAG_PHYSICAL_MODE, "Physical mode flag");
        CHECK_EQ(frame.memory_region_count, 2ULL, "Physical frame region count");
        CHECK_EQ(frame.kernel_virtual_base, 0ULL, "Physical frame has no virtual kernel base");
    }

    {
        std::vector<BootRegionSpec> regions;
        for (uint32_t i = 0; i < LITTLE64_BOOTINFO_MAX_REGIONS + 5; ++i) {
            regions.push_back(BootRegionSpec{
                .base = static_cast<uint64_t>(i) * 0x1000,
                .size = 0x1000,
                .type = LITTLE64_MEM_REGION_USABLE,
                .flags = 0,
            });
        }

        const Little64BootInfoFrame frame = BootFrameBuilder::makeVirtualHigherHalf(
            0x0,
            0x8000000,
            0x200000,
            0x300000,
            0xFFFF800000000000ULL,
            0xFFFF800000001000ULL,
            0x00100000,
            0x900000,
            regions);

        CHECK_EQ(frame.boot_flags, LITTLE64_BOOT_FLAG_VIRTUAL_MODE, "Virtual mode flag");
        CHECK_EQ(frame.kernel_virtual_base, 0xFFFF800000000000ULL, "Higher-half base");
        CHECK_EQ(frame.kernel_entry_virtual, 0xFFFF800000001000ULL, "Higher-half entry");
        CHECK_EQ(frame.page_table_root_physical, 0x00100000ULL, "Page table root physical address");
        CHECK_EQ(frame.memory_region_count, static_cast<uint64_t>(LITTLE64_BOOTINFO_MAX_REGIONS), "Region list is clamped to max ABI capacity");
    }

    return print_summary();
}
