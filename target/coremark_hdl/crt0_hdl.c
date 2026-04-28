/* crt0_hdl.c — Minimal bare-metal entry point for the Little-64 HDL harness.
 *
 * The stack pointer (R13) is seeded by run_elf_flat() in the Python test
 * harness before simulation begins.  BSS is zeroed by _load_elf_flat() before
 * the simulation starts, so no BSS-clearing loop is needed here.
 */

extern int main(int argc, char *argv[]);

void __attribute__((section(".text.boot"), noreturn)) _start(void) {
    main(0, (void *)0);
    __asm__ volatile("STOP");
    __builtin_unreachable();
}
