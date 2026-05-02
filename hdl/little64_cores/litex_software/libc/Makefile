include ../include/generated/variables.mak
include $(SOC_DIRECTORY)/software/common.mak

CFLAGS = $(filter-out --sysroot=% -I%/target/sysroot/usr/include -L%/target/sysroot/usr/lib,$(COMMONFLAGS)) -Wpragmas
CFLAGS += -I$(PICOLIBC_SOURCE_DIRECTORY)/libc/include -I$(PICOLIBC_BUILD_DIRECTORY)
CFLAGS += -ffunction-sections -fdata-sections

PICOLIBC_WORK_DIRECTORY=$(CURDIR)/picolibc-work
PICOLIBC_SOURCE_DIRECTORY=$(PICOLIBC_WORK_DIRECTORY)/source
PICOLIBC_BUILD_DIRECTORY=$(PICOLIBC_WORK_DIRECTORY)/build
PICOLIBC_LITTLE64_PATCH_DIRECTORY=$(CPU_DIRECTORY)/litex_software/picolibc/little64
PICOLIBC_SETJMP_HEADER=$(PICOLIBC_SOURCE_DIRECTORY)/libc/include/machine/setjmp.h
PICOLIBC_IEEEFP_HEADER=$(PICOLIBC_SOURCE_DIRECTORY)/libc/include/machine/ieeefp.h
UPSTREAM_LIBC_DIRECTORY=$(SOC_DIRECTORY)/software/libc
TRIPLE_TOOL_PREFIX=$(abspath ../../bin/$(TRIPLE)-)

CC=$(TRIPLE_TOOL_PREFIX)gcc
AR=$(TRIPLE_TOOL_PREFIX)gcc-ar
AS=$(TRIPLE_TOOL_PREFIX)as
NM=$(TRIPLE_TOOL_PREFIX)gcc-nm
STRIP=$(TRIPLE_TOOL_PREFIX)strip

define CROSSFILE
[binaries]
c     = ['$(TRIPLE_TOOL_PREFIX)gcc', '-fuse-ld=lld']
ar    = '$(TRIPLE_TOOL_PREFIX)gcc-ar'
as    = '$(TRIPLE_TOOL_PREFIX)as'
nm    = '$(TRIPLE_TOOL_PREFIX)gcc-nm'
strip = '$(TRIPLE_TOOL_PREFIX)strip'

[host_machine]
system     = 'unknown'
cpu_family = '$(CPUFAMILY)'
cpu        = '$(CPU)'
endian     = '$(CPUENDIANNESS)'

[built-in options]
c_args      = [ $(foreach flag,$(filter-out $(DEPFLAGS) -flto,$(CFLAGS)),'$(flag)',) ]
c_link_args = [ $(foreach flag,$(filter-out -flto,$(LDFLAGS)),'$(flag)',) ]
endef

export CROSSFILE

all: libc.a

cross.txt: FORCE
	@echo "$$CROSSFILE" > $@

__picolibc_source.stamp:
	rm -rf $(PICOLIBC_WORK_DIRECTORY)
	mkdir -p $(PICOLIBC_SOURCE_DIRECTORY)
	cp -a $(PICOLIBC_DIRECTORY)/. $(PICOLIBC_SOURCE_DIRECTORY)/
	mkdir -p $(PICOLIBC_SOURCE_DIRECTORY)/libc/machine/$(CPUFAMILY)
	cp -a $(PICOLIBC_LITTLE64_PATCH_DIRECTORY)/. $(PICOLIBC_SOURCE_DIRECTORY)/libc/machine/$(CPUFAMILY)/
	if ! grep -q '__little64__' $(PICOLIBC_SETJMP_HEADER); then \
		perl -0pi -e 's/#if defined\(__arm__\) \|\| defined\(__thumb__\)/#if defined(__little64__)\n#define _JBLEN 3\n#define _JBTYPE unsigned long\n#endif\n\n#if defined(__arm__) || defined(__thumb__)/' $(PICOLIBC_SETJMP_HEADER); \
	fi
	if ! grep -q 'LITTLE64_BYTE_ORDER_PATCH' $(PICOLIBC_IEEEFP_HEADER); then \
		perl -0pi -e 's/#ifndef __IEEE_BIG_ENDIAN\n#ifndef __IEEE_LITTLE_ENDIAN\n#error Endianess not declared!!/#ifndef __IEEE_BIG_ENDIAN\n#ifndef __IEEE_LITTLE_ENDIAN\n\/\* LITTLE64_BYTE_ORDER_PATCH: fallback when __FLOAT_WORD_ORDER__ is unavailable. \*\/\n#ifdef __BYTE_ORDER__\n#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__\n#define __IEEE_LITTLE_ENDIAN\n#endif\n#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__\n#define __IEEE_BIG_ENDIAN\n#endif\n#endif\n#endif\n#endif\n\n#ifndef __IEEE_BIG_ENDIAN\n#ifndef __IEEE_LITTLE_ENDIAN\n#error Endianess not declared!!/' $(PICOLIBC_IEEEFP_HEADER); \
	fi
	touch $@

__libc.a: cross.txt __picolibc_source.stamp
	meson setup $(PICOLIBC_BUILD_DIRECTORY) $(PICOLIBC_SOURCE_DIRECTORY) \
		--wipe \
		-Dmultilib=false \
		-Dpicocrt=false \
		-Denable-malloc=false \
		-Dsingle-thread=true \
		-Datomic-ungetc=false \
		-Dthread-local-storage=false \
		-Dthread-local-storage-api=false \
		-Dio-c99-formats=false \
		-Dio-float-exact=false \
		-Dformat-default=$(PICOLIBC_FORMAT) \
		-Dincludedir=picolibc/$(TRIPLE)/include \
		-Dlibdir=picolibc/$(TRIPLE)/lib \
		--cross-file cross.txt
	meson compile -C $(PICOLIBC_BUILD_DIRECTORY)
	cp $(PICOLIBC_BUILD_DIRECTORY)/libc.a __libc.a

_libc.a: $(UPSTREAM_LIBC_DIRECTORY)/stdio.c __libc.a
	$(compile)
	$(AR) csr __libc.a $@
	cp __libc.a _libc.a

libc.a: $(UPSTREAM_LIBC_DIRECTORY)/missing.c _libc.a
	$(compile)
	$(AR) csr _libc.a $@
	cp _libc.a libc.a

clean:
	rm -rf $(PICOLIBC_WORK_DIRECTORY)
	rm -f cross.txt __picolibc_source.stamp __libc.a _libc.a libc.a

.PHONY: all clean FORCE

FORCE: