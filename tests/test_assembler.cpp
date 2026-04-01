#include "llvm_assembler.hpp"
#include "linker.hpp"
#include "support/test_harness.hpp"
#include <cstdint>
#include <string>

static void test_llvm_assembler_emits_object() {
    std::string error;
    auto obj = LLVMAssembler::assembleSourceText(
        ".global start\n"
        "start:\n"
        "  STOP\n",
        "emit_object.asm",
        error);

    CHECK_TRUE(static_cast<bool>(obj), "llvm assembler emits an object for valid source");
    if (!obj) return;

    CHECK_TRUE(obj->size() >= 4, "object has minimum ELF header bytes");
    if (obj->size() < 4) return;

    CHECK_EQ((*obj)[0], static_cast<uint8_t>(0x7F), "ELF magic 0");
    CHECK_EQ((*obj)[1], static_cast<uint8_t>('E'), "ELF magic 1");
    CHECK_EQ((*obj)[2], static_cast<uint8_t>('L'), "ELF magic 2");
    CHECK_EQ((*obj)[3], static_cast<uint8_t>('F'), "ELF magic 3");
}

static void test_llvm_assembler_reports_errors() {
    std::string error;
    auto obj = LLVMAssembler::assembleSourceText(
        "THIS_IS_NOT_A_VALID_OPCODE\n",
        "invalid.asm",
        error);

    CHECK_TRUE(!obj.has_value(), "invalid source should fail assembly");
    CHECK_TRUE(!error.empty(), "invalid source should return diagnostics");
}

static void test_llvm_assembled_object_links_to_words() {
    std::string error;
    auto obj = LLVMAssembler::assembleSourceText(
        "STOP\n"
        "STOP\n",
        "link_words.asm",
        error);

    CHECK_TRUE(static_cast<bool>(obj), "valid source assembles before linking");
    if (!obj) return;

    LinkError link_error;
    auto words = Linker::linkObjects({*obj}, &link_error);
    CHECK_TRUE(static_cast<bool>(words), "single object links into flat word image");
    if (!words) return;

    CHECK_TRUE(words->size() >= 2, "linked image has expected instruction count");
    if (words->size() < 2) return;

    CHECK_EQ((*words)[0], static_cast<uint16_t>(0xDF00), "first word is STOP");
    CHECK_EQ((*words)[1], static_cast<uint16_t>(0xDF00), "second word is STOP");
}

int main() {
    test_llvm_assembler_emits_object();
    test_llvm_assembler_reports_errors();
    test_llvm_assembled_object_links_to_words();
    return print_summary();
}
