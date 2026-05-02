/* Little64-specific __muldi3 override.
 *
 * Problem: On Little64, the compiler emits __muldi3 for ALL integer
 * multiplication, including uint32_t * uint32_t (no multiply instruction).
 * The generic muldi3.c uses __muldsi3 which does su_int * su_int using C's '*'
 * operator → compiles to __muldi3 → infinite recursion.
 *
 * Fix: Implement __muldi3 using __mulsi3 (self-contained, no recursion).
 * __mulsi3 is already compiled separately and is shift/add based.
 *
 * This file is standalone (no int_lib.h) to work in the LiteX BIOS build.
 */

typedef unsigned int          su_int;
typedef unsigned long long    du_int;
typedef long long             di_int;

typedef union {
    di_int all;
    struct {
#if _YUGA_LITTLE_ENDIAN
        su_int low;
        int    high;
#else
        int    high;
        su_int low;
#endif
    } s;
} dwords;

/* __mulsi3: 32x32->32, self-contained shift-add, no *-operator recursion. */
extern su_int __mulsi3(su_int a, su_int b);

/*
 * __muldsi3: 32x32->64 unsigned multiply via half-word decomposition.
 * Uses __mulsi3 for all 32-bit multiplications to avoid recursion.
 *
 * a * b = a_lo*b_lo + (a_lo*b_hi + a_hi*b_lo)*2^16 + a_hi*b_hi*2^32
 */
static di_int __muldsi3(su_int a, su_int b) {
    const su_int lo_mask = (su_int)0xffff;
    su_int a_lo = a & lo_mask;
    su_int a_hi = a >> 16;
    su_int b_lo = b & lo_mask;
    su_int b_hi = b >> 16;

    /* Each factor is 16-bit, so each product fits in 32 bits */
    su_int p0 = __mulsi3(a_lo, b_lo);   /* a_lo * b_lo: bits 0..31 */
    su_int p1 = __mulsi3(a_lo, b_hi);   /* a_lo * b_hi: contributes at bit 16 */
    su_int p2 = __mulsi3(a_hi, b_lo);   /* a_hi * b_lo: contributes at bit 16 */
    su_int p3 = __mulsi3(a_hi, b_hi);   /* a_hi * b_hi: bits 32..63 */

    /* Combine: result_lo = p0 + ((p1+p2) << 16)
     *          result_hi = p3 + ((p1+p2) >> 16) + carry from result_lo */
    su_int mid = p1 + p2;           /* may carry into bit 32 but su_int wraps */
    su_int mid_carry = (mid < p1) ? 1u : 0u; /* carry from p1+p2 addition */

    su_int result_lo = p0 + (mid << 16);
    su_int lo_carry  = (result_lo < p0) ? 1u : 0u;

    su_int result_hi = p3 + (mid >> 16) + (mid_carry << 16) + lo_carry;

    dwords r;
    r.s.low  = result_lo;
    r.s.high = (int)result_hi;
    return r.all;
}

/* __muldi3: 64x64->64 multiply. */
di_int __muldi3(di_int a, di_int b) {
    dwords x;
    x.all = a;
    dwords y;
    y.all = b;
    dwords r;
    r.all = __muldsi3(x.s.low, y.s.low);
    /* upper 32 bits of result: x.hi*y.lo + x.lo*y.hi + (existing high) */
    r.s.high += (int)(__mulsi3((su_int)x.s.high, y.s.low) +
                      __mulsi3(x.s.low, (su_int)y.s.high));
    return r.all;
}
