#include "litex_sd_boot_regs.h"

#if L64_HAVE_SDRAM_INIT
#include <generated/sdram_phy.h>
#endif

#define STAGE0_STACK_TOP 0x10004000ULL
#define PAGE_SIZE 4096ULL
#define EARLY_PT_SCRATCH_PAGES 30ULL
#define ELF_HEADER_SCRATCH_SIZE 4096ULL
#define SD_BLOCK_SIZE 512U
#define FAT32_EOC_MIN 0x0FFFFFF8UL
#define FAT32_ATTR_LONG_NAME 0x0FUL
#define FAT32_ATTR_DIRECTORY 0x10U
#define FAT32_ATTR_VOLUME 0x08U
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

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef long long s64;

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

static volatile u8* const liteuart_rxtx = (volatile u8*)L64_UART_RXTX_ADDR;
static volatile u32* const liteuart_txfull = (volatile u32*)L64_UART_TXFULL_ADDR;
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
static Stage0Fat32Volume fat32_volume;
static u8 sector_buffer[SD_BLOCK_SIZE];
static u8 elf_header_scratch[ELF_HEADER_SCRATCH_SIZE];

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

static void serial_putc(char c) {
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

static void serial_put_labeled_hex64(const char* label, u64 value) {
    serial_puts(label);
    serial_put_hex_u64(value);
}

static void serial_put_labeled_hex32(const char* label, u32 value) {
    serial_puts(label);
    serial_put_hex_u32(value);
}

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
void cdelay(int iterations) {
    if (iterations <= 0) {
        return;
    }
    spin_delay((u32)iterations);
}

static void sdram_software_control_on(void) {
    sdram_dfii_control_write(DFII_CONTROL_CKE | DFII_CONTROL_ODT | DFII_CONTROL_RESET_N);
}

static void sdram_software_control_off(void) {
    sdram_dfii_control_write(DFII_CONTROL_SEL);
}

static void sdram_initialize_or_fail(void) {
    serial_puts("stage0: initializing sdram\n");
    sdram_software_control_on();
    init_sequence();
    sdram_software_control_off();
    serial_puts("stage0: sdram ready\n");
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

static u32 sdcard_read_response_word(u32 word_index) {
    return sdcard_core_cmd_response[word_index];
}

static u32 sdcard_wait_cmd_done(void) {
    u32 timeout = 1000000U;
    while (timeout != 0U) {
        u32 event = *sdcard_core_cmd_event;
        if ((event & 0x1U) != 0U) {
            if ((event & 0x4U) != 0U) {
                return SD_TIMEOUT;
            }
            if ((event & 0x8U) != 0U) {
                return SD_CRCERROR;
            }
            return SD_OK;
        }
        spin_delay(32U);
        --timeout;
    }
    return SD_TIMEOUT;
}

static u32 sdcard_wait_data_done(void) {
    u32 timeout = 1000000U;
    while (timeout != 0U) {
        u32 event = *sdcard_core_data_event;
        if ((event & 0x1U) != 0U) {
            if ((event & 0x4U) != 0U) {
                return SD_TIMEOUT;
            }
            if ((event & 0x8U) != 0U) {
                return SD_CRCERROR;
            }
            return SD_OK;
        }
        spin_delay(32U);
        --timeout;
    }
    return SD_TIMEOUT;
}

static u32 sdcard_send_command(u32 argument, u32 cmd, u32 response_type, u32 data_type) {
    *sdcard_core_cmd_argument = argument;
    *sdcard_core_cmd_command = (data_type << 5U) | (1U << 2U) | response_type | (cmd << 8U);
    *sdcard_core_cmd_send = 1U;
    return sdcard_wait_cmd_done();
}

static void sdcard_read_block(u32 block, u8* destination) {
    u32 timeout = 1000000U;

    *sdcard_block2mem_dma_enable = 0U;
    *sdcard_block2mem_dma_base_hi = (u32)((u64)(unsigned long long)(unsigned long)destination >> 32);
    *sdcard_block2mem_dma_base_lo = (u32)(u64)(unsigned long long)(unsigned long)destination;
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
            return;
        }
        spin_delay(32U);
        --timeout;
    }

    fail_hard_hex64("sdcard DMA timed out", block);
}

static void sdcard_initialize_or_fail(void) {
    u32 timeout = 1000U;
    u16 rca;
    u32 response_word3;

    serial_puts("stage0: initializing sdcard\n");
    sdcard_set_clk_freq(400000U);
    spin_delay(1024U);

    while (timeout != 0U) {
        *sdcard_phy_initialize = 1U;
        spin_delay(1024U);
        if (sdcard_send_command(0U, 0U, SDCARD_CTRL_RESPONSE_NONE, SDCARD_CTRL_DATA_TRANSFER_NONE) == SD_OK) {
            break;
        }
        --timeout;
    }
    if (timeout == 0U) {
        fail_hard("sdcard CMD0 failed");
    }

    if (sdcard_send_command(0x000001AAU, 8U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD8 failed");
    }

    sdcard_set_clk_freq(25000000U);
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
        fail_hard("sdcard CMD6 data failed");
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
        fail_hard("sdcard ACMD51 data failed");
    }

    if (sdcard_send_command(512U, 16U, SDCARD_CTRL_RESPONSE_SHORT, SDCARD_CTRL_DATA_TRANSFER_NONE) != SD_OK) {
        fail_hard("sdcard CMD16 failed");
    }

    serial_puts("stage0: sdcard ready\n");
}

static u32 cluster_to_lba(u32 cluster) {
    return fat32_volume.first_data_lba + (cluster - 2U);
}

static u32 fat32_next_cluster(u32 cluster) {
    u32 fat_offset = cluster * 4U;
    u32 fat_sector = fat32_volume.first_fat_lba + (fat_offset >> 9U);
    u32 sector_offset = fat_offset & (SD_BLOCK_SIZE - 1U);
    sdcard_read_block(fat_sector, sector_buffer);
    return read_le32(&sector_buffer[sector_offset]) & 0x0FFFFFFFU;
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

    sdcard_read_block(0U, sector_buffer);
    if (sector_buffer[510] != 0x55U || sector_buffer[511] != 0xAAU) {
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
        u32 sector = cluster_to_lba(cluster);
        u32 sector_offset = cluster_offset;
        u32 chunk_size = SD_BLOCK_SIZE - sector_offset;
        u32 index = 0U;
        if (chunk_size > size) {
            chunk_size = size;
        }
        sdcard_read_block(sector, sector_buffer);
        while (index < chunk_size) {
            destination[index] = sector_buffer[sector_offset + index];
            ++index;
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

static void read_file_range_to_physical(const Stage0FileInfo* file, u32 file_offset, u64 destination, u32 size) {
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
        u32 sector = cluster_to_lba(cluster);
        u32 sector_offset = cluster_offset;
        u32 chunk_size = SD_BLOCK_SIZE - sector_offset;
        if (chunk_size > size) {
            chunk_size = size;
        }
        sdcard_read_block(sector, sector_buffer);
        copy_to_physical(destination, &sector_buffer[sector_offset], chunk_size);
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

static void load_kernel_and_handoff(const Stage0FileInfo* kernel_file, const Stage0FileInfo* dtb_file) {
    u32 phoff;
    u16 phentsize;
    u16 phnum;
    u16 machine;
    u64 entry;
    u64 min_vaddr = 0ULL;
    u64 max_vaddr = 0ULL;
    u64 virtual_base;
    u64 image_span;
    u64 entry_physical;
    u64 kernel_end;
    u64 dtb_physical;
    u64 dtb_end;
    u64 boot_stack_top = L64_RAM_BASE + L64_RAM_SIZE - 8ULL;
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
    if (virtual_base <= entry && entry < virtual_base + image_span) {
        entry_physical = L64_KERNEL_PHYSICAL_BASE + (entry - virtual_base);
    } else if (L64_KERNEL_PHYSICAL_BASE <= entry && entry < L64_KERNEL_PHYSICAL_BASE + image_span) {
        entry_physical = entry;
    } else {
        fail_hard("VMLINUX entry lies outside the loadable image window");
    }

    kernel_end = L64_KERNEL_PHYSICAL_BASE + image_span;
    dtb_physical = L64_KERNEL_PHYSICAL_BASE + align_up_u64(image_span + EARLY_PT_SCRATCH_PAGES * PAGE_SIZE, PAGE_SIZE);
    dtb_end = dtb_physical + dtb_file->size;
    if (L64_KERNEL_PHYSICAL_BASE < L64_RAM_BASE || kernel_end > L64_RAM_BASE + L64_RAM_SIZE || dtb_end > L64_RAM_BASE + L64_RAM_SIZE) {
        fail_hard("kernel image or DTB does not fit in RAM");
    }
    if (boot_stack_top <= dtb_end) {
        fail_hard("kernel boot stack overlaps DTB");
    }

    serial_puts("stage0: loading VMLINUX");
    serial_put_labeled_hex64(" phys=", L64_KERNEL_PHYSICAL_BASE);
    serial_put_labeled_hex64(" entry=", entry_physical);
    serial_put_labeled_hex64(" span=", image_span);
    serial_putc('\n');

    ph_index = 0U;
    while (ph_index < phnum) {
        const u8* ph = &elf_header_scratch[phoff + (u32)ph_index * (u32)phentsize];
        u32 p_type = read_le32(&ph[0]);
        u64 p_offset = read_le64(&ph[8]);
        u64 p_vaddr = read_le64(&ph[16]);
        u64 p_filesz = read_le64(&ph[32]);
        u64 p_memsz = read_le64(&ph[40]);
        if (p_type == PT_LOAD) {
            u64 destination = L64_KERNEL_PHYSICAL_BASE + (p_vaddr - virtual_base);
            read_file_range_to_physical(kernel_file, (u32)p_offset, destination, (u32)p_filesz);
            if (p_memsz > p_filesz) {
                zero_to_physical(destination + p_filesz, p_memsz - p_filesz);
            }
        }
        ++ph_index;
    }

    serial_puts("stage0: loading BOOT.DTB");
    serial_put_labeled_hex64(" phys=", dtb_physical);
    serial_put_labeled_hex32(" size=", dtb_file->size);
    serial_putc('\n');
    read_file_range_to_physical(dtb_file, 0U, dtb_physical, dtb_file->size);

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

    serial_puts("stage0: entered from internal bootrom\n");
    clear_bss();
    serial_puts("stage0: cleared .bss\n");
    sdram_initialize_or_fail();
    sdcard_initialize_or_fail();
    load_fat32_volume_or_fail();

    locate_root_file_or_fail("VMLINUX    ", &kernel_file);
    locate_root_file_or_fail("BOOT    DTB", &dtb_file);
    serial_puts("stage0: located boot files");
    serial_put_labeled_hex32(" kernel_size=", kernel_file.size);
    serial_put_labeled_hex32(" dtb_size=", dtb_file.size);
    serial_putc('\n');

    load_kernel_and_handoff(&kernel_file, &dtb_file);
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