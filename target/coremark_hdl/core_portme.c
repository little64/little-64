/* core_portme.c — Little-64 bare-metal HDL-harness CoreMark port. */

#include "coremark.h"

ee_u32 default_num_contexts = 1;

/* ---- Timing stubs ---- */

void start_time(void) {}

void stop_time(void) {}

CORE_TICKS get_time(void) { return 0; }

secs_ret time_in_secs(CORE_TICKS ticks) { (void)ticks; return 0; }

/* ---- Output (no-op) ---- */

int ee_printf(const char *fmt, ...) {
    (void)fmt;
    return 0;
}

/* ---- Platform init / fini ---- */

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)p; (void)argc; (void)argv;
}

void portable_fini(core_portable *p) {
    (void)p;
}

/* Seed hooks consumed by core_util.c when SEED_METHOD == SEED_FUNC. */
ee_s32 portme_sys1(void) { return 0; }
ee_s32 portme_sys2(void) { return 0; }
ee_s32 portme_sys3(void) { return 0x66; }
ee_s32 portme_sys4(void) { return ITERATIONS; }
ee_s32 portme_sys5(void) { return 0; }

/* Static-memory build path; malloc/free are unused but must be linkable. */
void *portable_malloc(ee_size_t size) {
    (void)size;
    return NULL;
}

void portable_free(void *p) {
    (void)p;
}

/* ---- Minimal memory stub ----
 *
 * CoreMark calls memset() for matrix initialisation.  With -fno-builtin
 * we must supply it ourselves since there is no libc in this freestanding
 * environment.
 */
void *memset(void *s, int c, __SIZE_TYPE__ n) {
    unsigned char *p = (unsigned char *)s;
    while (n--) *p++ = (unsigned char)c;
    return s;
}

/* ---- Soft 64-bit multiply stub ----
 *
 * Mirrors the stub used by the BIOS boot test; avoids a compiler-rt
 * builtins linkage dependency for code paths that emit __muldi3.
 */
long long __attribute__((used)) __muldi3(long long a, long long b) {
    unsigned long long ua = (unsigned long long)a;
    unsigned long long ub = (unsigned long long)b;
    unsigned long long res = 0;
    while (ub) {
        if (ub & 1ULL) res += ua;
        ua <<= 1;
        ub >>= 1;
    }
    return (long long)res;
}
