#ifndef __SYSTEM_H
#define __SYSTEM_H

#ifdef __cplusplus
extern "C" {
#endif

__attribute__((unused)) static inline void flush_cpu_icache(void)
{
	__asm__ __volatile__("" : : : "memory");
}

__attribute__((unused)) static inline void flush_cpu_dcache(void)
{
	__asm__ __volatile__("" : : : "memory");
}

void flush_l2_cache(void);

void busy_wait(unsigned int ms);
void busy_wait_us(unsigned int us);

#ifdef __cplusplus
}
#endif

#endif