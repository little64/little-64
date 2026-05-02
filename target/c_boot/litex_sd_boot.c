#include "litex_sd_boot_regs.h"

#if L64_HAVE_SDRAM_INIT
#include <generated/csr.h>
#include <generated/sdram_phy.h>
#include <liblitedram/sdram.h>
#endif

#define STAGE0_STACK_TOP 0x10004000ULL
#define PAGE_SIZE 4096ULL
#define EARLY_PT_SCRATCH_PAGES 30ULL
#define ELF_HEADER_SCRATCH_SIZE 4096ULL
#define STAGE0_DMA_SCRATCH_SIZE SD_BLOCK_SIZE
#define STAGE0_SDRAM_TEST_WORDS 8U
#define STAGE0_LOAD_PROGRESS_MIN_STEP 0x00001000U
#define STAGE0_LOAD_PROGRESS_MAX_STEP 0x00040000U
#define STAGE0_TRANSFER_BUFFER_SIZE 4096U
#define SD_BLOCK_SIZE 512U
#define FAT32_EOC_MIN 0x0FFFFFF8UL
#define FAT32_ATTR_LONG_NAME 0x0FUL
#define FAT32_ATTR_DIRECTORY 0x10U
#define FAT32_ATTR_VOLUME 0x08U
#define FAT32_INVALID_CACHE_LBA 0xFFFFFFFFU
#define STAGE0_BOOT_CHECKSUM_MAGIC 0x4C36434BU
#define STAGE0_BOOT_CHECKSUM_VERSION 1U
#define EM_LITTLE64 0x4C36U
#define PT_LOAD 1U

#define SD_OK 0U
#define SD_TIMEOUT 2U
#define SD_CRCERROR 1U

#define SDCARD_CTRL_DATA_TRANSFER_NONE 0U
#define SDCARD_CTRL_DATA_TRANSFER_READ 1U
#define SDCARD_CTRL_RESPONSE_NONE 0U
#define SDCARD_CTRL_RESPONSE_SHORT 1U
#define SDCARD_CTRL_RESPONSE_LONG 2U
#define SDCARD_CTRL_RESPONSE_SHORT_BUSY 3U
/*
 * Enable 4-bit filesystem reads for testing.  The earlier framing issue
 * (shifted payload bytes on 512-byte CMD17 reads) is believed to be resolved
 * with the upstream litesdcard cmd_done-flag fix (PR #54 / 2025.12 release);
 * set to 1U to fall back to the stable 1-bit path if the problem recurs.
 */
#define SDCARD_NATIVE_FORCE_1BIT_FILESYSTEM_IO 0U

#if defined(L64_SDCARD_INTERFACE_SPI)
#define SDCARD_SPI_R1_IDLE 0x01U
#define SDCARD_SPI_R1_ILLEGAL_COMMAND 0x04U
#define SDCARD_SPI_DATA_TOKEN_START_BLOCK 0xFEU
#define SDCARD_SPI_INIT_CLK_HZ 400000U
#define SDCARD_SPI_POST_INIT_CLK_HZ 10000000U
#define SDCARD_SPI_DEBUG_TRANSFER_BUDGET 4U
#define SDCARD_SPI_DEBUG_TIMEOUT_PROGRESS 25000U
#define SDCARD_SPI_CONTROL_START 0x00000001U
#define SDCARD_SPI_CONTROL_LENGTH_SHIFT 8U
#ifndef L64_SDCARD_SPI_DATA_WIDTH
#define L64_SDCARD_SPI_DATA_WIDTH 8U
#endif
#define SDCARD_SPI_STATUS_DONE 0x00000001U
#define SDCARD_SPI_CS_SELECT_CHIP0 0x00000001U
#define SDCARD_SPI_CS_MODE_MANUAL 0x00010000U
#define SDCARD_SPI_CS_ASSERT (SDCARD_SPI_CS_MODE_MANUAL | SDCARD_SPI_CS_SELECT_CHIP0)
#define SDCARD_SPI_CS_DEASSERT SDCARD_SPI_CS_MODE_MANUAL
#endif

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef long long s64;

#ifndef L64_UART_EVENT_MASK
#define L64_UART_EVENT_MASK 0x00000003U
#endif

extern u8 __bss_start[];
extern u8 __bss_end[];

typedef struct Stage0FileInfo {
    u32 first_cluster;
    u32 size;
} Stage0FileInfo;

typedef struct Stage0Fat32Volume {
    u32 partition_lba;
    u32 sectors_per_cluster;
    u32 first_fat_lba;
    u32 fat_sector_count;
    u32 first_data_lba;
    u32 root_cluster;
} Stage0Fat32Volume;

typedef struct Stage0Progress {
    const char* label;
    u32 total;
    u32 completed;
    u32 next_report;
    u32 report_step;
} Stage0Progress;

typedef struct Stage0BootChecksums {
    u32 magic;
    u32 version;
    u32 kernel_image_crc32;
    u32 kernel_image_size;
    u32 dtb_crc32;
    u32 dtb_size;
    u32 reserved0;
    u32 reserved1;
} Stage0BootChecksums;

static volatile u8* const liteuart_rxtx = (volatile u8*)L64_UART_RXTX_ADDR;
static volatile u32* const liteuart_txfull = (volatile u32*)L64_UART_TXFULL_ADDR;
#if defined(L64_UART_EV_PENDING_ADDR)
static volatile u32* const liteuart_ev_pending = (volatile u32*)L64_UART_EV_PENDING_ADDR;
#endif
#if defined(L64_UART_EV_ENABLE_ADDR)
static volatile u32* const liteuart_ev_enable = (volatile u32*)L64_UART_EV_ENABLE_ADDR;
#endif
#if defined(L64_UART_PHY_TUNING_WORD_ADDR)
static volatile u32* const liteuart_phy_tuning_word = (volatile u32*)L64_UART_PHY_TUNING_WORD_ADDR;
#endif
#if defined(L64_SDCARD_INTERFACE_NATIVE)
static volatile u32* const sdcard_block2mem_dma_base_hi = (volatile u32*)L64_SDCARD_BLOCK2MEM_DMA_BASE_ADDR;
static volatile u32* const sdcard_block2mem_dma_base_lo = (volatile u32*)(L64_SDCARD_BLOCK2MEM_DMA_BASE_ADDR + 4ULL);
static volatile u32* const sdcard_block2mem_dma_length = (volatile u32*)L64_SDCARD_BLOCK2MEM_DMA_LENGTH_ADDR;
static volatile u32* const sdcard_block2mem_dma_enable = (volatile u32*)L64_SDCARD_BLOCK2MEM_DMA_ENABLE_ADDR;
static volatile u32* const sdcard_block2mem_dma_done = (volatile u32*)L64_SDCARD_BLOCK2MEM_DMA_DONE_ADDR;
static volatile u32* const sdcard_core_cmd_argument = (volatile u32*)L64_SDCARD_CORE_CMD_ARGUMENT_ADDR;
static volatile u32* const sdcard_core_cmd_command = (volatile u32*)L64_SDCARD_CORE_CMD_COMMAND_ADDR;
static volatile u32* const sdcard_core_cmd_send = (volatile u32*)L64_SDCARD_CORE_CMD_SEND_ADDR;
static volatile u32* const sdcard_core_cmd_response = (volatile u32*)L64_SDCARD_CORE_CMD_RESPONSE_ADDR;
static volatile u32* const sdcard_core_cmd_event = (volatile u32*)L64_SDCARD_CORE_CMD_EVENT_ADDR;
static volatile u32* const sdcard_core_data_event = (volatile u32*)L64_SDCARD_CORE_DATA_EVENT_ADDR;
static volatile u32* const sdcard_core_block_length = (volatile u32*)L64_SDCARD_CORE_BLOCK_LENGTH_ADDR;
static volatile u32* const sdcard_core_block_count = (volatile u32*)L64_SDCARD_CORE_BLOCK_COUNT_ADDR;
static volatile u32* const sdcard_phy_clock_divider = (volatile u32*)L64_SDCARD_PHY_CLOCK_DIVIDER_ADDR;
static volatile u32* const sdcard_phy_initialize = (volatile u32*)L64_SDCARD_PHY_INITIALIZE_ADDR;
static volatile u32* const sdcard_phy_settings = (volatile u32*)L64_SDCARD_PHY_SETTINGS_ADDR;
#if defined(L64_SDCARD_PHY_CARD_DETECT_ADDR)
static volatile u32* const sdcard_phy_card_detect = (volatile u32*)L64_SDCARD_PHY_CARD_DETECT_ADDR;
#endif
#if defined(L64_SDCARD_DEBUG_SIGNALS_ADDR)
static volatile u32* const sdcard_debug_signals = (volatile u32*)L64_SDCARD_DEBUG_SIGNALS_ADDR;
static volatile u32* const sdcard_debug_cmd_i_transitions = (volatile u32*)L64_SDCARD_DEBUG_CMD_I_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_cmd_o_transitions = (volatile u32*)L64_SDCARD_DEBUG_CMD_O_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_cmd_oe_transitions = (volatile u32*)L64_SDCARD_DEBUG_CMD_OE_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_data0_i_transitions = (volatile u32*)L64_SDCARD_DEBUG_DATA0_I_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_clk_transitions = (volatile u32*)L64_SDCARD_DEBUG_CLK_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_cmd_i_released_transitions = (volatile u32*)L64_SDCARD_DEBUG_CMD_I_RELEASED_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_data1_i_transitions = (volatile u32*)L64_SDCARD_DEBUG_DATA1_I_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_data2_i_transitions = (volatile u32*)L64_SDCARD_DEBUG_DATA2_I_TRANSITIONS_ADDR;
static volatile u32* const sdcard_debug_data3_i_transitions = (volatile u32*)L64_SDCARD_DEBUG_DATA3_I_TRANSITIONS_ADDR;
#endif
static u32 sdcard_last_cmd;
static u32 sdcard_last_cmd_argument;
static u32 sdcard_last_cmd_response_type;
static u32 sdcard_last_cmd_data_type;
static u32 sdcard_last_cmd_status;
static u32 sdcard_last_cmd_event;
static u32 sdcard_last_cmd_response_words[4];
static u32 sdcard_last_data_status;
static u32 sdcard_last_data_event;

#define SDCARD_PHY_WIDTH_1BIT 0U
#define SDCARD_PHY_WIDTH_4BIT 1U
#elif defined(L64_SDCARD_INTERFACE_SPI)
static volatile u32* const sdcard_spi_control = (volatile u32*)L64_SDCARD_SPI_CONTROL_ADDR;
static volatile u32* const sdcard_spi_status = (volatile u32*)L64_SDCARD_SPI_STATUS_ADDR;
static volatile u32* const sdcard_spi_mosi = (volatile u32*)L64_SDCARD_SPI_MOSI_ADDR;
static volatile u32* const sdcard_spi_miso = (volatile u32*)L64_SDCARD_SPI_MISO_ADDR;
static volatile u32* const sdcard_spi_cs = (volatile u32*)L64_SDCARD_SPI_CS_ADDR;
static volatile u32* const sdcard_spi_loopback = (volatile u32*)L64_SDCARD_SPI_LOOPBACK_ADDR;
static volatile u32* const sdcard_spi_clk_divider = (volatile u32*)L64_SDCARD_SPI_CLK_DIVIDER_ADDR;
static u32 sdcard_spi_uses_block_addressing;
static u32 sdcard_spi_transfer_debug_counter;
#else
#error "stage0 requires either L64_SDCARD_INTERFACE_NATIVE or L64_SDCARD_INTERFACE_SPI"
#endif
static Stage0Fat32Volume fat32_volume;
static u32 fat32_cached_fat_sector_lba = FAT32_INVALID_CACHE_LBA;
static u8 fat32_cached_fat_sector[SD_BLOCK_SIZE];
static u8 sector_buffer[SD_BLOCK_SIZE];
static u8 transfer_buffer[STAGE0_TRANSFER_BUFFER_SIZE];
static u8 elf_header_scratch[ELF_HEADER_SCRATCH_SIZE];

static const u32 crc32_nibble_table[16] = {
    0x00000000U, 0x1DB71064U, 0x3B6E20C8U, 0x26D930ACU,
    0x76DC4190U, 0x6B6B51F4U, 0x4DB26158U, 0x5005713CU,
    0xEDB88320U, 0xF00F9344U, 0xD6D6A3E8U, 0xCB61B38CU,
    0x9B64C2B0U, 0x86D3D2D4U, 0xA00AE278U, 0xBDBDF21CU,
};

s64 __muldi3(s64 a, s64 b) {
    int negate = 0;
    u64 multiplicand;
    u64 multiplier;
    u64 result = 0ULL;

    if (a < 0) {
        multiplicand = (u64)(-a);
        negate ^= 1;
    } else {
        multiplicand = (u64)a;
    }
    if (b < 0) {
        multiplier = (u64)(-b);
        negate ^= 1;
    } else {
        multiplier = (u64)b;
    }

    while (multiplier != 0ULL) {
        if ((multiplier & 1ULL) != 0ULL) {
            result += multiplicand;
        }
        multiplicand <<= 1U;
        multiplier >>= 1U;
    }

    return negate ? -(s64)result : (s64)result;
}

static void liteuart_initialize(void) {
#if defined(L64_UART_EV_ENABLE_ADDR)
    *liteuart_ev_enable = 0U;
#endif
#if defined(L64_UART_EV_PENDING_ADDR)
    *liteuart_ev_pending = L64_UART_EVENT_MASK;
#endif
#if defined(L64_UART_PHY_TUNING_WORD_ADDR)
    *liteuart_phy_tuning_word = L64_UART_PHY_TUNING_WORD_VALUE;
#endif
}

static void serial_putc(char c) {
    if (c == '\n') {
        serial_putc('\r');
    }

    while (*liteuart_txfull != 0U) {
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
    serial_putc((char)(nibble < 10 ? ('0' + nibble) : ('A' + (nibble - 10))));
}

static void serial_put_hex_u32(u32 value) {
    unsigned shift = 28U;
    serial_puts("0x");
    while (1) {
        serial_put_hex_digit((u8)((value >> shift) & 0xFU));
        if (shift == 0U) {
            break;
        }
        shift -= 4U;
    }
}

static void serial_put_hex_u64(u64 value) {
    unsigned shift = 60U;
    serial_puts("0x");
    while (1) {
        serial_put_hex_digit((u8)((value >> shift) & 0xFU));
        if (shift == 0U) {
            break;
        }
        shift -= 4U;
    }
}

static void serial_put_hex_u8(u8 value) {
    serial_put_hex_digit((u8)((value >> 4U) & 0x0FU));
    serial_put_hex_digit((u8)(value & 0x0FU));
}

static void serial_dump_bytes(const char* label, const u8* data, u32 size) {
    u32 index = 0U;

    serial_puts(label);
    while (index < size) {
        serial_putc(' ');
        serial_put_hex_u8(data[index]);
        ++index;
    }
    serial_putc('\n');
}

static void serial_put_labeled_hex64(const char* label, u64 value) {
    serial_puts(label);
    serial_put_hex_u64(value);
}

static void serial_put_labeled_hex32(const char* label, u32 value) {
    serial_puts(label);
    serial_put_hex_u32(value);
}

static int image_window_fits_ram(u64 physical_base, u64 image_span) {
    return physical_base >= L64_RAM_BASE &&
           physical_base + image_span <= L64_RAM_BASE + L64_RAM_SIZE;
}

static u64 pointer_to_u64(const void* ptr) {
    return (u64)(unsigned long long)(unsigned long)ptr;
}

__attribute__((noreturn))
static void fail_hard(const char* message);

__attribute__((noreturn))
static void fail_hard_hex64(const char* message, u64 value);

static void clear_bss(void) {
    volatile u8* p = __bss_start;
    while (p < __bss_end) {
        *p = 0;
        ++p;
    }
}

#if L64_SYS_CLK_FREQ <= 1000000ULL
#define spin_delay(iterations) ((void)(iterations))
#else
static void spin_delay(u32 iterations) {
    volatile u32 remaining = iterations;
    while (remaining != 0U) {
        --remaining;
    }
}
#endif

#if L64_HAVE_SDRAM_INIT
static void sdram_memory_test_or_fail(void) {
    volatile u64* const test_words = (volatile u64*)L64_RAM_BASE;
    u32 index = 0U;

    serial_puts("stage0: testing sdram");
    serial_put_labeled_hex64(" base=", L64_RAM_BASE);
    serial_put_labeled_hex32(" bytes=", STAGE0_SDRAM_TEST_WORDS * (u32)sizeof(u64));
    serial_putc('\n');

    while (index < STAGE0_SDRAM_TEST_WORDS) {
        u64 pattern = 0x13579BDF2468ACE0ULL ^ ((u64)index * 0x0102040810204080ULL);
        test_words[index] = pattern;
        ++index;
    }

    index = 0U;
    while (index < STAGE0_SDRAM_TEST_WORDS) {
        u64 expected = 0x13579BDF2468ACE0ULL ^ ((u64)index * 0x0102040810204080ULL);
        u64 observed = test_words[index];
        if (observed != expected) {
            serial_puts("stage0: error: sdram test mismatch");
            serial_put_labeled_hex32(" word=", index);
            serial_put_labeled_hex64(" expected=", expected);
            serial_put_labeled_hex64(" observed=", observed);
            serial_putc('\n');
            fail_hard("sdram read/write test failed");
        }
        ++index;
    }

    index = 0U;
    while (index < STAGE0_SDRAM_TEST_WORDS) {
        u64 pattern = ~((0xF0E1D2C3B4A59687ULL) ^ ((u64)index * 0x1111111111111111ULL));
        test_words[index] = pattern;
        ++index;
    }

    index = 0U;
    while (index < STAGE0_SDRAM_TEST_WORDS) {
        u64 expected = ~((0xF0E1D2C3B4A59687ULL) ^ ((u64)index * 0x1111111111111111ULL));
        u64 observed = test_words[index];
        if (observed != expected) {
            serial_puts("stage0: error: sdram test mismatch");
            serial_put_labeled_hex32(" word=", index);
            serial_put_labeled_hex64(" expected=", expected);
            serial_put_labeled_hex64(" observed=", observed);
            serial_putc('\n');
            fail_hard("sdram read/write test failed");
        }
        ++index;
    }

    serial_puts("stage0: sdram test passed\n");
}

static void sdram_initialize_or_fail(void) {
    serial_puts("stage0: initializing sdram (liblitedram)\n");
    if (sdram_init() != 1) {
        fail_hard("liblitedram sdram_init() returned failure");
    }
    serial_puts("stage0: sdram ready\n");
    sdram_memory_test_or_fail();
}
#else
static void sdram_initialize_or_fail(void) {
}
#endif

static u16 read_le16(const u8* data) {
    return (u16)((u16)data[0] | ((u16)data[1] << 8));
}

static u32 read_le32(const u8* data) {
    return (u32)data[0] |
        ((u32)data[1] << 8) |
        ((u32)data[2] << 16) |
        ((u32)data[3] << 24);
}

static u64 read_le64(const u8* data) {
    return (u64)read_le32(data) | ((u64)read_le32(data + 4) << 32);
}

static u32 align_up_u32(u32 value, u32 alignment) {
    return (value + alignment - 1U) & ~(alignment - 1U);
}

static u32 min_u32(u32 a, u32 b) {
    return a < b ? a : b;
}

static u64 align_up_u64(u64 value, u64 alignment) {
    return (value + alignment - 1ULL) & ~(alignment - 1ULL);
}

static u32 crc32_initialize(void) {
    return 0xFFFFFFFFU;
}

static u32 crc32_finalize(u32 crc) {
    return crc ^ 0xFFFFFFFFU;
}

static u32 crc32_update_bytes(u32 crc, const u8* data, u32 size) {
    while (size != 0U) {
        crc ^= *data;
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        ++data;
        --size;
    }
    return crc;
}

static u32 crc32_update_zeros(u32 crc, u32 size) {
    while (size != 0U) {
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        --size;
    }
    return crc;
}

static u32 crc32_update_physical(u32 crc, u64 source, u32 size) {
    const volatile u8* data = (const volatile u8*)source;
    while (size != 0U) {
        u8 value = *data;
        crc ^= value;
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        crc = crc32_nibble_table[crc & 0x0FU] ^ (crc >> 4U);
        ++data;
        --size;
    }
    return crc;
}

static void copy_to_physical(u64 destination, const u8* source, u32 size) {
    volatile u8* dst = (volatile u8*)destination;
    u32 index = 0U;
    while (index < size) {
        dst[index] = source[index];
        ++index;
    }
}

static void zero_to_physical(u64 destination, u64 size) {
    volatile u8* dst = (volatile u8*)destination;
    u64 index = 0ULL;
    while (index < size) {
        dst[index] = 0;
        ++index;
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
static void fail_hard_hex64(const char* message, u64 value) {
    serial_puts("stage0: error: ");
    serial_puts(message);
    serial_put_labeled_hex64(" value=", value);
    serial_putc('\n');
    for (;;) {
        __asm__ volatile ("STOP");
    }
}

static u32 pow2_round_up(u32 value) {
    if (value <= 1U) {
        return 1U;
    }
    --value;
    value |= value >> 1U;
    value |= value >> 2U;
    value |= value >> 4U;
    value |= value >> 8U;
    value |= value >> 16U;
    return value + 1U;
}

static u32 stage0_progress_step_for_size(u32 total) {
    u32 step = total >> 3U;

    if (step < STAGE0_LOAD_PROGRESS_MIN_STEP) {
        step = STAGE0_LOAD_PROGRESS_MIN_STEP;
    }
    if (step > STAGE0_LOAD_PROGRESS_MAX_STEP) {
        step = STAGE0_LOAD_PROGRESS_MAX_STEP;
    }
    return pow2_round_up(step);
}

static void stage0_progress_initialize(Stage0Progress* progress, const char* label, u32 total) {
    progress->label = label;
    progress->total = total;
    progress->completed = 0U;
    progress->report_step = stage0_progress_step_for_size(total);
    progress->next_report = progress->report_step;
    if (progress->next_report > total) {
        progress->next_report = total;
    }
}

static void stage0_progress_report(const Stage0Progress* progress) {
    serial_puts("stage0: ");
    serial_puts(progress->label);
    serial_puts(" progress");
    serial_put_labeled_hex32(" loaded=", progress->completed);
    serial_put_labeled_hex32(" total=", progress->total);
    serial_putc('\n');
}

static void stage0_progress_advance(Stage0Progress* progress, u32 amount) {
    if (progress == (Stage0Progress*)0 || progress->total == 0U) {
        return;
    }

    progress->completed += amount;
    if (progress->completed > progress->total) {
        progress->completed = progress->total;
    }
    if (progress->completed < progress->next_report && progress->completed != progress->total) {
        return;
    }

    stage0_progress_report(progress);
    while (progress->next_report <= progress->completed && progress->next_report < progress->total) {
        progress->next_report += progress->report_step;
    }
    if (progress->next_report > progress->total) {
        progress->next_report = progress->total;
    }
}

#if defined(L64_SDCARD_INTERFACE_NATIVE)
static void sdcard_ack_cmd_event(u32 event) {
    *sdcard_core_cmd_event = event;
}

static void sdcard_ack_data_event(u32 event) {
    *sdcard_core_data_event = event;
}

static void sdcard_set_clk_freq(u32 clk_freq) {
    u32 divider = clk_freq != 0U ? ((u32)L64_SYS_CLK_FREQ / clk_freq) : 256U;
    divider = pow2_round_up(divider);
    if (divider < 2U) {
        divider = 2U;
    }
    if (divider > 256U) {
        divider = 256U;
    }
    *sdcard_phy_clock_divider = divider;
}

static void sdcard_set_data_width(u32 width) {
    *sdcard_phy_settings = width;
    spin_delay(256U);
}

static u32 sdcard_read_response_word(u32 word_index) {
    return sdcard_core_cmd_response[word_index];
}

static void sdcard_record_last_command_result(u32 status, u32 event) {
    u32 word_index = 0U;

    sdcard_last_cmd_status = status;
    sdcard_last_cmd_event = event;
    while (word_index < 4U) {
        sdcard_last_cmd_response_words[word_index] = sdcard_core_cmd_response[word_index];
        ++word_index;
    }
}

static void sdcard_record_last_data_result(u32 status, u32 event) {
    sdcard_last_data_status = status;
    sdcard_last_data_event = event;
}

static void sdcard_log_last_command_state(const char* stage) {
    serial_puts("stage0: sdcard native ");
    serial_puts(stage);
    serial_put_labeled_hex32(" cmd=", sdcard_last_cmd);
    serial_put_labeled_hex32(" arg=", sdcard_last_cmd_argument);
    serial_put_labeled_hex32(" resp_type=", sdcard_last_cmd_response_type);
    serial_put_labeled_hex32(" data_type=", sdcard_last_cmd_data_type);
    serial_put_labeled_hex32(" status=", sdcard_last_cmd_status);
    serial_put_labeled_hex32(" event=", sdcard_last_cmd_event);
#if defined(L64_SDCARD_PHY_CARD_DETECT_ADDR)
    serial_put_labeled_hex32(" cd=", *sdcard_phy_card_detect);
#endif
    serial_putc('\n');
    serial_puts("stage0: sdcard native responses");
    serial_put_labeled_hex32(" r0=", sdcard_last_cmd_response_words[0]);
    serial_put_labeled_hex32(" r1=", sdcard_last_cmd_response_words[1]);
    serial_put_labeled_hex32(" r2=", sdcard_last_cmd_response_words[2]);
    serial_put_labeled_hex32(" r3=", sdcard_last_cmd_response_words[3]);
    serial_putc('\n');
#if defined(L64_SDCARD_DEBUG_SIGNALS_ADDR)
    serial_puts("stage0: sdcard native debug");
    serial_put_labeled_hex32(" signals=", *sdcard_debug_signals);
    serial_put_labeled_hex32(" cmd_i_edges=", *sdcard_debug_cmd_i_transitions);
    serial_put_labeled_hex32(" cmd_o_edges=", *sdcard_debug_cmd_o_transitions);
    serial_put_labeled_hex32(" cmd_oe_edges=", *sdcard_debug_cmd_oe_transitions);
    serial_put_labeled_hex32(" data0_i_edges=", *sdcard_debug_data0_i_transitions);
    serial_put_labeled_hex32(" clk_edges=", *sdcard_debug_clk_transitions);
    serial_put_labeled_hex32(" cmd_i_rel_edges=", *sdcard_debug_cmd_i_released_transitions);
    serial_putc('\n');
#endif
}

static void sdcard_log_last_data_state(const char* stage) {
    serial_puts("stage0: sdcard native ");
    serial_puts(stage);
    serial_put_labeled_hex32(" cmd=", sdcard_last_cmd);
    serial_put_labeled_hex32(" arg=", sdcard_last_cmd_argument);
    serial_put_labeled_hex32(" data_status=", sdcard_last_data_status);
    serial_put_labeled_hex32(" data_event=", sdcard_last_data_event);
    serial_put_labeled_hex32(" phy_settings=", *sdcard_phy_settings);
    serial_putc('\n');
#if defined(L64_SDCARD_DEBUG_SIGNALS_ADDR)
    serial_puts("stage0: sdcard native data debug");
    serial_put_labeled_hex32(" signals=", *sdcard_debug_signals);
    serial_put_labeled_hex32(" data0_i_edges=", *sdcard_debug_data0_i_transitions);
    serial_put_labeled_hex32(" data1_i_edges=", *sdcard_debug_data1_i_transitions);
    serial_put_labeled_hex32(" data2_i_edges=", *sdcard_debug_data2_i_transitions);
    serial_put_labeled_hex32(" data3_i_edges=", *sdcard_debug_data3_i_transitions);
    serial_put_labeled_hex32(" clk_edges=", *sdcard_debug_clk_transitions);
    serial_putc('\n');
#endif
}

static u32 sdcard_wait_cmd_done(void) {
    u32 timeout = 1000000U;
    while (timeout != 0U) {
        u32 event = *sdcard_core_cmd_event;
        if ((event & 0x1U) != 0U) {
            sdcard_ack_cmd_event(event);
            if ((event & 0x4U) != 0U) {
                sdcard_record_last_command_result(SD_TIMEOUT, event);
                return SD_TIMEOUT;
            }
            if ((event & 0x8U) != 0U) {
                sdcard_record_last_command_result(SD_CRCERROR, event);
                return SD_CRCERROR;
            }
            sdcard_record_last_command_result(SD_OK, event);
            return SD_OK;
        }
        spin_delay(32U);
        --timeout;
    }
    sdcard_record_last_command_result(SD_TIMEOUT, 0U);
    return SD_TIMEOUT;
}

static u32 sdcard_wait_data_done(void) {
    u32 timeout = 1000000U;
    while (timeout != 0U) {
        u32 event = *sdcard_core_data_event;
        if ((event & 0x1U) != 0U) {
            sdcard_ack_data_event(event);
            if ((event & 0x4U) != 0U) {
                sdcard_record_last_data_result(SD_TIMEOUT, event);
                return SD_TIMEOUT;
            }
            if ((event & 0x8U) != 0U) {
                sdcard_record_last_data_result(SD_CRCERROR, event);
                return SD_CRCERROR;
            }
            sdcard_record_last_data_result(SD_OK, event);
            return SD_OK;
        }
        spin_delay(32U);
        --timeout;
    }
    sdcard_record_last_data_result(SD_TIMEOUT, 0U);
    return SD_TIMEOUT;
}

static u32 sdcard_send_command(u32 argument, u32 cmd, u32 response_type, u32 data_type) {
    sdcard_last_cmd = cmd;
    sdcard_last_cmd_argument = argument;
    sdcard_last_cmd_response_type = response_type;
    sdcard_last_cmd_data_type = data_type;
    sdcard_ack_cmd_event(0xFU);
    sdcard_ack_data_event(0xFU);
    *sdcard_core_cmd_argument = argument;
    *sdcard_core_cmd_command = (data_type << 5U) | response_type | (cmd << 8U);
    *sdcard_core_cmd_send = 1U;
    return sdcard_wait_cmd_done();
}

#elif defined(L64_SDCARD_INTERFACE_SPI)
static void sdcard_set_clk_freq(u32 clk_freq) {
    u32 divider = clk_freq != 0U ? (u32)((L64_SYS_CLK_FREQ + clk_freq - 1U) / clk_freq) : 0xFFFFU;
    if (divider < 2U) {
        divider = 2U;
    }
    if (divider > 0xFFFFU) {
        divider = 0xFFFFU;
    }
    *sdcard_spi_clk_divider = divider;
}

static void sdcard_spi_log_transfer_step(const char* stage, u32 transfer_id, u32 bit_count, u32 value0, u32 value1) {
    serial_puts("stage0: spisdcard ");
    serial_puts(stage);
    serial_put_labeled_hex32(" id=", transfer_id);
    serial_put_labeled_hex32(" bits=", bit_count);
    serial_put_labeled_hex32(" a=", value0);
    serial_put_labeled_hex32(" b=", value1);
    serial_putc('\n');
}

static u32 sdcard_spi_transfer_bits_u32(u32 value, u32 bit_count) {
    u32 timeout = 100000U;
    u32 shift = 0U;
    u32 transfer_id = ++sdcard_spi_transfer_debug_counter;
    u32 next_progress_timeout = 100000U - SDCARD_SPI_DEBUG_TIMEOUT_PROGRESS;
    int debug_transfer = transfer_id <= SDCARD_SPI_DEBUG_TRANSFER_BUDGET;

    if (bit_count < L64_SDCARD_SPI_DATA_WIDTH) {
        shift = L64_SDCARD_SPI_DATA_WIDTH - bit_count;
    }

    if (debug_transfer) {
        sdcard_spi_log_transfer_step("pre-mosi", transfer_id, bit_count, value, shift);
    }
    *sdcard_spi_mosi = value << shift;
    if (debug_transfer) {
        sdcard_spi_log_transfer_step("post-mosi", transfer_id, bit_count, *sdcard_spi_mosi, *sdcard_spi_cs);
    }
    *sdcard_spi_control = SDCARD_SPI_CONTROL_START | (bit_count << SDCARD_SPI_CONTROL_LENGTH_SHIFT);
    if (debug_transfer) {
        sdcard_spi_log_transfer_step("post-ctrl", transfer_id, bit_count, *sdcard_spi_control, *sdcard_spi_status);
    }
    while (timeout != 0U) {
        u32 status = *sdcard_spi_status;
        if (debug_transfer && timeout == 100000U) {
            sdcard_spi_log_transfer_step("status0", transfer_id, bit_count, status, *sdcard_spi_miso);
        }
        if ((status & SDCARD_SPI_STATUS_DONE) != 0U) {
            u32 result = *sdcard_spi_miso;
            if (debug_transfer) {
                sdcard_spi_log_transfer_step("done", transfer_id, bit_count, result, status);
            }
            return result;
        }
        if (debug_transfer && timeout == next_progress_timeout) {
            sdcard_spi_log_transfer_step("wait", transfer_id, bit_count, status, *sdcard_spi_control);
            if (next_progress_timeout > SDCARD_SPI_DEBUG_TIMEOUT_PROGRESS) {
                next_progress_timeout -= SDCARD_SPI_DEBUG_TIMEOUT_PROGRESS;
            } else {
                next_progress_timeout = 0U;
            }
        }
        spin_delay(8U);
        --timeout;
    }

    if (debug_transfer) {
        sdcard_spi_log_transfer_step("timeout", transfer_id, bit_count, *sdcard_spi_status, *sdcard_spi_control);
    }
    fail_hard("spisdcard transfer timed out");
}

static u8 sdcard_spi_transfer_byte(u8 value) {
    return (u8)(sdcard_spi_transfer_bits_u32((u32)value, 8U) & 0xFFU);
}

static void sdcard_spi_wait_not_busy(void) {
    u32 timeout = 1000000U;

    while (timeout != 0U) {
        if (sdcard_spi_transfer_byte(0xFFU) == 0xFFU) {
            return;
        }
        spin_delay(32U);
        --timeout;
    }

    fail_hard("sdcard SPI busy wait timed out");
}

#if L64_SDCARD_SPI_DATA_WIDTH >= 32U
static void sdcard_spi_read_data_bytes(u8* destination, u32 size) {
    u32 index = 0U;

    while (index + 4U <= size) {
        u32 value = sdcard_spi_transfer_bits_u32(0xFFFFFFFFU, 32U);
        destination[index + 0U] = (u8)(value >> 24U);
        destination[index + 1U] = (u8)(value >> 16U);
        destination[index + 2U] = (u8)(value >> 8U);
        destination[index + 3U] = (u8)value;
        index += 4U;
    }
    while (index < size) {
        destination[index] = sdcard_spi_transfer_byte(0xFFU);
        ++index;
    }
}
#else
static void sdcard_spi_read_data_bytes(u8* destination, u32 size) {
    u32 index = 0U;

    while (index < size) {
        destination[index] = sdcard_spi_transfer_byte(0xFFU);
        ++index;
    }
}
#endif

static void sdcard_spi_deselect(void) {
    *sdcard_spi_cs = SDCARD_SPI_CS_DEASSERT;
    (void)sdcard_spi_transfer_byte(0xFFU);
}

static void sdcard_spi_select(void) {
    // serial_puts("stage0: spisdcard select pre\n");
    *sdcard_spi_cs = SDCARD_SPI_CS_ASSERT;
    // serial_puts("stage0: spisdcard select post\n");
}

static u8 sdcard_spi_compute_crc7(const u8* data, u32 size) {
    u8 crc = 0U;
    while (size != 0U) {
        u8 current = *data;
        u32 bit_index = 0U;
        while (bit_index < 8U) {
            crc <<= 1U;
            if (((current ^ crc) & 0x80U) != 0U) {
                crc ^= 0x09U;
            }
            current <<= 1U;
            ++bit_index;
        }
        ++data;
        --size;
    }
    return (u8)((crc << 1U) | 0x01U);
}

static u8 sdcard_spi_send_command_core(u8 cmd, u32 argument, u8* response_tail, u32 response_tail_size, int keep_selected, u32 skip_response_bytes) {
    u8 frame[5];
    u8 response = 0xFFU;
    u32 retry = 16U;

    // serial_puts("stage0: spisdcard cmd entry\n");

    frame[0] = (u8)(0x40U | cmd);
    frame[1] = (u8)(argument >> 24U);
    frame[2] = (u8)(argument >> 16U);
    frame[3] = (u8)(argument >> 8U);
    frame[4] = (u8)argument;

    sdcard_spi_select();
    (void)sdcard_spi_transfer_byte(0xFFU);
    (void)sdcard_spi_transfer_byte(frame[0]);
    (void)sdcard_spi_transfer_byte(frame[1]);
    (void)sdcard_spi_transfer_byte(frame[2]);
    (void)sdcard_spi_transfer_byte(frame[3]);
    (void)sdcard_spi_transfer_byte(frame[4]);
    (void)sdcard_spi_transfer_byte(sdcard_spi_compute_crc7(frame, 5U));

    while (skip_response_bytes != 0U) {
        (void)sdcard_spi_transfer_byte(0xFFU);
        --skip_response_bytes;
    }

    while (retry != 0U) {
        response = sdcard_spi_transfer_byte(0xFFU);
        if ((response & 0x80U) == 0U) {
            break;
        }
        --retry;
    }

    if (retry == 0U) {
        response = 0xFFU;
    }

    while (response_tail_size != 0U) {
        *response_tail = sdcard_spi_transfer_byte(0xFFU);
        ++response_tail;
        --response_tail_size;
    }

    if (!keep_selected) {
        sdcard_spi_deselect();
    }
    return response;
}

static u8 sdcard_spi_send_command(u8 cmd, u32 argument, u8* response_tail, u32 response_tail_size, int keep_selected) {
    return sdcard_spi_send_command_core(cmd, argument, response_tail, response_tail_size, keep_selected, 0U);
}

static u8 sdcard_spi_send_stop_command(void) {
    return sdcard_spi_send_command_core(12U, 0U, (u8*)0, 0U, 1, 1U);
}

static void sdcard_spi_wait_for_data_token_or_fail(u32 block) {
    u32 timeout = 1000000U;
    u8 token;
    u8 sample_bytes[8];
    u32 sample_count = 0U;
    u32 saw_ff = 0U;
    u32 saw_zero = 0U;
    u32 saw_other = 0U;

    do {
        token = sdcard_spi_transfer_byte(0xFFU);
        if (sample_count < 8U) {
            sample_bytes[sample_count] = token;
            ++sample_count;
        }
        if (token == 0xFFU) {
            ++saw_ff;
        } else if (token == 0x00U) {
            ++saw_zero;
        } else {
            ++saw_other;
        }
        if (token == SDCARD_SPI_DATA_TOKEN_START_BLOCK) {
            return;
        }
        spin_delay(32U);
        --timeout;
    } while (timeout != 0U);

    sdcard_spi_deselect();
    serial_puts("stage0: sdcard SPI read poll samples:");
    {
        u32 i = 0U;
        while (i < sample_count) {
            serial_puts(" ");
            serial_put_hex_u32((u32)sample_bytes[i]);
            ++i;
        }
        serial_puts("\n");
    }
    serial_puts("stage0: sdcard SPI poll counts ff=");
    serial_put_hex_u32(saw_ff);
    serial_puts(" zero=");
    serial_put_hex_u32(saw_zero);
    serial_puts(" other=");
    serial_put_hex_u32(saw_other);
    serial_puts("\n");
    fail_hard_hex64("sdcard SPI read timed out", block);
}

static void sdcard_spi_read_data_block_payload(u32 block, u8* destination) {
    sdcard_spi_wait_for_data_token_or_fail(block);
    sdcard_spi_read_data_bytes(destination, SD_BLOCK_SIZE);
    (void)sdcard_spi_transfer_byte(0xFFU);
    (void)sdcard_spi_transfer_byte(0xFFU);
}

static void sdcard_spi_read_blocks_contiguous(u32 start_block, u8* destination, u32 block_count) {
    u32 index = 0U;
    u32 argument = sdcard_spi_uses_block_addressing ? start_block : (start_block * SD_BLOCK_SIZE);

    if (block_count == 0U) {
        return;
    }
    if (block_count == 1U) {
        if (sdcard_spi_send_command(17U, argument, (u8*)0, 0U, 1) != 0U) {
            fail_hard_hex64("sdcard SPI read command failed", start_block);
        }
        sdcard_spi_read_data_block_payload(start_block, destination);
        sdcard_spi_deselect();
        return;
    }

    if (sdcard_spi_send_command(18U, argument, (u8*)0, 0U, 1) != 0U) {
        fail_hard_hex64("sdcard SPI multiblock read command failed", start_block);
    }

    while (index < block_count) {
        sdcard_spi_read_data_block_payload(start_block + index, destination + index * SD_BLOCK_SIZE);
        ++index;
    }

    if (sdcard_spi_send_stop_command() != 0U) {
        sdcard_spi_deselect();
        fail_hard_hex64("sdcard SPI CMD12 failed", start_block + block_count);
    }
    sdcard_spi_wait_not_busy();
    sdcard_spi_deselect();
}
#endif

static void sdcard_read_block(u32 block, u8* destination) {
#if defined(L64_SDCARD_INTERFACE_NATIVE)
    u64 dma_base = pointer_to_u64(destination);
    u32 timeout = 1000000U;

    if (!image_window_fits_ram(dma_base, SD_BLOCK_SIZE)) {
        dma_base = L64_RAM_BASE + L64_RAM_SIZE - STAGE0_DMA_SCRATCH_SIZE;
    }

    *sdcard_block2mem_dma_enable = 0U;
    *sdcard_block2mem_dma_base_hi = (u32)(dma_base >> 32);
    *sdcard_block2mem_dma_base_lo = (u32)dma_base;
    *sdcard_block2mem_dma_length = SD_BLOCK_SIZE;
    *sdcard_block2mem_dma_enable = 1U;

    *sdcard_core_block_length = SD_BLOCK_SIZE;
    *sdcard_core_block_count = 1U;
    if (sdcard_send_command(block, 17U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_READ) != SD_OK) {
        fail_hard_hex64("sdcard read command failed", block);
    }
    if (sdcard_wait_data_done() != SD_OK) {
        fail_hard_hex64("sdcard read data failed", block);
    }

    while (timeout != 0U) {
        if ((*sdcard_block2mem_dma_done & 0x1U) != 0U) {
            if (dma_base != pointer_to_u64(destination)) {
                volatile const u8* scratch = (volatile const u8*)(unsigned long)dma_base;
                u32 index = 0U;
                while (index < SD_BLOCK_SIZE) {
                    destination[index] = scratch[index];
                    ++index;
                }
            }
            return;
        }
        spin_delay(32U);
        --timeout;
    }

    fail_hard_hex64("sdcard DMA timed out", block);
#elif defined(L64_SDCARD_INTERFACE_SPI)
    sdcard_spi_read_blocks_contiguous(block, destination, 1U);
#endif
}

static void sdcard_read_blocks_contiguous(u32 start_block, u8* destination, u32 block_count) {
#if defined(L64_SDCARD_INTERFACE_NATIVE)
    u32 index = 0U;

    while (index < block_count) {
        sdcard_read_block(start_block + index, destination + index * SD_BLOCK_SIZE);
        ++index;
    }
#elif defined(L64_SDCARD_INTERFACE_SPI)
    sdcard_spi_read_blocks_contiguous(start_block, destination, block_count);
#endif
}

static void sdcard_initialize_or_fail(void) {
#if defined(L64_SDCARD_INTERFACE_NATIVE)
    u32 timeout = 1000U;
    u16 rca;
    u32 response_word3;
    u32 use_four_bit = 1U;

    serial_puts("stage0: initializing sdcard\n");
    sdcard_set_clk_freq(400000U);
    /* Power-on settle: match the SPI path's >=1ms margin before SD traffic. */
    spin_delay(200000U);

    timeout = 16U;
    while (timeout != 0U) {
        *sdcard_phy_initialize = 1U;
        /*
         * LiteSDCard's native init pulse emits 80 clocks.
         * At the low bring-up clock (~390 kHz on the current divider), that
         * takes about 205 us, so the previous ~10 us delay could start CMD0
         * while the init clocks were still being generated.
         */
        spin_delay(50000U);
        if (sdcard_send_command(0U, 0U, SDCARD_CTRL_RESPONSE_NONE, SDCARD_CTRL_DATA_TRANSFER_NONE) == SD_OK) {
            break;
        }
        spin_delay(20000U);
        --timeout;
    }
    if (timeout == 0U) {
        sdcard_log_last_command_state("cmd0-failed");
        fail_hard("sdcard CMD0 failed");
    }

    timeout = 16U;
    while (timeout != 0U) {
        if (sdcard_send_command(0x000001AAU, 8U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) == SD_OK) {
            break;
        }
        spin_delay(20000U);
        --timeout;
    }
    if (timeout == 0U) {
        sdcard_log_last_command_state("cmd8-failed");
        fail_hard("sdcard CMD8 failed");
    }

    sdcard_set_clk_freq(10000000U);
    spin_delay(1024U);

    timeout = 1000U;
    while (timeout != 0U) {
        if (sdcard_send_command(0U, 55U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
            fail_hard("sdcard CMD55 failed");
        }
        if (sdcard_send_command(0x70FF8000U, 41U, SDCARD_CTRL_RESPONSE_SHORT_BUSY, SDCARD_CTRL_DATA_TRANSFER_NONE) == SD_OK) {
            response_word3 = sdcard_read_response_word(3U);
            if ((response_word3 & 0x80000000U) != 0U) {
                break;
            }
        }
        --timeout;
    }
    if (timeout == 0U) {
        fail_hard("sdcard ACMD41 timed out");
    }

    if (sdcard_send_command(0U, 2U, SDCARD_CTRL_RESPONSE_LONG, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD2 failed");
    }
    if (sdcard_send_command(0U, 3U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD3 failed");
    }

    rca = (u16)((sdcard_read_response_word(3U) >> 16U) & 0xFFFFU);
    if (sdcard_send_command((u32)rca << 16U, 10U, SDCARD_CTRL_RESPONSE_LONG, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD10 failed");
    }
    if (sdcard_send_command((u32)rca << 16U, 9U, SDCARD_CTRL_RESPONSE_LONG, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD9 failed");
    }
    if (sdcard_send_command((u32)rca << 16U, 7U, SDCARD_CTRL_RESPONSE_SHORT_BUSY, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD7 failed");
    }

    if (sdcard_send_command((u32)rca << 16U, 55U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD55 for ACMD6 failed");
    }
    if (sdcard_send_command(2U, 6U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard ACMD6 failed");
    }

    *sdcard_core_block_length = 64U;
    *sdcard_core_block_count = 1U;
    if (sdcard_send_command(0x80FFFFF1U, 6U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_READ) != SD_OK) {
        fail_hard("sdcard CMD6 switch failed");
    }
    if (sdcard_wait_data_done() != SD_OK) {
        sdcard_log_last_data_state("cmd6-data-failed");
        serial_puts("stage0: sdcard native falling back to 1-bit mode\n");
        use_four_bit = 0U;
        sdcard_set_data_width(SDCARD_PHY_WIDTH_1BIT);
        if (sdcard_send_command((u32)rca << 16U, 55U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
            fail_hard("sdcard CMD55 for ACMD6 1-bit fallback failed");
        }
        if (sdcard_send_command(0U, 6U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
            fail_hard("sdcard ACMD6 1-bit fallback failed");
        }
        if (sdcard_send_command(0x80FFFFF1U, 6U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_READ) != SD_OK) {
            fail_hard("sdcard CMD6 switch 1-bit retry failed");
        }
        if (sdcard_wait_data_done() != SD_OK) {
            sdcard_log_last_data_state("cmd6-data-failed-1bit");
            fail_hard("sdcard CMD6 data failed");
        }
    }

    if (sdcard_send_command((u32)rca << 16U, 55U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD55 for ACMD51 failed");
    }
    *sdcard_core_block_length = 8U;
    *sdcard_core_block_count = 1U;
    if (sdcard_send_command(0U, 51U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_READ) != SD_OK) {
        fail_hard("sdcard ACMD51 failed");
    }
    if (sdcard_wait_data_done() != SD_OK) {
        sdcard_log_last_data_state("acmd51-data-failed");
        fail_hard("sdcard ACMD51 data failed");
    }

    if (use_four_bit == 0U) {
        serial_puts("stage0: sdcard native continuing in 1-bit mode\n");
    }

    if (sdcard_send_command(512U, 16U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD16 failed");
    }

#if defined(L64_SDCARD_INTERFACE_NATIVE)
    if (SDCARD_NATIVE_FORCE_1BIT_FILESYSTEM_IO != 0U) {
        serial_puts("stage0: sdcard native forcing 1-bit filesystem I/O\n");
        if (sdcard_send_command((u32)rca << 16U, 55U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
            fail_hard("sdcard CMD55 for ACMD6 filesystem 1-bit forced mode failed");
        }
        if (sdcard_send_command(0U, 6U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
            fail_hard("sdcard ACMD6 filesystem 1-bit forced mode failed");
        }
        sdcard_set_data_width(SDCARD_PHY_WIDTH_1BIT);
        use_four_bit = 0U;
    }
#endif

    serial_puts("stage0: sdcard ready\n");
#elif defined(L64_SDCARD_INTERFACE_SPI)
    u32 timeout = 1000U;
    u8 response_tail[4];

    serial_puts("stage0: initializing sdcard (spi)\n");
    *sdcard_spi_loopback = 0U;
    *sdcard_spi_cs = SDCARD_SPI_CS_DEASSERT;
    sdcard_set_clk_freq(SDCARD_SPI_INIT_CLK_HZ);

    /* Power-on settle: spec requires >=1ms of Vcc ramp before any SD activity. */
    spin_delay(200000U);

    /* Send >=74 dummy clocks with CS high and MOSI high. Use 160 clocks for margin. */
    timeout = 20U;
    while (timeout != 0U) {
        (void)sdcard_spi_transfer_byte(0xFFU);
        --timeout;
    }

    /* Retry CMD0 a few times: some cards need a couple of attempts after cold power-on. */
    timeout = 16U;
    while (timeout != 0U) {
        serial_puts("stage0: sdcard SPI CMD0\n");
        if (sdcard_spi_send_command(0U, 0U, (u8*)0, 0U, 0) == SDCARD_SPI_R1_IDLE) {
            break;
        }
        spin_delay(20000U);
        --timeout;
    }
    if (timeout == 0U) {
        fail_hard("sdcard SPI CMD0 failed");
    }

    serial_puts("stage0: sdcard SPI CMD8\n");
    if (sdcard_spi_send_command(8U, 0x000001AAU, response_tail, 4U, 0) != SDCARD_SPI_R1_IDLE) {
        fail_hard("sdcard SPI CMD8 failed");
    }
    if (response_tail[2] != 0x01U || response_tail[3] != 0xAAU) {
        fail_hard("sdcard SPI CMD8 response invalid");
    }

    timeout = 1000U;
    while (timeout != 0U) {
        serial_puts("stage0: sdcard SPI ACMD41\n");
        if (sdcard_spi_send_command(55U, 0U, (u8*)0, 0U, 0) > SDCARD_SPI_R1_IDLE) {
            fail_hard("sdcard SPI CMD55 failed");
        }
        if (sdcard_spi_send_command(41U, 0x40000000U, (u8*)0, 0U, 0) == 0U) {
            break;
        }
        spin_delay(1024U);
        --timeout;
    }
    if (timeout == 0U) {
        fail_hard("sdcard SPI ACMD41 timed out");
    }

    serial_puts("stage0: sdcard SPI CMD58\n");
    if (sdcard_spi_send_command(58U, 0U, response_tail, 4U, 0) != 0U) {
        fail_hard("sdcard SPI CMD58 failed");
    }
    sdcard_spi_uses_block_addressing = (response_tail[0] & 0x40U) != 0U;

    /*
     * Post-init clock: the SD physical spec allows up to 25 MHz, but in practice
     * the Arty SPI-mode SD path reaches the card over PMOD / breakout wiring
     * that is unterminated and has non-trivial stub capacitance. Many cards fail
     * to deliver a clean start-of-block token (0xFE) on CMD17 at 25 MHz in that
     * environment even though init at 400 kHz succeeds. Stage a conservative
     * 4 MHz for now; signal integrity, not card capability, is the bottleneck
     * here. If a specific board is known good this can be raised.
     */
    sdcard_set_clk_freq(SDCARD_SPI_POST_INIT_CLK_HZ);
    if (!sdcard_spi_uses_block_addressing) {
        serial_puts("stage0: sdcard SPI CMD16\n");
        if (sdcard_spi_send_command(16U, 512U, (u8*)0, 0U, 0) != 0U) {
            fail_hard("sdcard SPI CMD16 failed");
        }
    }

    serial_puts("stage0: sdcard ready (spi)\n");
#endif
}

static u32 cluster_to_lba(u32 cluster) {
    return fat32_volume.first_data_lba + (cluster - 2U);
}

static u32 fat32_next_cluster(u32 cluster) {
    u32 fat_offset = cluster * 4U;
    u32 fat_sector = fat32_volume.first_fat_lba + (fat_offset >> 9U);
    u32 sector_offset = fat_offset & (SD_BLOCK_SIZE - 1U);
    if (fat32_cached_fat_sector_lba != fat_sector) {
        sdcard_read_block(fat_sector, fat32_cached_fat_sector);
        fat32_cached_fat_sector_lba = fat_sector;
    }
    return read_le32(&fat32_cached_fat_sector[sector_offset]) & 0x0FFFFFFFU;
}

static u32 fat32_count_contiguous_sectors(u32 start_cluster, u32 max_sectors, u32* next_cluster_after_run) {
    u32 cluster = start_cluster;
    u32 run_sectors = 1U;
    u32 next_cluster;

    while (run_sectors < max_sectors) {
        next_cluster = fat32_next_cluster(cluster);
        if (next_cluster >= FAT32_EOC_MIN || next_cluster != cluster + 1U) {
            *next_cluster_after_run = next_cluster;
            return run_sectors;
        }
        cluster = next_cluster;
        ++run_sectors;
    }

    *next_cluster_after_run = fat32_next_cluster(cluster);
    return run_sectors;
}

static void load_fat32_volume_or_fail(void) {
    u32 partition_type;
    u32 partition_lba;
    u16 bytes_per_sector;
    u16 reserved_sectors;
    u32 fat_size;
    u32 sectors_per_cluster;
    u32 root_cluster;
    u8 fat_count;

#if defined(L64_SDCARD_INTERFACE_SPI)
    serial_puts("stage0: reading sdcard MBR (spi)\n");
#endif
    sdcard_read_block(0U, sector_buffer);
    if (sector_buffer[510] != 0x55U || sector_buffer[511] != 0xAAU) {
        serial_dump_bytes("stage0: mbr first16", sector_buffer, 16U);
        serial_dump_bytes("stage0: mbr part0", &sector_buffer[446], 16U);
        serial_dump_bytes("stage0: mbr tail16", &sector_buffer[496], 16U);
        fail_hard("sdcard MBR signature missing");
    }

    partition_type = sector_buffer[446 + 4];
    partition_lba = read_le32(&sector_buffer[446 + 8]);
    if (partition_lba == 0U) {
        fail_hard("sdcard boot partition missing");
    }
    if (partition_type != 0x0BU && partition_type != 0x0CU) {
        fail_hard_hex64("sdcard boot partition type unsupported", partition_type);
    }

    sdcard_read_block(partition_lba, sector_buffer);
    if (sector_buffer[510] != 0x55U || sector_buffer[511] != 0xAAU) {
        fail_hard("FAT32 boot sector signature missing");
    }

    bytes_per_sector = read_le16(&sector_buffer[11]);
    sectors_per_cluster = sector_buffer[13];
    reserved_sectors = read_le16(&sector_buffer[14]);
    fat_count = sector_buffer[16];
    fat_size = read_le32(&sector_buffer[36]);
    root_cluster = read_le32(&sector_buffer[44]);

    if (bytes_per_sector != SD_BLOCK_SIZE) {
        fail_hard_hex64("FAT32 bytes-per-sector unsupported", bytes_per_sector);
    }
    if (sectors_per_cluster == 0U || fat_count == 0U || fat_size == 0U || root_cluster < 2U) {
        fail_hard("FAT32 parameters invalid");
    }
    if (fat_count != 2U) {
        fail_hard_hex64("FAT32 FAT count unsupported", fat_count);
    }
    if (sectors_per_cluster != 1U) {
        fail_hard_hex64("FAT32 sectors-per-cluster unsupported", sectors_per_cluster);
    }

    fat32_volume.partition_lba = partition_lba;
    fat32_volume.sectors_per_cluster = sectors_per_cluster;
    fat32_volume.first_fat_lba = partition_lba + (u32)reserved_sectors;
    fat32_volume.fat_sector_count = fat_size;
    fat32_volume.first_data_lba = fat32_volume.first_fat_lba + fat_size + fat_size;
    fat32_volume.root_cluster = root_cluster;
    fat32_cached_fat_sector_lba = FAT32_INVALID_CACHE_LBA;

    serial_puts("stage0: FAT32 ready");
    serial_put_labeled_hex32(" partition_lba=", partition_lba);
    serial_put_labeled_hex32(" root_cluster=", root_cluster);
    serial_putc('\n');
}

static int directory_name_matches(const u8* entry, const char* short_name_11) {
    u32 index = 0U;
    while (index < 11U) {
        if (entry[index] != (u8)short_name_11[index]) {
            return 0;
        }
        ++index;
    }
    return 1;
}

static void read_file_range_to_buffer(const Stage0FileInfo* file, u32 file_offset, u8* destination, u32 size);

static void locate_root_file_or_fail(const char* short_name_11, Stage0FileInfo* out_file) {
    u32 cluster = fat32_volume.root_cluster;

    while (cluster < FAT32_EOC_MIN) {
        u32 sector_index = 0U;
        while (sector_index < fat32_volume.sectors_per_cluster) {
            u32 lba = cluster_to_lba(cluster) + sector_index;
            u32 entry_offset = 0U;
            sdcard_read_block(lba, sector_buffer);

            while (entry_offset < SD_BLOCK_SIZE) {
                const u8* entry = &sector_buffer[entry_offset];
                u8 first = entry[0];
                u8 attributes = entry[11];
                if (first == 0x00U) {
                    fail_hard("required FAT32 file not found");
                }
                if (first != 0xE5U && attributes != FAT32_ATTR_LONG_NAME && (attributes & (FAT32_ATTR_DIRECTORY | FAT32_ATTR_VOLUME)) == 0U) {
                    if (directory_name_matches(entry, short_name_11)) {
                        out_file->first_cluster = ((u32)read_le16(&entry[20]) << 16U) | read_le16(&entry[26]);
                        out_file->size = read_le32(&entry[28]);
                        if (out_file->first_cluster < 2U) {
                            fail_hard("FAT32 file has invalid first cluster");
                        }
                        return;
                    }
                }
                entry_offset += 32U;
            }
            ++sector_index;
        }
        cluster = fat32_next_cluster(cluster);
    }

    fail_hard("FAT32 root directory chain terminated unexpectedly");
}

static void load_boot_checksums_or_fail(const Stage0FileInfo* file, Stage0BootChecksums* out_checksums) {
    if (file->size < 32U) {
        fail_hard("BOOT.CRC is too small");
    }

    read_file_range_to_buffer(file, 0U, elf_header_scratch, 32U);
    out_checksums->magic = read_le32(&elf_header_scratch[0]);
    out_checksums->version = read_le32(&elf_header_scratch[4]);
    out_checksums->kernel_image_crc32 = read_le32(&elf_header_scratch[8]);
    out_checksums->kernel_image_size = read_le32(&elf_header_scratch[12]);
    out_checksums->dtb_crc32 = read_le32(&elf_header_scratch[16]);
    out_checksums->dtb_size = read_le32(&elf_header_scratch[20]);
    out_checksums->reserved0 = read_le32(&elf_header_scratch[24]);
    out_checksums->reserved1 = read_le32(&elf_header_scratch[28]);

    if (out_checksums->magic != STAGE0_BOOT_CHECKSUM_MAGIC) {
        fail_hard_hex64("BOOT.CRC magic mismatch", out_checksums->magic);
    }
    if (out_checksums->version != STAGE0_BOOT_CHECKSUM_VERSION) {
        fail_hard_hex64("BOOT.CRC version mismatch", out_checksums->version);
    }
}

static void read_file_range_to_buffer(const Stage0FileInfo* file, u32 file_offset, u8* destination, u32 size) {
    u32 cluster_skip = file_offset >> 9U;
    u32 cluster_offset = file_offset & (SD_BLOCK_SIZE - 1U);
    u32 cluster = file->first_cluster;

    while (cluster_skip != 0U) {
        cluster = fat32_next_cluster(cluster);
        if (cluster >= FAT32_EOC_MIN) {
            fail_hard("FAT32 file range exceeds cluster chain");
        }
        --cluster_skip;
    }

    while (size != 0U) {
        if (cluster_offset == 0U && size >= SD_BLOCK_SIZE) {
            u32 next_cluster = FAT32_EOC_MIN;
            u32 full_sector_count = size >> 9U;
            u32 run_sectors = fat32_count_contiguous_sectors(cluster, full_sector_count, &next_cluster);
            u32 run_bytes = run_sectors * SD_BLOCK_SIZE;

            sdcard_read_blocks_contiguous(cluster_to_lba(cluster), destination, run_sectors);
            destination += run_bytes;
            size -= run_bytes;
            if (size == 0U) {
                return;
            }
            cluster = next_cluster;
            if (cluster >= FAT32_EOC_MIN) {
                fail_hard("FAT32 file range terminated early");
            }
            continue;
        }

        u32 sector = cluster_to_lba(cluster);
        u32 sector_offset = cluster_offset;
        u32 chunk_size = SD_BLOCK_SIZE - sector_offset;
        u32 index = 0U;
        if (chunk_size > size) {
            chunk_size = size;
        }
        if (sector_offset == 0U && chunk_size == SD_BLOCK_SIZE) {
            sdcard_read_block(sector, destination);
        } else {
            sdcard_read_block(sector, sector_buffer);
            while (index < chunk_size) {
                destination[index] = sector_buffer[sector_offset + index];
                ++index;
            }
        }
        destination += chunk_size;
        size -= chunk_size;
        cluster_offset += chunk_size;
        if (cluster_offset >= SD_BLOCK_SIZE && size != 0U) {
            cluster_offset = 0U;
            cluster = fat32_next_cluster(cluster);
            if (cluster >= FAT32_EOC_MIN) {
                fail_hard("FAT32 file range terminated early");
            }
        }
    }
}

static void read_file_range_to_physical(const Stage0FileInfo* file, u32 file_offset, u64 destination, u32 size, Stage0Progress* progress, u32* crc32) {
    u32 cluster_skip = file_offset >> 9U;
    u32 cluster_offset = file_offset & (SD_BLOCK_SIZE - 1U);
    u32 cluster = file->first_cluster;

    while (cluster_skip != 0U) {
        cluster = fat32_next_cluster(cluster);
        if (cluster >= FAT32_EOC_MIN) {
            fail_hard("FAT32 physical read exceeds cluster chain");
        }
        --cluster_skip;
    }

    while (size != 0U) {
        if (cluster_offset == 0U && size >= SD_BLOCK_SIZE) {
            u32 next_cluster = FAT32_EOC_MIN;
            u32 full_sector_count = size >> 9U;
            u32 run_sectors = fat32_count_contiguous_sectors(cluster, full_sector_count, &next_cluster);
            u32 max_batch_sectors = STAGE0_TRANSFER_BUFFER_SIZE / SD_BLOCK_SIZE;

            while (run_sectors != 0U) {
                u32 batch_sectors = run_sectors;
                u32 batch_bytes;
                if (batch_sectors > max_batch_sectors) {
                    batch_sectors = max_batch_sectors;
                }
                batch_bytes = batch_sectors * SD_BLOCK_SIZE;

                sdcard_read_blocks_contiguous(cluster_to_lba(cluster), transfer_buffer, batch_sectors);
                if (crc32 != (u32*)0) {
                    *crc32 = crc32_update_bytes(*crc32, transfer_buffer, batch_bytes);
                }
                copy_to_physical(destination, transfer_buffer, batch_bytes);
                stage0_progress_advance(progress, batch_bytes);

                destination += batch_bytes;
                size -= batch_bytes;
                run_sectors -= batch_sectors;
                if (run_sectors != 0U) {
                    cluster += batch_sectors;
                    continue;
                }
                if (size == 0U) {
                    return;
                }
                cluster = next_cluster;
                if (cluster >= FAT32_EOC_MIN) {
                    fail_hard("FAT32 physical read terminated early");
                }
            }
            continue;
        }

        u32 sector = cluster_to_lba(cluster);
        u32 sector_offset = cluster_offset;
        u32 chunk_size = SD_BLOCK_SIZE - sector_offset;
        if (chunk_size > size) {
            chunk_size = size;
        }
        sdcard_read_block(sector, sector_buffer);
        if (crc32 != (u32*)0) {
            *crc32 = crc32_update_bytes(*crc32, &sector_buffer[sector_offset], chunk_size);
        }
        copy_to_physical(destination, &sector_buffer[sector_offset], chunk_size);
        stage0_progress_advance(progress, chunk_size);
        destination += (u64)chunk_size;
        size -= chunk_size;
        cluster_offset += chunk_size;
        if (cluster_offset >= SD_BLOCK_SIZE && size != 0U) {
            cluster_offset = 0U;
            cluster = fat32_next_cluster(cluster);
            if (cluster >= FAT32_EOC_MIN) {
                fail_hard("FAT32 physical read terminated early");
            }
        }
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

static void load_kernel_and_handoff(const Stage0FileInfo* kernel_file, const Stage0FileInfo* dtb_file, const Stage0BootChecksums* checksums) {
    u32 phoff;
    u32 kernel_copy_size = 0U;
    u32 kernel_load_crc = crc32_initialize();
    u32 kernel_readback_crc;
    u32 dtb_load_crc = crc32_initialize();
    u32 dtb_readback_crc;
    u16 phentsize;
    u16 phnum;
    u16 machine;
    u64 entry;
    u64 min_vaddr = 0ULL;
    u64 max_vaddr = 0ULL;
    u64 virtual_base;
    u64 image_span;
    u64 entry_physical;
    u64 load_physical_base;
    u64 kernel_end;
    u64 dtb_physical;
    u64 dtb_end;
    u64 boot_stack_top = L64_RAM_BASE + L64_RAM_SIZE - STAGE0_DMA_SCRATCH_SIZE - 8ULL;
    u32 current_kernel_offset = 0U;
    Stage0Progress kernel_progress;
    Stage0Progress dtb_progress;
    u16 ph_index = 0U;

    if (kernel_file->size < 64U) {
        fail_hard("VMLINUX is too small");
    }
    if (dtb_file->size == 0U) {
        fail_hard("BOOT.DTB is empty");
    }

    read_file_range_to_buffer(kernel_file, 0U, elf_header_scratch, min_u32(kernel_file->size, ELF_HEADER_SCRATCH_SIZE));
    if (elf_header_scratch[0] != 0x7FU || elf_header_scratch[1] != 'E' || elf_header_scratch[2] != 'L' || elf_header_scratch[3] != 'F') {
        fail_hard("VMLINUX ELF magic missing");
    }
    if (elf_header_scratch[4] != 2U || elf_header_scratch[5] != 1U) {
        fail_hard("VMLINUX is not ELF64 little-endian");
    }

    machine = read_le16(&elf_header_scratch[18]);
    entry = read_le64(&elf_header_scratch[24]);
    phoff = read_le32(&elf_header_scratch[32]);
    phentsize = read_le16(&elf_header_scratch[54]);
    phnum = read_le16(&elf_header_scratch[56]);
    if (machine != EM_LITTLE64) {
        fail_hard_hex64("VMLINUX machine mismatch", machine);
    }
    if ((u64)phoff + (u64)phentsize * (u64)phnum > ELF_HEADER_SCRATCH_SIZE) {
        fail_hard("VMLINUX program headers exceed stage0 scratch buffer");
    }

    while (ph_index < phnum) {
        const u8* ph = &elf_header_scratch[phoff + (u32)ph_index * (u32)phentsize];
        u32 p_type = read_le32(&ph[0]);
        u64 p_offset = read_le64(&ph[8]);
        u64 p_vaddr = read_le64(&ph[16]);
        u64 p_filesz = read_le64(&ph[32]);
        u64 p_memsz = read_le64(&ph[40]);
        if (p_type == PT_LOAD) {
            if (p_offset + p_filesz > kernel_file->size) {
                fail_hard("VMLINUX PT_LOAD exceeds file size");
            }
            kernel_copy_size += (u32)p_filesz;
            if (min_vaddr == 0ULL || p_vaddr < min_vaddr) {
                min_vaddr = p_vaddr;
            }
            if (p_vaddr + p_memsz > max_vaddr) {
                max_vaddr = p_vaddr + p_memsz;
            }
        }
        ++ph_index;
    }

    if (min_vaddr == 0ULL || max_vaddr <= min_vaddr) {
        fail_hard("VMLINUX has no PT_LOAD segments");
    }

    virtual_base = min_vaddr & ~(PAGE_SIZE - 1ULL);
    image_span = align_up_u64(max_vaddr - virtual_base, PAGE_SIZE);
    load_physical_base = L64_KERNEL_PHYSICAL_BASE;
    serial_puts("stage0: elf image window");
    serial_put_labeled_hex64(" vbase=", virtual_base);
    serial_put_labeled_hex64(" entry=", entry);
    serial_put_labeled_hex64(" span=", image_span);
    serial_putc('\n');
    if (image_window_fits_ram(virtual_base, image_span) &&
        virtual_base <= entry && entry < virtual_base + image_span) {
        load_physical_base = virtual_base;
        entry_physical = entry;
    } else if (virtual_base <= entry && entry < virtual_base + image_span) {
        entry_physical = L64_KERNEL_PHYSICAL_BASE + (entry - virtual_base);
    } else if (L64_KERNEL_PHYSICAL_BASE <= entry && entry < L64_KERNEL_PHYSICAL_BASE + image_span) {
        entry_physical = entry;
    } else {
        fail_hard("VMLINUX entry lies outside the loadable image window");
    }

    kernel_end = load_physical_base + image_span;
    dtb_physical = load_physical_base + align_up_u64(image_span + EARLY_PT_SCRATCH_PAGES * PAGE_SIZE, PAGE_SIZE);
    dtb_end = dtb_physical + dtb_file->size;
    if (!image_window_fits_ram(load_physical_base, image_span) || dtb_end > L64_RAM_BASE + L64_RAM_SIZE) {
        fail_hard("kernel image or DTB does not fit in RAM");
    }
    if (boot_stack_top <= dtb_end) {
        fail_hard("kernel boot stack overlaps DTB");
    }
    if (checksums->kernel_image_size != image_span) {
        fail_hard_hex64("BOOT.CRC kernel image size mismatch", checksums->kernel_image_size);
    }
    if (checksums->dtb_size != dtb_file->size) {
        fail_hard_hex64("BOOT.CRC DTB size mismatch", checksums->dtb_size);
    }

    serial_puts("stage0: loading VMLINUX");
    serial_put_labeled_hex64(" phys=", load_physical_base);
    serial_put_labeled_hex64(" entry=", entry_physical);
    serial_put_labeled_hex64(" span=", image_span);
    serial_put_labeled_hex32(" copy_bytes=", kernel_copy_size);
    serial_putc('\n');

    stage0_progress_initialize(&kernel_progress, "VMLINUX", kernel_copy_size);
    zero_to_physical(load_physical_base, image_span);

    ph_index = 0U;
    while (ph_index < phnum) {
        const u8* ph = &elf_header_scratch[phoff + (u32)ph_index * (u32)phentsize];
        u32 p_type = read_le32(&ph[0]);
        u64 p_offset = read_le64(&ph[8]);
        u64 p_vaddr = read_le64(&ph[16]);
        u64 p_filesz = read_le64(&ph[32]);
        u64 p_memsz = read_le64(&ph[40]);
        if (p_type == PT_LOAD) {
            u64 destination = load_physical_base + (p_vaddr - virtual_base);
            u32 segment_offset = (u32)(destination - load_physical_base);
            if (segment_offset > current_kernel_offset) {
                kernel_load_crc = crc32_update_zeros(kernel_load_crc, segment_offset - current_kernel_offset);
                current_kernel_offset = segment_offset;
            }
            read_file_range_to_physical(kernel_file, (u32)p_offset, destination, (u32)p_filesz, &kernel_progress, &kernel_load_crc);
            current_kernel_offset += (u32)p_filesz;
            if (p_memsz > p_filesz) {
                kernel_load_crc = crc32_update_zeros(kernel_load_crc, (u32)(p_memsz - p_filesz));
                current_kernel_offset += (u32)(p_memsz - p_filesz);
            }
        }
        ++ph_index;
    }
    if (current_kernel_offset < image_span) {
        kernel_load_crc = crc32_update_zeros(kernel_load_crc, (u32)(image_span - current_kernel_offset));
    }
    kernel_load_crc = crc32_finalize(kernel_load_crc);
    if (kernel_load_crc != checksums->kernel_image_crc32) {
        serial_puts("stage0: kernel load crc mismatch");
        serial_put_labeled_hex32(" expected=", checksums->kernel_image_crc32);
        serial_put_labeled_hex32(" observed=", kernel_load_crc);
        serial_putc('\n');
        fail_hard("kernel load verification failed");
    }

    serial_puts("stage0: loading BOOT.DTB");
    serial_put_labeled_hex64(" phys=", dtb_physical);
    serial_put_labeled_hex32(" size=", dtb_file->size);
    serial_putc('\n');

    stage0_progress_initialize(&dtb_progress, "BOOT.DTB", dtb_file->size);
    read_file_range_to_physical(dtb_file, 0U, dtb_physical, dtb_file->size, &dtb_progress, &dtb_load_crc);
    dtb_load_crc = crc32_finalize(dtb_load_crc);
    if (dtb_load_crc != checksums->dtb_crc32) {
        serial_puts("stage0: dtb load crc mismatch");
        serial_put_labeled_hex32(" expected=", checksums->dtb_crc32);
        serial_put_labeled_hex32(" observed=", dtb_load_crc);
        serial_putc('\n');
        fail_hard("dtb load verification failed");
    }

    serial_puts("stage0: verifying kernel image in ram");
    serial_put_labeled_hex32(" bytes=", (u32)image_span);
    serial_putc('\n');
    kernel_readback_crc = crc32_finalize(crc32_update_physical(crc32_initialize(), load_physical_base, (u32)image_span));
    if (kernel_readback_crc != checksums->kernel_image_crc32) {
        serial_puts("stage0: kernel ram crc mismatch");
        serial_put_labeled_hex32(" expected=", checksums->kernel_image_crc32);
        serial_put_labeled_hex32(" observed=", kernel_readback_crc);
        serial_putc('\n');
        fail_hard("kernel ram verification failed");
    }

    serial_puts("stage0: verifying dtb in ram");
    serial_put_labeled_hex32(" bytes=", dtb_file->size);
    serial_putc('\n');
    dtb_readback_crc = crc32_finalize(crc32_update_physical(crc32_initialize(), dtb_physical, dtb_file->size));
    if (dtb_readback_crc != checksums->dtb_crc32) {
        serial_puts("stage0: dtb ram crc mismatch");
        serial_put_labeled_hex32(" expected=", checksums->dtb_crc32);
        serial_put_labeled_hex32(" observed=", dtb_readback_crc);
        serial_putc('\n');
        fail_hard("dtb ram verification failed");
    }

#if defined(L64_SDCARD_INTERFACE_NATIVE)
    /*
     * Ensure the PHY is in 4-bit mode at handoff regardless of whether the
     * stage-0 filesystem path used 1-bit or 4-bit.  The SD card bus width is
     * handled independently: the Linux litex_mmc driver always sends ACMD6
     * with MMC_BUS_WIDTH_4 before its first data transfer, so any transient
     * PHY/card mismatch here is resolved before the kernel touches the bus.
     */
    sdcard_set_data_width(SDCARD_PHY_WIDTH_4BIT);
    spin_delay(256U);
#endif

    serial_puts("stage0: handing off to kernel");
    serial_put_labeled_hex64(" entry=", entry_physical);
    serial_put_labeled_hex64(" dtb=", dtb_physical);
    serial_put_labeled_hex64(" stack_top=", boot_stack_top);
    serial_putc('\n');
    handoff_to_kernel(dtb_physical, boot_stack_top, entry_physical);
}

__attribute__((used, noinline))
static void litex_soc_boot_entry(void) {
    Stage0FileInfo kernel_file;
    Stage0FileInfo dtb_file;
    Stage0FileInfo checksums_file;
    Stage0BootChecksums checksums;

    liteuart_initialize();
    serial_puts("stage0: entered from internal bootrom\n");
    clear_bss();
    serial_puts("stage0: cleared .bss\n");
    sdram_initialize_or_fail();
    sdcard_initialize_or_fail();
    load_fat32_volume_or_fail();

    locate_root_file_or_fail("VMLINUX    ", &kernel_file);
    locate_root_file_or_fail("BOOT    DTB", &dtb_file);
    locate_root_file_or_fail("BOOT    CRC", &checksums_file);
    load_boot_checksums_or_fail(&checksums_file, &checksums);
    serial_puts("stage0: located boot files");
    serial_put_labeled_hex32(" kernel_size=", kernel_file.size);
    serial_put_labeled_hex32(" dtb_size=", dtb_file.size);
    serial_putc('\n');

    load_kernel_and_handoff(&kernel_file, &dtb_file, &checksums);
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