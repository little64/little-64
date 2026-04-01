// start.c

#include "boot_abi.h"

#define SERIAL_BASE ((volatile unsigned char *)0xFFFFFFFFFFFF0000ULL)

static volatile Little64BootInfoFrame g_boot_info;

static const char banner[] = "BIOS READY\n";
static const char mode_phys[] = "BOOT MODE: PHYS\n";

static void serial_puts(const char* s) {
    while (*s) {
        *SERIAL_BASE = (unsigned char)*s;
        ++s;
    }
}

static void init_boot_info_physical(void) {
    g_boot_info.magic = LITTLE64_BOOTINFO_MAGIC;
    g_boot_info.abi_version = LITTLE64_BOOTINFO_ABI_VERSION;
    g_boot_info.frame_size = (uint32_t)sizeof(Little64BootInfoFrame);
    g_boot_info.boot_flags = LITTLE64_BOOT_FLAG_PHYSICAL_MODE;

    g_boot_info.physical_memory_base = 0x0;
    g_boot_info.physical_memory_size = 0x04000000ULL;
    g_boot_info.kernel_physical_base = 0x0;
    g_boot_info.kernel_physical_size = 0;
    g_boot_info.boot_stack_physical_top = 0x04000000ULL;

    g_boot_info.memory_region_count = 1;
    g_boot_info.memory_regions[0].base = 0x0;
    g_boot_info.memory_regions[0].size = 0x04000000ULL;
    g_boot_info.memory_regions[0].type = LITTLE64_MEM_REGION_USABLE;
    g_boot_info.memory_regions[0].flags = 0;
}

__attribute__((naked))
void _start(void) {
    // Initialize stack pointer to 0x4000000 and jump to work().
    __asm__ volatile (
        "LDI #0, R13\n"
        "LDI.S1 #0, R13\n"
        "LDI.S2 #0, R13\n"
        "LDI.S3 #4, R13\n"
        "LDI64 #work, R1\n"
        "MOVE R1, PC"
    );
}


void work(void) {
    init_boot_info_physical();
    serial_puts(banner);
    serial_puts(mode_phys);

    __asm__ volatile ("STOP");
}




