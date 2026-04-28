#ifndef CORE_PORTME_H
#define CORE_PORTME_H

/*
 * core_portme.h — Little-64 bare-metal HDL-harness CoreMark port.
 *
 * Timing is a no-op; cycle counts are measured externally by the HDL
 * simulation harness (run_elf_flat in shared_program.py).
 */

#include <stddef.h>
#include <stdint.h>

/* ---- Integer types ---- */
typedef int8_t   ee_s8;
typedef uint8_t  ee_u8;
typedef int16_t  ee_s16;
typedef uint16_t ee_u16;
typedef int32_t  ee_s32;
typedef uint32_t ee_u32;
typedef uint64_t ee_u64;
typedef uint32_t ee_f32;

/* Required by coremark internals */
typedef uint32_t ee_ptr_int;
typedef size_t ee_size_t;
typedef uint32_t mem_size_t;
#ifndef NULL
#define NULL ((void *)0)
#endif

/* ---- Timer (dummy — measured externally by the HDL harness) ---- */
typedef uint32_t CORE_TICKS;
#define CORETIMETYPE ee_u32
typedef uint32_t secs_ret;

#define GETMYTIME(_t)         (*(_t) = 0)
#define MYTIMEDIFF(fin, ini)  ((fin) - (ini))
#define TIMER_RES_DIVIDER     1
#define SAMPLE_TIME_IMPLEMENTATION 1
#define EE_TICKS_PER_SEC      1000000UL

/* ---- Platform feature flags ---- */
#define HAS_FLOAT   0
#define HAS_TIME_H  0
#define USE_CLOCK   0
#define HAS_STDIO   0
#define HAS_PRINTF  0

/* CoreMark requires a compile-time context count contract. */
#ifndef MULTITHREAD
#define MULTITHREAD 1
#endif
#define USE_PTHREAD 0
#define USE_FORK 0
#define USE_SOCKET 0

/* ---- Memory allocation ---- */
#define MEM_METHOD   MEM_STATIC
#define MEM_LOCATION "STATIC"
#define MEM_ALIGNMENT 4
#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x)-1) & ~3))

/* ---- Iteration count (override at compile time via -DITERATIONS=N) ---- */
#ifndef ITERATIONS
#  define ITERATIONS 1
#endif

/* ---- Seed method ---- */
#define SEED_METHOD SEED_FUNC

#if !defined(PROFILE_RUN) && !defined(PERFORMANCE_RUN) && !defined(VALIDATION_RUN)
#if (TOTAL_DATA_SIZE == 1200)
#define PROFILE_RUN 1
#elif (TOTAL_DATA_SIZE == 2000)
#define PERFORMANCE_RUN 1
#else
#define VALIDATION_RUN 1
#endif
#endif

/* ---- Compiler info strings ---- */
#define COMPILER_FLAGS   "-O2 -target little64"
#define COMPILER_VERSION "clang (little64)"

/* ---- main() return-value convention ---- */
#define MAIN_HAS_NORETURN 0

/* ---- Port interface declarations ---- */
typedef struct core_portable_s {
    uint8_t portable_id;
} core_portable;

extern ee_u32 default_num_contexts;

void portable_init(core_portable *p, int *argc, char *argv[]);
void portable_fini(core_portable *p);

ee_s32 get_seed_32(int i);
ee_s32 portme_sys1(void);
ee_s32 portme_sys2(void);
ee_s32 portme_sys3(void);
ee_s32 portme_sys4(void);
ee_s32 portme_sys5(void);

/* Timing stubs (implemented in core_portme.c) */
void     start_time(void);
void     stop_time(void);
CORE_TICKS get_time(void);
secs_ret time_in_secs(CORE_TICKS ticks);

/* Output (no-op, implemented in core_portme.c) */
int ee_printf(const char *fmt, ...);

#endif /* CORE_PORTME_H */
