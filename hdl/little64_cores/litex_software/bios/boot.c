#ifndef UPSTREAM_BIOS_BOOT_C
#error "UPSTREAM_BIOS_BOOT_C must point at the LiteX BIOS boot.c source"
#endif

#define netboot_from_json little64_legacy_netboot_from_json
#define netboot little64_legacy_netboot
#define sdcardboot_from_json little64_legacy_sdcardboot_from_json
#define sdcardboot little64_legacy_sdcardboot
#define sataboot_from_json little64_legacy_sataboot_from_json
#define sataboot little64_legacy_sataboot

#include UPSTREAM_BIOS_BOOT_C

#undef netboot_from_json
#undef netboot
#undef sdcardboot_from_json
#undef sdcardboot
#undef sataboot_from_json
#undef sataboot

#include <libfatfs/diskio.h>

static int little64_json_token_to_string(char *dst, size_t dst_size, const char *json, jsmntok_t *token)
{
	int len;

	if ((token->start < 0) || (token->end < token->start))
		return 0;
	len = token->end - token->start;
	if (len >= (int)dst_size)
		return 0;
	memcpy(dst, json + token->start, len);
	dst[len] = 0;
	return 1;
}

static void little64_log_fatfs_failure(const char *context, FRESULT fr)
{
	printf("%s failed (%d).\n", context, (int)fr);
}

#if defined(CSR_SPISDCARD_BASE) || defined(CSR_SDCARD_CORE_BASE) || defined(CSR_SDCARD_BASE)
static FATFS little64_sd_fatfs __attribute__((aligned(64)));
static FIL little64_sd_file __attribute__((aligned(64)));
static char little64_sd_json_buffer[1024] __attribute__((aligned(64)));
static char little64_sd_json_name[32] __attribute__((aligned(64)));
static char little64_sd_json_value[32] __attribute__((aligned(64)));
static jsmntok_t little64_sd_json_tokens[32] __attribute__((aligned(64)));

static unsigned int little64_ld_word_le(const uint8_t *buffer, unsigned int offset)
{
	return (unsigned int)buffer[offset] | ((unsigned int)buffer[offset + 1] << 8);
}

static unsigned int little64_ld_dword_le(const uint8_t *buffer, unsigned int offset)
{
	return (unsigned int)buffer[offset]
		| ((unsigned int)buffer[offset + 1] << 8)
		| ((unsigned int)buffer[offset + 2] << 16)
		| ((unsigned int)buffer[offset + 3] << 24);
}

static void little64_debug_sdcard_volume(void)
{
	uint8_t sector[512];
	unsigned int part_lba;

	sdcard_read(0, 1, sector);
	printf(
		"raw sector0: sig=%02x%02x p1_type=%02x p1_lba=%lu p1_sectors=%lu\n",
		sector[511], sector[510],
		sector[450],
		(unsigned long)little64_ld_dword_le(sector, 454),
		(unsigned long)little64_ld_dword_le(sector, 458)
	);

	part_lba = little64_ld_dword_le(sector, 454);
	if (part_lba == 0) {
		printf("raw sector0: partition 1 start LBA is zero.\n");
		return;
	}

	sdcard_read(part_lba, 1, sector);
	printf(
		"raw sector%lu: jump=%02x%02x%02x sig=%02x%02x bps=%u spc=%u nfats=%u fatsz32=%lu root=%lu fstype=%.8s\n",
		(unsigned long)part_lba,
		sector[0], sector[1], sector[2],
		sector[511], sector[510],
		little64_ld_word_le(sector, 11),
		sector[13],
		sector[16],
		(unsigned long)little64_ld_dword_le(sector, 36),
		(unsigned long)little64_ld_dword_le(sector, 44),
		sector + 82
	);
	printf(
		"raw sector%lu: hidden=%lu totsec=%lu fsinfo=%u backup=%u\n",
		(unsigned long)part_lba,
		(unsigned long)little64_ld_dword_le(sector, 28),
		(unsigned long)little64_ld_dword_le(sector, 32),
		little64_ld_word_le(sector, 48),
		little64_ld_word_le(sector, 50)
	);
}

#ifdef CSR_SDCARD_CORE_BASE
static DSTATUS little64_debug_sdcard_status = STA_NOINIT;
static uint8_t little64_sd_dma_bounce[512] __attribute__((aligned(64)));

static DSTATUS little64_debug_sd_disk_status(BYTE drv)
{
	if (drv)
		return STA_NOINIT;
	return little64_debug_sdcard_status;
}

static DSTATUS little64_debug_sd_disk_initialize(BYTE drv)
{
	if (drv)
		return STA_NOINIT;
	if (little64_debug_sdcard_status)
		little64_debug_sdcard_status = sdcard_init() ? 0 : STA_NOINIT;
	if (little64_debug_sdcard_status != 0)
		printf("fatfs disk_initialize failed: drv=%u status=%u\n", (unsigned int)drv, (unsigned int)little64_debug_sdcard_status);
	return little64_debug_sdcard_status;
}

static DRESULT little64_debug_sd_disk_read(BYTE drv, BYTE *buf, LBA_t block, UINT count)
{
	UINT index;

	if (drv)
		return RES_PARERR;
	for (index = 0; index < count; index++) {
		sdcard_read(block + index, 1, little64_sd_dma_bounce);
		memcpy(buf + (index * 512), little64_sd_dma_bounce, 512);
	}
	return RES_OK;
}

static DISKOPS little64_debug_sd_disk_ops = {
	.disk_initialize = little64_debug_sd_disk_initialize,
	.disk_status = little64_debug_sd_disk_status,
	.disk_read = little64_debug_sd_disk_read,
};
#endif
#endif

#ifdef CSR_ETHMAC_BASE
static void netboot_from_json(const char * filename, unsigned int ip, unsigned short tftp_port)
{
	int size;
	int i;
	int count;

	char json_buffer[1024];
	char json_name[32];
	char json_value[32];

	unsigned long boot_r1 = 0;
	unsigned long boot_r2 = 0;
	unsigned long boot_r3 = 0;
	unsigned long boot_addr = 0;

	uint8_t image_found = 0;
	uint8_t boot_addr_found = 0;

	size = tftp_get(ip, tftp_port, filename, json_buffer);
	if (size <= 0)
		return;
	if (size >= (int)sizeof(json_buffer))
		size = sizeof(json_buffer) - 1;
	json_buffer[size] = 0;

	jsmntok_t t[32];
	jsmn_parser p;
	jsmn_init(&p);
	count = jsmn_parse(&p, json_buffer, size, t, sizeof(t)/sizeof(*t));
	if (count < 0)
		return;
	for (i = 0; i < count - 1; i++) {
		memset(json_name, 0, sizeof(json_name));
		memset(json_value, 0, sizeof(json_value));
		if ((t[i].type == JSMN_STRING) && (t[i].size == 1)) {
			if (!little64_json_token_to_string(json_name, sizeof(json_name), json_buffer, &t[i]))
				continue;
			if (!little64_json_token_to_string(json_value, sizeof(json_value), json_buffer, &t[i + 1]))
				continue;
			if (strncmp(json_name, "bootargs", 8) == 0) {
				continue;
			} else if (strncmp(json_name, "addr", 4) == 0) {
				boot_addr = strtoul(json_value, NULL, 0);
				boot_addr_found = 1;
			} else if (strncmp(json_name, "r1", 2) == 0) {
				boot_r1 = strtoul(json_value, NULL, 0);
			} else if (strncmp(json_name, "r2", 2) == 0) {
				boot_r2 = strtoul(json_value, NULL, 0);
			} else if (strncmp(json_name, "r3", 2) == 0) {
				boot_r3 = strtoul(json_value, NULL, 0);
			} else {
				size = copy_file_from_tftp_to_ram(ip, tftp_port, json_name, (void *)strtoul(json_value, NULL, 0));
				if (size <= 0)
					return;
				image_found = 1;
				if (boot_addr_found == 0)
					boot_addr = strtoul(json_value, NULL, 0);
			}
		}
	}

	if (image_found)
		boot(boot_r1, boot_r2, boot_r3, boot_addr);
}

void netboot(int nb_params, char **params)
{
	unsigned int ip;
	char *filename = NULL;

	if (nb_params > 0)
		filename = params[0];

	printf("Booting from network...\n");

	net_init();
	printf("Remote IP: %d.%d.%d.%d\n", remote_ip[0], remote_ip[1], remote_ip[2], remote_ip[3]);

	ip = IPTOINT(remote_ip[0], remote_ip[1], remote_ip[2], remote_ip[3]);

	if (filename) {
		printf("Booting from %s (JSON)...\n", filename);
		netboot_from_json(filename, ip, TFTP_SERVER_PORT);
	} else {
#ifndef ETH_NETBOOT_SKIP_JSON
		printf("Booting from boot.json...\n");
		netboot_from_json("boot.json", ip, TFTP_SERVER_PORT);
#endif

#ifdef MAIN_RAM_BASE
		printf("Booting from boot.bin...\n");
		netboot_from_bin("boot.bin", ip, TFTP_SERVER_PORT);
#endif
	}

	printf("Network boot failed.\n");
}
#endif

#if defined(CSR_SPISDCARD_BASE) || defined(CSR_SDCARD_CORE_BASE) || defined(CSR_SDCARD_BASE)
static int little64_copy_file_from_sdcard_to_ram(const char * filename, unsigned long ram_address)
{
	FRESULT fr;
	uint32_t br;
	uint32_t offset;
	unsigned long length;

	fr = f_mount(&little64_sd_fatfs, "", 1);
	if (fr != FR_OK) {
		little64_log_fatfs_failure("sdcard f_mount", fr);
		little64_debug_sdcard_volume();
		return 0;
	}
	fr = f_open(&little64_sd_file, filename, FA_READ);
	if (fr != FR_OK) {
		printf("%s open failed (%d).\n", filename, (int)fr);
		f_mount(0, "", 0);
		return 0;
	}

	length = f_size(&little64_sd_file);
	printf("Copying %s to 0x%08lx (%ld bytes)...\n", filename, ram_address, length);
	init_progression_bar(length);
	offset = 0;
	for (;;) {
		fr = f_read(&little64_sd_file, (void*) ram_address + offset, 0x8000, (UINT *)&br);
		if (fr != FR_OK) {
			little64_log_fatfs_failure("sdcard f_read", fr);
			f_close(&little64_sd_file);
			f_mount(0, "", 0);
			return 0;
		}
		if (br == 0)
			break;
		offset += br;
		show_progress(offset);
	}
	show_progress(offset);
	printf("\n");

	f_close(&little64_sd_file);
	f_mount(0, "", 0);

	return 1;
}

static void sdcardboot_from_json(const char * filename)
{
	FRESULT fr;

	int i;
	int count;
	uint32_t length;
	uint32_t result;

	unsigned long boot_r1 = 0;
	unsigned long boot_r2 = 0;
	unsigned long boot_r3 = 0;
	unsigned long boot_addr = 0;

	uint8_t image_found = 0;
	uint8_t boot_addr_found = 0;

	fr = f_mount(&little64_sd_fatfs, "", 1);
	if (fr != FR_OK) {
		little64_log_fatfs_failure("boot.json f_mount", fr);
		little64_debug_sdcard_volume();
		return;
	}
	fr = f_open(&little64_sd_file, filename, FA_READ);
	if (fr != FR_OK) {
		printf("%s open failed (%d).\n", filename, (int)fr);
		f_mount(0, "", 0);
		return;
	}

	fr = f_read(&little64_sd_file, little64_sd_json_buffer, sizeof(little64_sd_json_buffer) - 1, (UINT *) &length);

	f_close(&little64_sd_file);
	f_mount(0, "", 0);
	if (fr != FR_OK) {
		little64_log_fatfs_failure("boot.json f_read", fr);
		return;
	}
	little64_sd_json_buffer[length] = 0;

	jsmn_parser p;
	jsmn_init(&p);
	count = jsmn_parse(&p, little64_sd_json_buffer, length, little64_sd_json_tokens, sizeof(little64_sd_json_tokens)/sizeof(*little64_sd_json_tokens));
	if (count < 0) {
		printf("boot.json parse failed (%d).\n", count);
		return;
	}
	for (i = 0; i < count - 1; i++) {
		memset(little64_sd_json_name, 0, sizeof(little64_sd_json_name));
		memset(little64_sd_json_value, 0, sizeof(little64_sd_json_value));
		if ((little64_sd_json_tokens[i].type == JSMN_STRING) && (little64_sd_json_tokens[i].size == 1)) {
			if (!little64_json_token_to_string(little64_sd_json_name, sizeof(little64_sd_json_name), little64_sd_json_buffer, &little64_sd_json_tokens[i]))
				continue;
			if (!little64_json_token_to_string(little64_sd_json_value, sizeof(little64_sd_json_value), little64_sd_json_buffer, &little64_sd_json_tokens[i + 1]))
				continue;
			if (strncmp(little64_sd_json_name, "bootargs", 8) == 0) {
				continue;
			} else if (strncmp(little64_sd_json_name, "addr", 4) == 0) {
				boot_addr = strtoul(little64_sd_json_value, NULL, 0);
				boot_addr_found = 1;
			} else if (strncmp(little64_sd_json_name, "r1", 2) == 0) {
				boot_r1 = strtoul(little64_sd_json_value, NULL, 0);
			} else if (strncmp(little64_sd_json_name, "r2", 2) == 0) {
				boot_r2 = strtoul(little64_sd_json_value, NULL, 0);
			} else if (strncmp(little64_sd_json_name, "r3", 2) == 0) {
				boot_r3 = strtoul(little64_sd_json_value, NULL, 0);
			} else {
				result = little64_copy_file_from_sdcard_to_ram(little64_sd_json_name, strtoul(little64_sd_json_value, NULL, 0));
				if (result == 0)
					return;
				image_found = 1;
				if (boot_addr_found == 0)
					boot_addr = strtoul(little64_sd_json_value, NULL, 0);
			}
		}
	}

	if (image_found)
		boot(boot_r1, boot_r2, boot_r3, boot_addr);
	printf("boot.json contained no loadable images.\n");
}

void sdcardboot(void)
{
#ifdef CSR_SPISDCARD_BASE
	printf("Booting from SDCard in SPI-Mode...\n");
	fatfs_set_ops_spisdcard();
#endif
#if defined(CSR_SDCARD_CORE_BASE) || defined(CSR_SDCARD_BASE)
	printf("Booting from SDCard in SD-Mode...\n");
	#ifdef CSR_SDCARD_CORE_BASE
	FfDiskOps = &little64_debug_sd_disk_ops;
	#else
	fatfs_set_ops_sdcard();
	#endif
#endif

	printf("Booting from boot.json...\n");
	sdcardboot_from_json("boot.json");

#ifdef MAIN_RAM_BASE
	printf("Booting from boot.bin...\n");
	if (little64_copy_file_from_sdcard_to_ram("boot.bin", MAIN_RAM_BASE) != 0)
		boot(0, 0, 0, MAIN_RAM_BASE);
#endif

	printf("SDCard boot failed.\n");
}
#endif

#if defined(CSR_SATA_SECTOR2MEM_BASE)
static void sataboot_from_json(const char * filename)
{
	FRESULT fr;
	FATFS fs;
	FIL file;

	int i;
	int count;
	uint32_t length;
	uint32_t result;

	char json_buffer[1024];
	char json_name[32];
	char json_value[32];

	unsigned long boot_r1 = 0;
	unsigned long boot_r2 = 0;
	unsigned long boot_r3 = 0;
	unsigned long boot_addr = 0;

	uint8_t image_found = 0;
	uint8_t boot_addr_found = 0;

	fr = f_mount(&fs, "", 1);
	if (fr != FR_OK)
		return;
	fr = f_open(&file, filename, FA_READ);
	if (fr != FR_OK) {
		printf("%s file not found.\n", filename);
		f_mount(0, "", 0);
		return;
	}

	fr = f_read(&file, json_buffer, sizeof(json_buffer) - 1, (UINT *) &length);

	f_close(&file);
	f_mount(0, "", 0);
	if (fr != FR_OK)
		return;
	json_buffer[length] = 0;

	jsmntok_t t[32];
	jsmn_parser p;
	jsmn_init(&p);
	count = jsmn_parse(&p, json_buffer, length, t, sizeof(t)/sizeof(*t));
	if (count < 0)
		return;
	for (i = 0; i < count - 1; i++) {
		memset(json_name, 0, sizeof(json_name));
		memset(json_value, 0, sizeof(json_value));
		if ((t[i].type == JSMN_STRING) && (t[i].size == 1)) {
			if (!little64_json_token_to_string(json_name, sizeof(json_name), json_buffer, &t[i]))
				continue;
			if (!little64_json_token_to_string(json_value, sizeof(json_value), json_buffer, &t[i + 1]))
				continue;
			if (strncmp(json_name, "bootargs", 8) == 0) {
				continue;
			} else if (strncmp(json_name, "addr", 4) == 0) {
				boot_addr = strtoul(json_value, NULL, 0);
				boot_addr_found = 1;
			} else if (strncmp(json_name, "r1", 2) == 0) {
				boot_r1 = strtoul(json_value, NULL, 0);
			} else if (strncmp(json_name, "r2", 2) == 0) {
				boot_r2 = strtoul(json_value, NULL, 0);
			} else if (strncmp(json_name, "r3", 2) == 0) {
				boot_r3 = strtoul(json_value, NULL, 0);
			} else {
				result = copy_file_from_sata_to_ram(json_name, strtoul(json_value, NULL, 0));
				if (result == 0)
					return;
				image_found = 1;
				if (boot_addr_found == 0)
					boot_addr = strtoul(json_value, NULL, 0);
			}
		}
	}

	if (image_found)
		boot(boot_r1, boot_r2, boot_r3, boot_addr);
}

void sataboot(void)
{
	printf("Booting from SATA...\n");
	fatfs_set_ops_sata();

	printf("Booting from boot.json...\n");
	sataboot_from_json("boot.json");

	printf("Booting from boot.bin...\n");
	sataboot_from_bin("boot.bin");

	printf("SATA boot failed.\n");
}
#endif