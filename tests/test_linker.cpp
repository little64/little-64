#include "linker.hpp"
#include "assembler.hpp"
#include <cstdio>
#include <string>
#include <vector>

#define CHECK_EQ(actual, expected, msg) \
    do { \
        auto _a = (actual); \
        auto _e = (expected); \
        if (_a == _e) { \
            ; \
        } else { \
            std::fprintf(stderr, "FAIL [%s:%d] %s (expected %d, got %d)\n", __FILE__, __LINE__, (msg), (int)_e, (int)_a); \
            return 1; \
        } \
    } while (0)

int main() {
    Assembler asmbl;

    auto obj1 = asmbl.assembleElf(".global start\nstart: STOP\n");
    auto obj2 = asmbl.assembleElf(".extern start\nJAL @start\n");

    LinkError err;
    auto linked = Linker::linkObjects({obj1, obj2}, &err);
    if (!linked) {
        std::fprintf(stderr, "Link failed: %s\n", err.message.c_str());
        return 1;
    }

    // Check that linked output is non-empty and begins with a jump by comparing first instruction
    CHECK_EQ(linked->size() > 0, true, "Linked output exists");

    // first object is start: STOP (0xFF00), second object has JAL @start (two instr: MOVE + JUMP)
    CHECK_EQ((*linked)[0], (uint16_t)0xFF00, "First word is STOP from start");
    // The JUMP part of JAL is the third word (index 2) in final output.
    // Resolves to target=0 from instruction at byte offset 4 => rel=-3 -> 0x53DF.
    CHECK_EQ((*linked)[2], (uint16_t)0x53DF, "Third word is JAL to start with resolved PCREL6");

    return 0;
}
