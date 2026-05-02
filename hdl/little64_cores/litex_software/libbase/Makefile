include ../include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

# Keep global interrupts disabled while debugging early BIOS bring-up on
# Little64 hardware; this avoids entering unstable IRQ paths.
CFLAGS += -DLITTLE64_BIOS_DISABLE_GLOBAL_IRQ_ENABLE

UPSTREAM_LIBBASE_DIRECTORY = $(SOC_DIRECTORY)/software/libbase

OBJECTS =  \
	crc16.o    \
	crc32.o    \
	console.o  \
	system.o   \
	progress.o \
	memtest.o  \
	uart.o     \
	spiflash.o \
	i2c.o      \
	isr.o      \
	hyperram.o

all: libbase.a

libbase.a: $(OBJECTS)
	$(AR) crs libbase.a $(OBJECTS)

# Force polling UART path on Little64 BIOS to avoid TX IRQ dependency during
# early hardware bring-up.
uart.o: CFLAGS += -DUART_POLLING

# pull in dependency info for *existing* .o files
-include $(OBJECTS:.o=.d)

VPATH = $(UPSTREAM_LIBBASE_DIRECTORY)

%.o: %.c
	$(compile)

.PHONY: all clean

clean:
	$(RM) $(OBJECTS)
	$(RM) libbase.a .*~ *~
