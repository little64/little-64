#pragma once

#include <cstdint>
#include <cstdio>

static int _pass = 0;
static int _fail = 0;

#define CHECK_EQ(actual, expected, msg)                                         \
    do {                                                                        \
        uint64_t _a = static_cast<uint64_t>(actual);                            \
        uint64_t _e = static_cast<uint64_t>(expected);                          \
        if (_a == _e) {                                                         \
            _pass++;                                                            \
        } else {                                                                \
            std::fprintf(stderr, "FAIL [%s:%d] %s\n"                         \
                                 "  expected: 0x%016llX\n"                    \
                                 "  actual  : 0x%016llX\n",                   \
                         __FILE__, __LINE__, (msg),                             \
                         static_cast<unsigned long long>(_e),                   \
                         static_cast<unsigned long long>(_a));                  \
            _fail++;                                                            \
        }                                                                       \
    } while (0)

#define CHECK_TRUE(cond, msg)  CHECK_EQ(!!(cond), 1ULL, (msg))
#define CHECK_FALSE(cond, msg) CHECK_EQ(!!(cond), 0ULL, (msg))

#define CHECK_THROWS(expr, msg)                                                 \
    do {                                                                        \
        bool _threw = false;                                                    \
        try { (expr); } catch (...) { _threw = true; }                          \
        if (_threw) {                                                           \
            _pass++;                                                            \
        } else {                                                                \
            std::fprintf(stderr, "FAIL [%s:%d] expected exception: %s\n",    \
                         __FILE__, __LINE__, (msg));                            \
            _fail++;                                                            \
        }                                                                       \
    } while (0)

static int print_summary() {
    std::printf("\n=== Results: %d passed, %d failed ===\n", _pass, _fail);
    return _fail != 0 ? 1 : 0;
}
