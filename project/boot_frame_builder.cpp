#include "boot_frame_builder.hpp"

namespace {

void appendRegions(Little64BootInfoFrame& frame, const std::vector<BootRegionSpec>& regions) {
    for (const auto& region : regions) {
        if (little64_bootinfo_add_memory_region(
                &frame,
                region.base,
                region.size,
                region.type,
                region.flags) != 0) {
            break;
        }
    }
}

} // namespace

Little64BootInfoFrame BootFrameBuilder::makePhysical(
    uint64_t physical_memory_base,
    uint64_t physical_memory_size,
    uint64_t kernel_physical_base,
    uint64_t kernel_physical_size,
    uint64_t boot_stack_physical_top,
    const std::vector<BootRegionSpec>& regions
) {
    Little64BootInfoFrame frame{};
    little64_bootinfo_init_physical(
        &frame,
        physical_memory_base,
        physical_memory_size,
        kernel_physical_base,
        kernel_physical_size,
        boot_stack_physical_top);
    appendRegions(frame, regions);
    return frame;
}

Little64BootInfoFrame BootFrameBuilder::makeVirtualHigherHalf(
    uint64_t physical_memory_base,
    uint64_t physical_memory_size,
    uint64_t kernel_physical_base,
    uint64_t kernel_physical_size,
    uint64_t kernel_virtual_base,
    uint64_t kernel_entry_virtual,
    uint64_t page_table_root_physical,
    uint64_t boot_stack_physical_top,
    const std::vector<BootRegionSpec>& regions
) {
    Little64BootInfoFrame frame{};
    little64_bootinfo_init_virtual(
        &frame,
        physical_memory_base,
        physical_memory_size,
        kernel_physical_base,
        kernel_physical_size,
        kernel_virtual_base,
        kernel_entry_virtual,
        page_table_root_physical,
        boot_stack_physical_top);
    appendRegions(frame, regions);
    return frame;
}
