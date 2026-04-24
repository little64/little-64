"""C source templates emitted into the LiteX stage-0 build tree.

Separated from :mod:`little64.commands.sd.artifacts` so the imperative
artifact-building code stays visible instead of being buried under 200 lines
of verbatim C. The strings are consumed verbatim; do not edit formatting
without matching the expected C semantics.
"""

from __future__ import annotations


STAGE0_SYSTEM_HEADER = """#ifndef __SYSTEM_H
#define __SYSTEM_H

#ifdef CONFIG_CPU_NOP
#undef CONFIG_CPU_NOP
#endif
#define CONFIG_CPU_NOP \"move R0, R0\"

#endif
"""


STAGE0_HW_COMMON_HEADER = """#ifndef __HW_COMMON_H
#define __HW_COMMON_H

#include <stdint.h>
#include <generated/soc.h>
#include <system.h>

#ifndef CSR_ACCESSORS_DEFINED
#define CSR_ACCESSORS_DEFINED

#define MMPTR(a) (*((volatile uint32_t *)(a)))

static inline void cdelay(int iterations) {
#ifndef CONFIG_BIOS_NO_DELAYS
    while (iterations > 0) {
        __asm__ volatile(CONFIG_CPU_NOP);
        --iterations;
    }
#endif
}

static inline void csr_write_simple(unsigned long value, unsigned long address) {
    MMPTR(address) = (uint32_t)value;
}

static inline unsigned long csr_read_simple(unsigned long address) {
    return MMPTR(address);
}

#endif

#define CSR_DW_BYTES     (CONFIG_CSR_DATA_WIDTH/8)
#define CSR_OFFSET_BYTES 4

static inline int num_subregs(int csr_bytes) {
    return (csr_bytes - 1) / CSR_DW_BYTES + 1;
}

static inline uint64_t _csr_rd(unsigned long address, int csr_bytes) {
    uint64_t value = csr_read_simple(address);
    for (int index = 1; index < num_subregs(csr_bytes); ++index) {
        value <<= CONFIG_CSR_DATA_WIDTH;
        address += CSR_OFFSET_BYTES;
        value |= csr_read_simple(address);
    }
    return value;
}

static inline void _csr_wr(unsigned long address, uint64_t value, int csr_bytes) {
    int subregs = num_subregs(csr_bytes);
    for (int index = 0; index < subregs; ++index) {
        csr_write_simple(value >> (CONFIG_CSR_DATA_WIDTH * (subregs - 1 - index)), address);
        address += CSR_OFFSET_BYTES;
    }
}

static inline uint8_t csr_rd_uint8(unsigned long address) {
    return (uint8_t)_csr_rd(address, sizeof(uint8_t));
}

static inline void csr_wr_uint8(uint8_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint8_t));
}

static inline uint16_t csr_rd_uint16(unsigned long address) {
    return (uint16_t)_csr_rd(address, sizeof(uint16_t));
}

static inline void csr_wr_uint16(uint16_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint16_t));
}

static inline uint32_t csr_rd_uint32(unsigned long address) {
    return (uint32_t)_csr_rd(address, sizeof(uint32_t));
}

static inline void csr_wr_uint32(uint32_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint32_t));
}

static inline uint64_t csr_rd_uint64(unsigned long address) {
    return _csr_rd(address, sizeof(uint64_t));
}

static inline void csr_wr_uint64(uint64_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint64_t));
}

#define _csr_rd_buf(address, buf, count) \
{ \
    int index, subindex, offset, subregs, subelems; \
    uint64_t value; \
    if (sizeof(buf[0]) >= CSR_DW_BYTES) { \
        for (index = 0; index < count; ++index) { \
            buf[index] = _csr_rd(address, sizeof(buf[0])); \
            address += CSR_OFFSET_BYTES * num_subregs(sizeof(buf[0])); \
        } \
    } else { \
        subregs = num_subregs(sizeof(buf[0]) * count); \
        subelems = CSR_DW_BYTES / sizeof(buf[0]); \
        offset = subregs * subelems - count; \
        for (index = 0; index < subregs; ++index) { \
            value = csr_read_simple(address); \
            for (subindex = subelems - 1; subindex >= 0; --subindex) { \
                if ((index * subelems + subindex - offset) >= 0) { \
                    buf[index * subelems + subindex - offset] = value; \
                    value >>= sizeof(buf[0]) * 8; \
                } \
            } \
            address += CSR_OFFSET_BYTES; \
        } \
    } \
}

#define _csr_wr_buf(address, buf, count) \
{ \
    int index, subindex, offset, subregs, subelems; \
    uint64_t value; \
    if (sizeof(buf[0]) >= CSR_DW_BYTES) { \
        for (index = 0; index < count; ++index) { \
            _csr_wr(address, buf[index], sizeof(buf[0])); \
            address += CSR_OFFSET_BYTES * num_subregs(sizeof(buf[0])); \
        } \
    } else { \
        subregs = num_subregs(sizeof(buf[0]) * count); \
        subelems = CSR_DW_BYTES / sizeof(buf[0]); \
        offset = subregs * subelems - count; \
        for (index = 0; index < subregs; ++index) { \
            value = 0; \
            for (subindex = 0; subindex < subelems; ++subindex) { \
                if ((index * subelems + subindex - offset) >= 0) { \
                    value <<= sizeof(buf[0]) * 8; \
                    value |= buf[index * subelems + subindex - offset]; \
                } \
            } \
            csr_write_simple(value, address); \
            address += CSR_OFFSET_BYTES; \
        } \
    } \
}

static inline void csr_rd_buf_uint8(unsigned long address, uint8_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint8(unsigned long address, const uint8_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint16(unsigned long address, uint16_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint16(unsigned long address, const uint16_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint32(unsigned long address, uint32_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint32(unsigned long address, const uint32_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint64(unsigned long address, uint64_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint64(unsigned long address, const uint64_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

#endif
"""
