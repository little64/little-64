include ../include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

MAKEFILE_DIR := $(dir $(abspath $(firstword $(MAKEFILE_LIST))))
REPO_PYTHON := $(abspath $(MAKEFILE_DIR)/../../../../.venv/bin/python)
PYTHON := $(if $(wildcard $(REPO_PYTHON)),$(REPO_PYTHON),python3)

# In LiteX BIOS mode we provide a local picolibc build in ../libc; avoid
# pulling headers/libs from the external mlibc sysroot by default.
CFLAGS := $(filter-out --sysroot=% -I%/target/sysroot/usr/include -L%/target/sysroot/usr/lib,$(CFLAGS))
LDFLAGS := $(filter-out --sysroot=% -I%/target/sysroot/usr/include -L%/target/sysroot/usr/lib,$(LDFLAGS))
CFLAGS += -I../libc/picolibc-work/source/libc/include -I../libc/picolibc-work/build

UPSTREAM_BIOS_DIRECTORY=$(SOC_DIRECTORY)/software/bios
CFLAGS += -DUPSTREAM_BIOS_BOOT_C=\"$(UPSTREAM_BIOS_DIRECTORY)/boot.c\"

# Permit TFTP_SERVER_PORT override from shell environment / command line
ifdef TFTP_SERVER_PORT
CFLAGS += -DTFTP_SERVER_PORT=$(TFTP_SERVER_PORT)
endif

OBJECTS = boot-helper.o	\
	  boot.o			\
	  helpers.o			\
	  cmd_bios.o		\
	  cmd_mem.o			\
	  cmd_boot.o		\
	  cmd_i2c.o			\
	  cmd_spiflash.o	\
	  cmd_litedram.o	\
	  cmd_liteeth.o		\
	  cmd_litesdcard.o  \
	  cmd_litesata.o    \
	  sim_debug.o		\
	  main.o

ifneq "$(or $(BIOS_CONSOLE_NO_AUTOCOMPLETE),$(BIOS_CONSOLE_LITE))" ""
CFLAGS += -DBIOS_CONSOLE_NO_AUTOCOMPLETE
else
OBJECTS += complete.o
endif

ifdef BIOS_CONSOLE_NO_HISTORY
CFLAGS += -DBIOS_CONSOLE_NO_HISTORY
endif

ifdef BIOS_CONSOLE_DISABLE
CFLAGS += -DBIOS_CONSOLE_DISABLE
endif

ifdef BIOS_CONSOLE_LITE
CFLAGS += -DBIOS_CONSOLE_LITE
OBJECTS += readline_simple.o
else
OBJECTS += readline.o
endif

ifeq ($(CPU), zynq7000)
LSCRIPT = linker-zynq.ld
else ifeq ($(CPU), zynqmp)
LSCRIPT = linker-zynqmp.ld
else
LSCRIPT = linker.ld
endif

all: bios.bin
	$(PYTHON) -m litex.soc.software.memusage bios.elf $(CURDIR)/../include/generated/regions.ld $(TRIPLE)

%.bin: %.elf
	$(OBJCOPY) -O binary $< $@
ifneq ($(OS),Windows_NT)
	chmod -x $@
endif
ifeq ($(CPUENDIANNESS),little)
	$(PYTHON) -m litex.soc.software.crcfbigen $@ --little
else
	$(PYTHON) -m litex.soc.software.crcfbigen $@
endif

bios.elf: $(BIOS_DIRECTORY)/$(LSCRIPT) $(OBJECTS)

vpath %.a $(PACKAGES:%=../%)

%.elf: crt0.o $(LIBS:%=%.a)
	$(CC) $(LDFLAGS) -nostdlib -nostartfiles -nodefaultlibs -T $(BIOS_DIRECTORY)/$(LSCRIPT) -Wl,-N -o $@ \
		crt0.o \
		$(OBJECTS) \
		$(PACKAGES:%=-L../%) \
		-Wl,--gc-sections \
		-Wl,-Map,$@.map \
		$(LIBS:lib%=-l%)

ifneq ($(OS),Windows_NT)
	chmod -x $@
endif

# pull in dependency info for *existing* .o files
-include $(OBJECTS:.o=.d)

helpers.o: CFLAGS += -include stdint.h

VPATH = $(MAKEFILE_DIR):$(UPSTREAM_BIOS_DIRECTORY):$(UPSTREAM_BIOS_DIRECTORY)/cmds:$(CPU_DIRECTORY)

%.o: %.c
	$(compile)

%.o: %.S
	$(assemble)

clean:
	$(RM) $(OBJECTS) bios.elf bios.bin .*~ *~

.PHONY: all clean