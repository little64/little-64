#define FLASH_BASE 0x20000000ULL
#ifndef L64_UART_BASE
/* Canonical LiteX helper contract UART CSR base. */
#define L64_UART_BASE 0xF0004000ULL
#endif
#define LITEUART_BASE L64_UART_BASE
#define LITEUART_RXTX_OFFSET 0x00ULL
#define LITEUART_TXFULL_OFFSET 0x04ULL
#define FLASH_BOOT_MAGIC 0x4C3634464C415348ULL
#define FLASH_BOOT_ABI_VERSION 1ULL
#define FLASH_BOOT_HEADER_OFFSET 0x00002000ULL
#define STAGE0_STACK_TOP 0x10004000ULL
#define KERNEL_PHYS_BASE_MIN 0x40000000ULL

typedef unsigned char u8;
typedef unsigned long long u64;

extern u8 __bss_start[];
extern u8 __bss_end[];

typedef struct Little64LiteXFlashBootHeader {
    u64 magic;
    u64 abi_version;
    u64 kernel_flash_offset;
    u64 kernel_copy_size;
    u64 kernel_physical_base;
    u64 kernel_entry_physical;
    u64 dtb_flash_offset;
    u64 dtb_size;
    u64 dtb_physical;
    u64 kernel_boot_stack_top;
    u64 flash_image_size;
    u64 reserved0;
    u64 reserved1;
    u64 reserved2;
    u64 reserved3;
    u64 reserved4;
} Little64LiteXFlashBootHeader;

static volatile u8* const liteuart_rxtx = (volatile u8*)(LITEUART_BASE + LITEUART_RXTX_OFFSET);
static volatile u8* const liteuart_txfull = (volatile u8*)(LITEUART_BASE + LITEUART_TXFULL_OFFSET);
static const Little64LiteXFlashBootHeader* const flash_header =
    (const Little64LiteXFlashBootHeader*)(FLASH_BASE + FLASH_BOOT_HEADER_OFFSET);

static void serial_putc(char c) {
    while (*liteuart_txfull != 0) {
    }
    *liteuart_rxtx = (u8)c;
}

static void serial_puts(const char* s) {
    while (*s != '\0') {
        serial_putc(*s);
        ++s;
    }
}

static void serial_put_hex_digit(u8 nibble) {
    const char digit = (nibble < 10) ? (char)('0' + nibble) : (char)('A' + (nibble - 10));
    serial_putc(digit);
}

static void serial_put_hex_u64(u64 value) {
    serial_puts("0x");
    for (unsigned nibble_index = 0; nibble_index < 16; ++nibble_index) {
        const unsigned shift = (15U - nibble_index) * 4U;
        const u8 nibble = (u8)((value >> shift) & 0xFULL);
        serial_put_hex_digit(nibble);
    }
}

static void serial_put_labeled_hex(const char* label, u64 value) {
    serial_puts(label);
    serial_put_hex_u64(value);
}

static void serial_put_copy_summary(
    const char* image_name,
    u64 flash_offset,
    u64 physical_address,
    u64 size
) {
    serial_puts("stage0: copying ");
    serial_puts(image_name);
    serial_put_labeled_hex(" flash_offset=", flash_offset);
    serial_put_labeled_hex(" phys=", physical_address);
    serial_put_labeled_hex(" size=", size);
    serial_putc('\n');
}

static void clear_bss(void) {
    volatile u8* p = __bss_start;

    while (p < __bss_end) {
        *p = 0;
        ++p;
    }
}

static void copy_to_physical(u64 destination, const u8* source, u64 size) {
    volatile u8* dst = (volatile u8*)destination;
    u64 source_address = (u64)source;

    if (((destination | source_address) & 0x7ULL) == 0) {
        volatile u64* dst64 = (volatile u64*)destination;
        const volatile u64* src64 = (const volatile u64*)source;

        while (size >= 8) {
            *dst64 = *src64;
            ++dst64;
            ++src64;
            size -= 8;
        }

        dst = (volatile u8*)dst64;
        source = (const u8*)src64;
    }

    while (size != 0) {
        *dst = *source;
        ++dst;
        ++source;
        --size;
    }
}

__attribute__((noreturn))
static void fail_hard(const char* message) {
    serial_puts("stage0: error: ");
    serial_puts(message);
    serial_putc('\n');
    for (;;) {
        __asm__ volatile ("STOP");
    }
}

__attribute__((noreturn))
static void fail_hard_expected_hex(const char* message, u64 actual, u64 expected) {
    serial_puts("stage0: error: ");
    serial_puts(message);
    serial_put_labeled_hex(" actual=", actual);
    serial_put_labeled_hex(" expected=", expected);
    serial_putc('\n');
    for (;;) {
        __asm__ volatile ("STOP");
    }
}

static void describe_flash_header(const Little64LiteXFlashBootHeader* header) {
    serial_puts("stage0: flash header");
    serial_put_labeled_hex(" abi=", header->abi_version);
    serial_put_labeled_hex(" flash_image_size=", header->flash_image_size);
    serial_putc('\n');

    serial_puts("stage0: kernel plan");
    serial_put_labeled_hex(" flash_offset=", header->kernel_flash_offset);
    serial_put_labeled_hex(" phys=", header->kernel_physical_base);
    serial_put_labeled_hex(" entry=", header->kernel_entry_physical);
    serial_put_labeled_hex(" size=", header->kernel_copy_size);
    serial_putc('\n');

    serial_puts("stage0: dtb plan");
    serial_put_labeled_hex(" flash_offset=", header->dtb_flash_offset);
    serial_put_labeled_hex(" phys=", header->dtb_physical);
    serial_put_labeled_hex(" size=", header->dtb_size);
    serial_put_labeled_hex(" stack_top=", header->kernel_boot_stack_top);
    serial_putc('\n');
}

static void validate_header_or_fail(const Little64LiteXFlashBootHeader* header) {
    const u64 kernel_end = header->kernel_flash_offset + header->kernel_copy_size;
    const u64 dtb_end = header->dtb_flash_offset + header->dtb_size;

    if (header->magic != FLASH_BOOT_MAGIC) {
        fail_hard_expected_hex("flash boot magic mismatch", header->magic, FLASH_BOOT_MAGIC);
    }
    if (header->abi_version != FLASH_BOOT_ABI_VERSION) {
        fail_hard_expected_hex("flash boot ABI mismatch", header->abi_version, FLASH_BOOT_ABI_VERSION);
    }
    describe_flash_header(header);

    if (header->kernel_copy_size == 0) {
        fail_hard("kernel copy size is zero");
    }
    if (header->dtb_size == 0) {
        fail_hard("dtb size is zero");
    }
    if (kernel_end < header->kernel_flash_offset) {
        fail_hard("kernel flash range overflowed");
    }
    if (dtb_end < header->dtb_flash_offset) {
        fail_hard("dtb flash range overflowed");
    }
    if (kernel_end > header->flash_image_size) {
        fail_hard("kernel copy range exceeds flash image size");
    }
    if (dtb_end > header->flash_image_size) {
        fail_hard("dtb copy range exceeds flash image size");
    }
    if (header->kernel_physical_base < KERNEL_PHYS_BASE_MIN) {
        fail_hard("kernel physical base is below the reserved low-memory window");
    }
    if (header->kernel_entry_physical < header->kernel_physical_base) {
        fail_hard("kernel entry lies below the copied kernel image");
    }
    if (header->dtb_physical < header->kernel_physical_base + header->kernel_copy_size) {
        fail_hard("dtb physical address overlaps the copied kernel image");
    }
    if (header->kernel_boot_stack_top <= header->dtb_physical + header->dtb_size) {
        fail_hard("kernel boot stack overlaps the copied dtb");
    }
}

__attribute__((noreturn))
static void handoff_to_kernel(u64 dtb_physical, u64 stack_top, u64 entry_physical) {
    __asm__ volatile (
        "MOVE %0, R1\n"
        "MOVE %1, R13\n"
        "MOVE %2, PC\n"
        :
        : "r"(dtb_physical), "r"(stack_top), "r"(entry_physical)
        : "R1", "R13"
    );
    __builtin_unreachable();
}

__attribute__((used, noinline))
static void litex_soc_boot_entry(void) {
    serial_puts("stage0: entered from SPI flash\n");
    serial_put_labeled_hex("stage0: scratch stack top=", STAGE0_STACK_TOP);
    serial_putc('\n');

    clear_bss();
    serial_puts("stage0: cleared .bss\n");
    serial_put_labeled_hex("stage0: validating flash boot header at ", FLASH_BASE + FLASH_BOOT_HEADER_OFFSET);
    serial_putc('\n');
    validate_header_or_fail(flash_header);
    serial_puts("stage0: flash boot header accepted\n");

    serial_put_copy_summary(
        "kernel",
        flash_header->kernel_flash_offset,
        flash_header->kernel_physical_base,
        flash_header->kernel_copy_size
    );

    copy_to_physical(
        flash_header->kernel_physical_base,
        (const u8*)(FLASH_BASE + flash_header->kernel_flash_offset),
        flash_header->kernel_copy_size
    );
    serial_puts("stage0: kernel image copied\n");

    serial_put_copy_summary(
        "dtb",
        flash_header->dtb_flash_offset,
        flash_header->dtb_physical,
        flash_header->dtb_size
    );
    copy_to_physical(
        flash_header->dtb_physical,
        (const u8*)(FLASH_BASE + flash_header->dtb_flash_offset),
        flash_header->dtb_size
    );
    serial_puts("stage0: dtb copied\n");

    serial_puts("stage0: handing off to kernel");
    serial_put_labeled_hex(" entry=", flash_header->kernel_entry_physical);
    serial_put_labeled_hex(" dtb=", flash_header->dtb_physical);
    serial_put_labeled_hex(" stack_top=", flash_header->kernel_boot_stack_top);
    serial_putc('\n');
    handoff_to_kernel(
        flash_header->dtb_physical,
        flash_header->kernel_boot_stack_top,
        flash_header->kernel_entry_physical
    );
}

__attribute__((naked, section(".text.boot")))
void _start(void) {
    __asm__ volatile (
        "LDI #0, R13\n"
        "LDI.S1 #0x40, R13\n"
        "LDI.S3 #0x10, R13\n"
        "LDI64 litex_soc_boot_entry, R1\n"
        "MOVE R1, PC\n"
    );
}