include ../include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

CFLAGS += -include inttypes.h
UPSTREAM_LIBLITEDRAM_DIRECTORY=$(SOC_DIRECTORY)/software/liblitedram

OBJECTS = \
	accessors.o \
	bist.o \
	sdram.o \
	sdram_dbg.o \
	sdram_spd.o \
	utils.o

all: liblitedram.a

liblitedram.a: $(OBJECTS)
	$(AR) crs liblitedram.a $(OBJECTS)

-include $(OBJECTS:.o=.d)

%.o: $(UPSTREAM_LIBLITEDRAM_DIRECTORY)/%.c
	$(compile)

.PHONY: all clean

clean:
	$(RM) $(OBJECTS)
	$(RM) liblitedram.a .*~ *~