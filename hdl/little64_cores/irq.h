#ifndef __IRQ_H
#define __IRQ_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

static inline uint64_t little64_read_special(uint64_t selector)
{
	uint64_t value;
	__asm__ __volatile__("LSR\t%1, %0" : "=r" (value) : "r" (selector));
	return value;
}

static inline void little64_write_special(uint64_t selector, uint64_t value)
{
	__asm__ __volatile__("SSR\t%0, %1" : : "r" (selector), "r" (value));
}

static inline unsigned int irq_getie(void)
{
	return (unsigned int)(little64_read_special(0) & 0x1ULL);
}

static inline void irq_setie(unsigned int ie)
{
	#ifdef LITTLE64_BIOS_DISABLE_GLOBAL_IRQ_ENABLE
	(void)ie;
	return;
	#endif

	uint64_t cpu_control = little64_read_special(0);
	if (ie) {
		/*
		 * Little64 requires a valid interrupt table for maskable IRQ delivery.
		 * LiteX BIOS enables interrupts very early; keep interrupts disabled until
		 * software has installed a non-zero interrupt_table_base (selector 16).
		 */
		if (little64_read_special(16) != 0)
			cpu_control |= 0x1ULL;
		else
			cpu_control &= ~0x1ULL;
	} else {
		cpu_control &= ~0x1ULL;
 	}
	little64_write_special(0, cpu_control);
}

static inline unsigned int irq_getmask(void)
{
	/*
	 * LiteX interrupt lines map to architectural IRQ vectors 65..127.
	 * Vector 64 (high-bank bit 0) is reserved, so expose a logical line mask
	 * by shifting the architectural high-bank mask down by one bit.
	 */
	return (unsigned int)(little64_read_special(18) >> 1);
}

static inline void irq_setmask(unsigned int mask)
{
	little64_write_special(18, ((uint64_t)mask) << 1);
}

static inline unsigned int irq_pending(void)
{
	return (unsigned int)(little64_read_special(20) >> 1);
}

#ifdef __cplusplus
}
#endif

#endif