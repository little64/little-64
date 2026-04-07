// start.c

#include "boot_abi.h"

#define SERIAL_BASE ((volatile unsigned char *)0xFFFFFFFFFFFF0000ULL)

static volatile Little64BootInfoFrame g_boot_info;

static const char banner[] = "BIOS READY\n";
static const char mode_phys[] = "BOOT MODE: PHYS\n";
static const char phase_init[] = "PHASE: INIT\n";
static const char phase_diag[] = "PHASE: DIAG\n";
static const char phase_done[] = "PHASE: DONE\n";
static const char summary_prefix[] = "SUMMARY: ";
static const char nl[] = "\n";

static volatile unsigned long g_diag_accum = 0;

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

static void serial_put_hex_digit(unsigned value) {
    const unsigned nibble = value & 0xFU;
    const unsigned char c = (unsigned char)(nibble < 10 ? ('0' + nibble) : ('A' + (nibble - 10)));
    *SERIAL_BASE = c;
}

static void serial_put_hex_u64(unsigned long long value) {
    for (int shift = 60; shift >= 0; shift -= 4) {
        serial_put_hex_digit((unsigned)(value >> shift));
    }
}

__attribute__((noinline))
static unsigned long long checksum_text(const char* s) {
    unsigned long long acc = 0x9E3779B97F4A7C15ULL;
    while (*s) {
        const unsigned long long ch = (unsigned long long)(unsigned char)(*s);
        acc ^= ch;
        acc += (acc << 6) + (acc >> 2) + 0x9E3779B97F4A7C15ULL;
        ++s;
    }
    return acc;
}

__attribute__((noinline))
static unsigned long long compute_boot_summary_value(unsigned long long seed) {
    unsigned long long x = seed;
    x ^= (unsigned long long)g_boot_info.memory_region_count;
    x += g_boot_info.physical_memory_size;
    x ^= (g_boot_info.boot_stack_physical_top >> 3);
    return x;
}

__attribute__((noinline))
static void emit_phase_line(const char* phase, const char* detail) {
    serial_puts(phase);
    serial_puts(detail);
}

__attribute__((noinline))
static void emit_summary_line(unsigned long long value) {
    serial_puts(summary_prefix);
    serial_put_hex_u64(value);
    serial_puts(nl);
}

__attribute__((noinline))
static unsigned long long mix_debug_value(unsigned long long value, unsigned salt) {
    unsigned long long x = value;
    x ^= ((unsigned long long)salt << 32) | (unsigned long long)salt;
    x = (x << 9) ^ (x >> 7) ^ 0xD1B54A32D192ED03ULL;
    return x;
}

__attribute__((noinline))
static void run_debug_fixture(void) {
    unsigned long long value = 0x123456789ABCDEF0ULL;
    value = compute_boot_summary_value(value);
    value = mix_debug_value(value, 1);
    value = mix_debug_value(value, 2);
    value = mix_debug_value(value, 3);
    g_diag_accum += (unsigned long)(value & 0xFFFFULL);
    value ^= (unsigned long long)g_diag_accum;

#ifdef LITTLE64_DEBUG_VERBOSE
    emit_phase_line(phase_init, nl);
    emit_phase_line(phase_diag, nl);
    emit_summary_line(value);
    emit_phase_line(phase_done, nl);
#else
    g_diag_accum ^= (unsigned long)(value & 0xFFFFFFFFULL);
#endif
}

__attribute__((naked))
void _start(void) {
    // Initialize stack pointer to 0x4000000 and jump to work().
    __asm__ volatile (
        "LDI #0, R13\n"
        "LDI.S1 #0, R13\n"
        "LDI.S2 #0, R13\n"
        "LDI.S3 #4, R13\n"
        "LDI64 work, R1\n"
        "MOVE R1, PC"
    );
}


void work(void) {
    init_boot_info_physical();
    serial_puts(banner);
    serial_puts(mode_phys);
    run_debug_fixture();

#ifdef LITTLE64_DEBUG_HOLD
    for (;;) {
        __asm__ volatile ("" ::: "memory");
    }
#else
    __asm__ volatile ("STOP");
#endif
}




