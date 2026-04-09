#include "support/test_harness.hpp"

#include "compiler.hpp"
#include "cpu.hpp"
#include "linker.hpp"

#include <cstdio>
#include <cstdint>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr uint64_t kResultAddr = 0x3000;
constexpr uint64_t kVarargsProbeAddr = 0x3008;
constexpr int kMaxCycles = 400000;
constexpr int kHeavyMaxCycles = 5000000;
constexpr int kVarargsHeavyMaxCycles = 12000000;
constexpr int kSoakRuns = 3;

const std::vector<const char*> kOptLevels = {"0", "1", "2", "3"};

bool compile_link_source_words(const std::string& source,
                               const char* opt_level,
                               std::vector<uint16_t>& words_out) {
    std::string compile_error;
    auto object = Compiler::compileSourceText(source, "clang_runtime_stress.c", false, opt_level, compile_error);
    if (!object) {
        std::fprintf(stderr, "Compile failed at -O%s:\n%s\n", opt_level, compile_error.c_str());
        CHECK_TRUE(false, "Clang compileSourceText should succeed");
        return false;
    }

    LinkError link_error;
    auto words = Linker::linkObjects({*object}, &link_error);
    if (!words) {
        std::fprintf(stderr, "Link failed at -O%s:\n%s\n", opt_level, link_error.message.c_str());
        CHECK_TRUE(false, "Linker::linkObjects should succeed");
        return false;
    }

    words_out = std::move(*words);
    return true;
}

bool run_program_words(const std::vector<uint16_t>& words,
                       const char* opt_level,
                       Little64CPU& cpu_out,
                       int max_cycles,
                       bool& timed_out) {
    Little64CPU cpu;
    cpu.loadProgram(words);

    int cycles = 0;
    while (cpu.isRunning && cycles < max_cycles) {
        cpu.cycle();
        ++cycles;
    }

    timed_out = cpu.isRunning;
    cpu_out = std::move(cpu);
    return true;
}

bool compile_link_run_c_source(const std::string& source,
                               const char* opt_level,
                               Little64CPU& cpu_out,
                               int max_cycles = kMaxCycles,
                               const char* workload_label = nullptr) {
    std::vector<uint16_t> words;
    if (!compile_link_source_words(source, opt_level, words)) {
        return false;
    }

    bool timed_out = false;
    if (!run_program_words(words, opt_level, cpu_out, max_cycles, timed_out)) {
        return false;
    }

    if (timed_out) {
        if (workload_label != nullptr) {
            std::fprintf(stderr,
                         "Program did not STOP [%s] at -O%s within %d cycles (PC=0x%016llx)\n",
                         workload_label,
                         opt_level,
                         max_cycles,
                         static_cast<unsigned long long>(cpu_out.registers.regs[15]));
        } else {
            std::fprintf(stderr,
                         "Program did not STOP at -O%s within %d cycles (PC=0x%016llx)\n",
                         opt_level,
                         max_cycles,
                         static_cast<unsigned long long>(cpu_out.registers.regs[15]));
        }
        CHECK_TRUE(false, "Compiled C program should halt with STOP");
        return false;
    }
    return true;
}

bool compile_link_expect_timeout(const std::string& source,
                                 const char* opt_level,
                                 int max_cycles) {
    std::vector<uint16_t> words;
    if (!compile_link_source_words(source, opt_level, words)) {
        return false;
    }

    Little64CPU cpu;
    bool timed_out = false;
    if (!run_program_words(words, opt_level, cpu, max_cycles, timed_out)) {
        return false;
    }

    if (!timed_out) {
        std::fprintf(stderr,
                     "Expected timeout at -O%s but program halted early (PC=0x%016llx)\n",
                     opt_level,
                     static_cast<unsigned long long>(cpu.registers.regs[15]));
        CHECK_TRUE(false, "Timeout guard should fail a non-halting program");
        return false;
    }

    return true;
}

std::string make_recursive_program(uint64_t seed, uint64_t salt, uint64_t depth) {
    std::ostringstream src;
    src
        << "typedef unsigned long long u64;\n"
        << "static volatile u64* const OUT = (volatile u64*)0x3000ULL;\n"
        << "__attribute__((noinline)) static u64 rec_mix(u64 n, u64 acc, u64 salt) {\n"
        << "  volatile u64 mix1 = acc ^ (salt + (n << 2));\n"
        << "  volatile u64 mix2 = salt ^ (acc >> 1) ^ n;\n"
        << "  if (n == 0ULL) return mix1 + mix2 + 0x55ULL;\n"
        << "  u64 inner = rec_mix(n - 1ULL, mix1 + n, mix2 + 0x9ULL);\n"
        << "  return inner ^ (mix1 + (mix2 << 1) + n);\n"
        << "}\n"
        << "void _start(void) {\n"
        << "  volatile u64 result = rec_mix(" << depth << "ULL, " << seed << "ULL, " << salt << "ULL);\n"
        << "  *OUT = result;\n"
        << "  __asm__ volatile(\"STOP\");\n"
        << "}\n";
    return src.str();
}

uint64_t recursive_expected_inner(uint64_t n, uint64_t acc, uint64_t salt) {
    const uint64_t mix1 = acc ^ (salt + (n << 2));
    const uint64_t mix2 = salt ^ (acc >> 1) ^ n;
    if (n == 0ULL) {
        return mix1 + mix2 + 0x55ULL;
    }
    const uint64_t inner = recursive_expected_inner(n - 1ULL, mix1 + n, mix2 + 0x9ULL);
    return inner ^ (mix1 + (mix2 << 1) + n);
}

uint64_t recursive_expected(uint64_t seed, uint64_t salt, uint64_t depth) {
    return recursive_expected_inner(depth, seed, salt);
}

std::string make_deep_call_program(uint64_t seed, int depth) {
    std::ostringstream src;
    src << "typedef unsigned long long u64;\n";
    src << "static volatile u64* const OUT = (volatile u64*)0x3000ULL;\n";

    for (int i = 0; i <= depth; ++i) {
        src << "__attribute__((noinline)) static u64 f" << i << "(u64 x);\n";
    }

    for (int i = 0; i < depth; ++i) {
        const int s1 = (i % 5) + 1;
        const int s2 = (i % 3) + 1;
        const uint64_t c1 = 0x11ULL + static_cast<uint64_t>(i) * 3ULL;
        const uint64_t c2 = 0x100ULL + static_cast<uint64_t>(i) * 5ULL;

        src
            << "__attribute__((noinline)) static u64 f" << i << "(u64 x) {\n"
            << "  volatile u64 a = x + " << c1 << "ULL;\n"
            << "  volatile u64 b = a ^ (x << " << s1 << ");\n"
            << "  volatile u64 c = b + " << c2 << "ULL;\n"
            << "  return f" << (i + 1) << "(c ^ (a >> " << s2 << "));\n"
            << "}\n";
    }

    src
        << "__attribute__((noinline)) static u64 f" << depth << "(u64 x) {\n"
        << "  volatile u64 a = x + 0x31ULL;\n"
        << "  volatile u64 b = a ^ (x >> 2);\n"
        << "  return b + 0x2222ULL;\n"
        << "}\n"
        << "void _start(void) {\n"
        << "  volatile u64 result = f0(" << seed << "ULL);\n"
        << "  *OUT = result;\n"
        << "  __asm__ volatile(\"STOP\");\n"
        << "}\n";

    return src.str();
}

uint64_t deep_call_expected(uint64_t seed, int depth) {
    uint64_t x = seed;
    for (int i = 0; i < depth; ++i) {
        const int s1 = (i % 5) + 1;
        const int s2 = (i % 3) + 1;
        const uint64_t c1 = 0x11ULL + static_cast<uint64_t>(i) * 3ULL;
        const uint64_t c2 = 0x100ULL + static_cast<uint64_t>(i) * 5ULL;

        const uint64_t a = x + c1;
        const uint64_t b = a ^ (x << s1);
        const uint64_t c = b + c2;
        x = c ^ (a >> s2);
    }

    const uint64_t a = x + 0x31ULL;
    const uint64_t b = a ^ (x >> 2);
    return b + 0x2222ULL;
}

std::string make_register_pressure_program(uint64_t seed, int var_count, int rounds) {
    std::ostringstream src;
    src
        << "typedef unsigned long long u64;\n"
        << "static volatile u64* const OUT = (volatile u64*)0x3000ULL;\n"
        << "__attribute__((noinline)) static u64 pressure(u64 seed) {\n";

    for (int i = 0; i < var_count; ++i) {
        src << "  volatile u64 v" << i << " = seed + " << (i + 1) << "ULL;\n";
    }

    src << "  for (u64 i = 0; i < " << rounds << "ULL; ++i) {\n";
    for (int i = 0; i < var_count; ++i) {
        const int ref = (i + (var_count / 2)) % var_count;
        const int prev = (i + var_count - 1) % var_count;
        const int sh = (i % 3) + 1;
        src << "    v" << i << " = v" << i
            << " + (v" << ref << " ^ (v" << prev << " >> " << sh << ") ^ (i + " << i << "ULL));\n";
    }
    src << "  }\n";

    src << "  u64 out = 0ULL;\n";
    for (int i = 0; i < var_count; ++i) {
        src << "  out ^= v" << i << ";\n";
    }

    src
        << "  return out;\n"
        << "}\n"
        << "void _start(void) {\n"
        << "  volatile u64 result = pressure(" << seed << "ULL);\n"
        << "  *OUT = result;\n"
        << "  __asm__ volatile(\"STOP\");\n"
        << "}\n";

    return src.str();
}

uint64_t register_pressure_expected(uint64_t seed, int var_count, int rounds) {
    std::vector<uint64_t> vars;
    vars.reserve(static_cast<size_t>(var_count));

    for (int i = 0; i < var_count; ++i) {
        vars.push_back(seed + static_cast<uint64_t>(i + 1));
    }

    for (uint64_t i = 0; i < static_cast<uint64_t>(rounds); ++i) {
        for (int j = 0; j < var_count; ++j) {
            const int ref = (j + (var_count / 2)) % var_count;
            const int prev = (j + var_count - 1) % var_count;
            const int sh = (j % 3) + 1;
            vars[static_cast<size_t>(j)] = vars[static_cast<size_t>(j)]
                + (vars[static_cast<size_t>(ref)]
                    ^ (vars[static_cast<size_t>(prev)] >> sh)
                    ^ (i + static_cast<uint64_t>(j)));
        }
    }

    uint64_t out = 0;
    for (uint64_t v : vars) {
        out ^= v;
    }
    return out;
}

uint64_t fold_values(const std::vector<uint64_t>& values) {
    uint64_t acc = 0x1234FEDCBA987654ULL ^ static_cast<uint64_t>(values.size());
    uint64_t salt = 0x9E3779B97F4A7C15ULL;
    for (size_t i = 0; i < values.size(); ++i) {
        const uint64_t v = values[i];
        salt = (salt ^ (salt << 5)) + 0xD1B54A32D192ED03ULL + static_cast<uint64_t>(i);
        acc ^= (v + salt + static_cast<uint64_t>(i));
        acc = (acc << 7) ^ (acc >> 3) ^ (v << (static_cast<uint64_t>(i) & 7ULL));
    }
    return acc;
}

uint64_t fold_values_recursive_inner(const std::vector<uint64_t>& values, size_t idx, uint64_t acc) {
    if (idx == values.size()) {
        return acc + 0x77ULL;
    }

    const uint64_t v = values[idx];
    const uint64_t mix = (v ^ (acc >> 2)) + (static_cast<uint64_t>(idx) << 3) + 0x33ULL;
    const uint64_t inner = fold_values_recursive_inner(values, idx + 1, acc ^ mix);
    return inner ^ (mix + (acc << 1));
}

uint64_t fold_values_recursive(const std::vector<uint64_t>& values) {
    return fold_values_recursive_inner(values, 0, 0xABCDEF1234567890ULL ^ static_cast<uint64_t>(values.size()));
}

uint64_t varargs_capture_expected_hash(const std::vector<uint64_t>& values) {
    uint64_t acc = static_cast<uint64_t>(values.size());
    for (size_t i = 0; i < values.size(); ++i) {
        acc ^= values[i] + (static_cast<uint64_t>(i) << 8);
    }
    return acc;
}

std::string make_varargs_abi_litmus_program() {
    std::ostringstream src;
    src
        << "typedef unsigned long long u64;\n"
        << "typedef __builtin_va_list va_list;\n"
        << "#define va_start(ap, last) __builtin_va_start(ap, last)\n"
        << "#define va_end(ap) __builtin_va_end(ap)\n"
        << "#define va_arg(ap, t) __builtin_va_arg(ap, t)\n"
        << "static volatile u64* const OUT = (volatile u64*)0x3000ULL;\n"
        << "static volatile u64* const PROBE = (volatile u64*)0x3008ULL;\n"
        << "static volatile u64 CURSOR = 0ULL;\n"
        << "__attribute__((noinline)) static u64 capture_args(u64 count, ...) {\n"
        << "  va_list ap;\n"
        << "  va_start(ap, count);\n"
        << "  u64 base = CURSOR;\n"
        << "  CURSOR = base + count;\n"
        << "  u64 acc = count;\n"
        << "  for (u64 i = 0; i < count; ++i) {\n"
        << "    u64 v = va_arg(ap, u64);\n"
        << "    PROBE[base + i] = v;\n"
        << "    acc ^= v + (i << 8);\n"
        << "  }\n"
        << "  va_end(ap);\n"
        << "  return acc;\n"
        << "}\n"
        << "void _start(void) {\n"
        << "  u64 h1 = capture_args(3ULL,\n"
        << "      0x1111111111111111ULL, 0x2222222222222222ULL, 0x3333333333333333ULL);\n"
        << "  u64 h2 = capture_args(6ULL,\n"
        << "      0x4444444444444444ULL, 0x5555555555555555ULL, 0x6666666666666666ULL,\n"
        << "      0x7777777777777777ULL, 0x8888888888888888ULL, 0x9999999999999999ULL);\n"
        << "  u64 h3 = capture_args(9ULL,\n"
        << "      0xAAAAAAAABBBBBBBBULL, 0xCCCCCCCCDDDDDDDDULL, 0xEEEEEEEEFFFFFFFFULL,\n"
        << "      0x1111111122222222ULL, 0x3333333344444444ULL, 0x5555555566666666ULL,\n"
        << "      0x7777777788888888ULL, 0x99999999AAAAAAAALL, 0xBBBBBBBBCCCCCCCCULL);\n"
        << "  *OUT = h1 ^ (h2 << 1) ^ (h3 << 2) ^ PROBE[0] ^ PROBE[3] ^ PROBE[9];\n"
        << "  __asm__ volatile(\"STOP\");\n"
        << "}\n";
    return src.str();
}

std::string make_varargs_heavy_program(uint64_t seed, int rounds) {
    std::ostringstream src;
    src
        << "typedef unsigned long long u64;\n"
        << "typedef __builtin_va_list va_list;\n"
        << "#define va_start(ap, last) __builtin_va_start(ap, last)\n"
        << "#define va_end(ap) __builtin_va_end(ap)\n"
        << "#define va_arg(ap, t) __builtin_va_arg(ap, t)\n"
        << "static volatile u64* const OUT = (volatile u64*)0x3000ULL;\n"
        << "__attribute__((noinline)) static u64 fold_va(u64 count, ...) {\n"
        << "  va_list ap;\n"
        << "  va_start(ap, count);\n"
        << "  u64 acc = 0x1234FEDCBA987654ULL ^ count;\n"
        << "  u64 salt = 0x9E3779B97F4A7C15ULL;\n"
        << "  for (u64 i = 0; i < count; ++i) {\n"
        << "    u64 v = va_arg(ap, u64);\n"
        << "    salt = (salt ^ (salt << 5)) + 0xD1B54A32D192ED03ULL + i;\n"
        << "    acc ^= (v + salt + i);\n"
        << "    acc = (acc << 7) ^ (acc >> 3) ^ (v << (i & 7ULL));\n"
        << "  }\n"
        << "  va_end(ap);\n"
        << "  return acc;\n"
        << "}\n"
        << "void _start(void) {\n"
        << "  volatile u64 a0 = " << (seed + 1ULL) << "ULL;\n"
        << "  volatile u64 a1 = " << (seed + 2ULL) << "ULL;\n"
        << "  volatile u64 a2 = " << (seed + 3ULL) << "ULL;\n"
        << "  volatile u64 a3 = " << (seed + 4ULL) << "ULL;\n"
        << "  volatile u64 a4 = " << (seed + 5ULL) << "ULL;\n"
        << "  volatile u64 a5 = " << (seed + 6ULL) << "ULL;\n"
        << "  volatile u64 a6 = " << (seed + 7ULL) << "ULL;\n"
        << "  volatile u64 a7 = " << (seed + 8ULL) << "ULL;\n"
        << "  volatile u64 a8 = " << (seed + 9ULL) << "ULL;\n"
        << "  volatile u64 a9 = " << (seed + 10ULL) << "ULL;\n"
        << "  volatile u64 a10 = " << (seed + 11ULL) << "ULL;\n"
        << "  volatile u64 a11 = " << (seed + 12ULL) << "ULL;\n";

    for (int round = 0; round < rounds; ++round) {
        src
            << "  {\n"
            << "    const u64 r = " << static_cast<uint64_t>(round) << "ULL;\n"
            << "    u64 p = fold_va(6ULL, a0, a1, a2, a3, a4, a5);\n"
            << "    u64 q = fold_va(6ULL, a6, a7, a8, a9, a10, a11);\n"
            << "    u64 m = fold_va(8ULL, p, q, a0, a3, a6, a9, a11, r);\n"
            << "    u64 n = fold_va(5ULL, m, a2, a5, a8, a10);\n"
            << "    a0 = a0 ^ (p + r);\n"
            << "    a1 = a1 + (q ^ a0);\n"
            << "    a2 = a2 ^ (m + a1);\n"
            << "    a3 = a3 + (n ^ a2);\n"
            << "    a4 = a4 ^ (p + q + r);\n"
            << "    a5 = a5 + (m ^ n);\n"
            << "    a6 = a6 ^ (a0 + a3 + p);\n"
            << "    a7 = a7 + (a2 ^ q);\n"
            << "    a8 = a8 ^ (a4 + m);\n"
            << "    a9 = a9 + (a6 ^ n);\n"
            << "    a10 = a10 ^ (a8 + p + q);\n"
            << "    a11 = a11 + (a10 ^ m ^ n);\n"
            << "  }\n";
    }

    src
        << "  u64 out = fold_va(6ULL, a0, a2, a4, a6, a8, a10) ^ fold_va(6ULL, a1, a3, a5, a7, a9, a11);\n"
        << "  *OUT = out;\n"
        << "  __asm__ volatile(\"STOP\");\n"
        << "}\n";
    return src.str();
}

uint64_t varargs_heavy_expected(uint64_t seed, int rounds) {
    uint64_t a0 = seed + 1ULL;
    uint64_t a1 = seed + 2ULL;
    uint64_t a2 = seed + 3ULL;
    uint64_t a3 = seed + 4ULL;
    uint64_t a4 = seed + 5ULL;
    uint64_t a5 = seed + 6ULL;
    uint64_t a6 = seed + 7ULL;
    uint64_t a7 = seed + 8ULL;
    uint64_t a8 = seed + 9ULL;
    uint64_t a9 = seed + 10ULL;
    uint64_t a10 = seed + 11ULL;
    uint64_t a11 = seed + 12ULL;

    for (uint64_t r = 0; r < static_cast<uint64_t>(rounds); ++r) {
        const uint64_t p = fold_values({a0, a1, a2, a3, a4, a5});
        const uint64_t q = fold_values({a6, a7, a8, a9, a10, a11});
        const uint64_t m = fold_values({p, q, a0, a3, a6, a9, a11, r});
        const uint64_t n = fold_values({m, a2, a5, a8, a10});

        a0 = a0 ^ (p + r);
        a1 = a1 + (q ^ a0);
        a2 = a2 ^ (m + a1);
        a3 = a3 + (n ^ a2);
        a4 = a4 ^ (p + q + r);
        a5 = a5 + (m ^ n);
        a6 = a6 ^ (a0 + a3 + p);
        a7 = a7 + (a2 ^ q);
        a8 = a8 ^ (a4 + m);
        a9 = a9 + (a6 ^ n);
        a10 = a10 ^ (a8 + p + q);
        a11 = a11 + (a10 ^ m ^ n);
    }

    return fold_values({a0, a2, a4, a6, a8, a10})
        ^ fold_values({a1, a3, a5, a7, a9, a11});
}

std::string make_timeout_non_halting_program(uint64_t seed) {
    std::ostringstream src;
    src
        << "typedef unsigned long long u64;\n"
        << "void _start(void) {\n"
        << "  volatile u64 x = " << seed << "ULL;\n"
        << "  for (;;) {\n"
        << "    x = (x << 1) ^ (x >> 3) ^ 0xD00D00D00D00D00DULL;\n"
        << "    x ^= (x << 7);\n"
        << "  }\n"
        << "}\n";
    return src.str();
}

void test_recursive_clang_matrix() {
    const uint64_t seed = 0x1234ULL;
    const uint64_t salt = 0x99ULL;
    const uint64_t depth = 28ULL;
    const uint64_t expected = recursive_expected(seed, salt, depth);
    const std::string source = make_recursive_program(seed, salt, depth);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("recursive clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_recursive_clang_heavy_matrix() {
    const uint64_t seed = 0x726574555553ULL;
    const uint64_t salt = 0xD3ULL;
    const uint64_t depth = 96ULL;
    const uint64_t expected = recursive_expected(seed, salt, depth);
    const std::string source = make_recursive_program(seed, salt, depth);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu, kHeavyMaxCycles)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("deep recursive clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_deep_callstack_clang_matrix() {
    const uint64_t seed = 0x1234567890ULL;
    const int depth = 40;
    const uint64_t expected = deep_call_expected(seed, depth);
    const std::string source = make_deep_call_program(seed, depth);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("deep callstack clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_deep_callstack_clang_heavy_matrix() {
    const uint64_t seed = 0x88112233445566ULL;
    const int depth = 120;
    const uint64_t expected = deep_call_expected(seed, depth);
    const std::string source = make_deep_call_program(seed, depth);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu, kHeavyMaxCycles)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("large call-chain clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_register_pressure_clang_matrix() {
    const uint64_t seed = 0xCAFEBABEULL;
    const int var_count = 24;
    const int rounds = 40;
    const uint64_t expected = register_pressure_expected(seed, var_count, rounds);
    const std::string source = make_register_pressure_program(seed, var_count, rounds);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("register pressure clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_register_pressure_clang_heavy_matrix() {
    const uint64_t seed = 0xA5A55A5A11ULL;
    const int var_count = 40;
    const int rounds = 110;
    const uint64_t expected = register_pressure_expected(seed, var_count, rounds);
    const std::string source = make_register_pressure_program(seed, var_count, rounds);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu, kHeavyMaxCycles)) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("heavy register pressure clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_varargs_clang_heavy_matrix() {
    const uint64_t seed = 0x1111222233334444ULL;
    const int rounds = 2;
    const uint64_t expected = varargs_heavy_expected(seed, rounds);
    const std::string source = make_varargs_heavy_program(seed, rounds);

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu, kVarargsHeavyMaxCycles, "varargs-heavy")) {
            return;
        }

        const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("heavy varargs clang result matches at -O") + opt;
        CHECK_EQ(got, expected, msg.c_str());
    }
}

void test_varargs_abi_litmus_matrix() {
    const std::vector<uint64_t> set1 = {
        0x1111111111111111ULL,
        0x2222222222222222ULL,
        0x3333333333333333ULL,
    };
    const std::vector<uint64_t> set2 = {
        0x4444444444444444ULL,
        0x5555555555555555ULL,
        0x6666666666666666ULL,
        0x7777777777777777ULL,
        0x8888888888888888ULL,
        0x9999999999999999ULL,
    };
    const std::vector<uint64_t> set3 = {
        0xAAAAAAAABBBBBBBBULL,
        0xCCCCCCCCDDDDDDDDULL,
        0xEEEEEEEEFFFFFFFFULL,
        0x1111111122222222ULL,
        0x3333333344444444ULL,
        0x5555555566666666ULL,
        0x7777777788888888ULL,
        0x99999999AAAAAAAALL,
        0xBBBBBBBBCCCCCCCCULL,
    };

    const uint64_t h1 = varargs_capture_expected_hash(set1);
    const uint64_t h2 = varargs_capture_expected_hash(set2);
    const uint64_t h3 = varargs_capture_expected_hash(set3);
    const uint64_t expected_out = h1 ^ (h2 << 1) ^ (h3 << 2) ^ set1[0] ^ set2[0] ^ set3[0];
    const std::string source = make_varargs_abi_litmus_program();

    for (const char* opt : kOptLevels) {
        Little64CPU cpu;
        if (!compile_link_run_c_source(source, opt, cpu, kMaxCycles, "varargs-abi-litmus")) {
            return;
        }

        for (size_t i = 0; i < set1.size(); ++i) {
            const uint64_t got = cpu.getMemoryBus().read64(kVarargsProbeAddr + static_cast<uint64_t>(i) * 8ULL);
            const std::string msg = std::string("varargs litmus set1 index ") + std::to_string(i)
                + " matches at -O" + opt;
            CHECK_EQ(got, set1[i], msg.c_str());
        }

        for (size_t i = 0; i < set2.size(); ++i) {
            const uint64_t slot = 3ULL + static_cast<uint64_t>(i);
            const uint64_t got = cpu.getMemoryBus().read64(kVarargsProbeAddr + slot * 8ULL);
            const std::string msg = std::string("varargs litmus set2 index ") + std::to_string(i)
                + " matches at -O" + opt;
            CHECK_EQ(got, set2[i], msg.c_str());
        }

        for (size_t i = 0; i < set3.size(); ++i) {
            const uint64_t slot = 9ULL + static_cast<uint64_t>(i);
            const uint64_t got = cpu.getMemoryBus().read64(kVarargsProbeAddr + slot * 8ULL);
            const std::string msg = std::string("varargs litmus set3 index ") + std::to_string(i)
                + " matches at -O" + opt;
            CHECK_EQ(got, set3[i], msg.c_str());
        }

        const uint64_t out = cpu.getMemoryBus().read64(kResultAddr);
        std::string msg = std::string("varargs litmus checksum matches at -O") + opt;
        CHECK_EQ(out, expected_out, msg.c_str());
    }
}

void test_timeout_guard_matrix() {
    const std::string source = make_timeout_non_halting_program(0x123456789ABCDEF0ULL);

    for (const char* opt : kOptLevels) {
        const bool timed_out = compile_link_expect_timeout(source, opt, 6000);
        std::string msg = std::string("timeout guard trips for non-halting workload at -O") + opt;
        CHECK_TRUE(timed_out, msg.c_str());
    }
}

void run_soak_workload(const char* workload_name,
                       const std::string& source,
                       uint64_t expected,
                       int max_cycles) {
    for (const char* opt : kOptLevels) {
        std::vector<uint16_t> words;
        if (!compile_link_source_words(source, opt, words)) {
            return;
        }

        uint64_t first_run_value = 0;

        for (int run = 0; run < kSoakRuns; ++run) {
            Little64CPU cpu;
            bool timed_out = false;
            if (!run_program_words(words, opt, cpu, max_cycles, timed_out)) {
                return;
            }

            if (timed_out) {
                std::fprintf(stderr,
                             "Soak workload %s timed out at -O%s run %d (PC=0x%016llx)\n",
                             workload_name,
                             opt,
                             run + 1,
                             static_cast<unsigned long long>(cpu.registers.regs[15]));
                CHECK_TRUE(false, "Soak workload should halt");
                return;
            }

            const uint64_t got = cpu.getMemoryBus().read64(kResultAddr);
            {
                std::string msg = std::string("soak expected result ") + workload_name
                    + " -O" + opt + " run " + std::to_string(run + 1);
                CHECK_EQ(got, expected, msg.c_str());
            }

            if (run == 0) {
                first_run_value = got;
            } else {
                std::string msg = std::string("soak deterministic result ") + workload_name
                    + " -O" + opt + " run " + std::to_string(run + 1);
                CHECK_EQ(got, first_run_value, msg.c_str());
            }
        }
    }
}

void test_soak_runtime_stability_matrix() {
    const uint64_t recursive_seed = 0x726574555553ULL;
    const uint64_t recursive_salt = 0xD3ULL;
    const uint64_t recursive_depth = 96ULL;
    const std::string recursive_source = make_recursive_program(recursive_seed, recursive_salt, recursive_depth);
    const uint64_t recursive_expected_value = recursive_expected(recursive_seed, recursive_salt, recursive_depth);

    const uint64_t deep_call_seed = 0x88112233445566ULL;
    const int deep_call_depth = 120;
    const std::string deep_call_source = make_deep_call_program(deep_call_seed, deep_call_depth);
    const uint64_t deep_call_expected_value = deep_call_expected(deep_call_seed, deep_call_depth);

    const uint64_t pressure_seed = 0xA5A55A5A11ULL;
    const int pressure_var_count = 40;
    const int pressure_rounds = 110;
    const std::string pressure_source = make_register_pressure_program(pressure_seed, pressure_var_count, pressure_rounds);
    const uint64_t pressure_expected_value = register_pressure_expected(pressure_seed, pressure_var_count, pressure_rounds);

    run_soak_workload("recursive", recursive_source, recursive_expected_value, kHeavyMaxCycles);
    run_soak_workload("deep-call", deep_call_source, deep_call_expected_value, kHeavyMaxCycles);
    run_soak_workload("register-pressure", pressure_source, pressure_expected_value, kHeavyMaxCycles);
}

} // namespace

int main() {
    std::printf("=== Little-64 clang runtime stress tests ===\n\n");
    std::printf("Recursive workloads\n");
    test_recursive_clang_matrix();
    std::printf("Deep recursive workloads\n");
    test_recursive_clang_heavy_matrix();

    std::printf("Deep non-recursive call stack workloads\n");
    test_deep_callstack_clang_matrix();
    std::printf("Large non-recursive call stack workloads\n");
    test_deep_callstack_clang_heavy_matrix();

    std::printf("Register pressure and spill workloads\n");
    test_register_pressure_clang_matrix();
    std::printf("Heavy register pressure and spill workloads\n");
    test_register_pressure_clang_heavy_matrix();

    std::printf("Heavy variable-argument workloads\n");
    test_varargs_clang_heavy_matrix();
    std::printf("Varargs ABI litmus workloads\n");
    test_varargs_abi_litmus_matrix();

    std::printf("Timeout guard workloads\n");
    test_timeout_guard_matrix();

    std::printf("Soak stability workloads\n");
    test_soak_runtime_stability_matrix();

    return print_summary();
}
