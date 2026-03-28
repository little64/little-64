/*
 * Little-64 Backend for vbcc
 *
 * Instruction selector and code generator.
 * This file implements the core compilation logic: translating vbcc's IR to
 * Little-64 assembly code.
 *
 * SKELETON: This is the starting point for Phase 1. Implement:
 * - Function prologue/epilogue generation
 * - Register allocation strategy
 * - Basic instruction emission (initially NOP/placeholder)
 * - Address mode handling
 */

#include "cc.h"      /* vbcc core definitions */
#include "machine.h" /* Target machine configuration */

/* ========================================================================
 * Code Generation State
 * ======================================================================== */

/* Current function being compiled */
static struct Var *current_function;

/* Stack frame offset (grows upward; current offset from SP) */
static long stack_offset;

/* ========================================================================
 * Helper Functions
 * ======================================================================== */

/*
 * emit_instruction - Emit a single 16-bit instruction
 *
 * This is a placeholder. In Phase 2, this will be replaced with proper
 * instruction encoding.
 */
static void emit_instruction(const char *mnemonic, const char *operands) {
    printf("    %s %s\n", mnemonic, operands ? operands : "");
}

/*
 * get_register_name - Return the name of a register by number
 */
static const char *get_register_name(int reg) {
    static const char *names[] = {
        "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7",
        "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"
    };
    if (reg >= 0 && reg < 16)
        return names[reg];
    return "???";
}

/* ========================================================================
 * Stack Frame Management
 * ======================================================================== */

/*
 * enter_function - Initialize code generation for a function
 *
 * Emits function prologue: save callee-saved registers, allocate stack space.
 */
static void enter_function(struct Var *func) {
    current_function = func;
    stack_offset = 0;

    /* Prologue */
    printf("%s:\n", func->identifier);

    /* TODO Phase 1: Emit prologue
     * - Save callee-saved registers that are used (R6–R12, R14)
     * - Allocate stack space for local variables
     * - For now, emit placeholder
     */
    emit_instruction("NOP", "# Prologue placeholder");
}

/*
 * leave_function - Finalize code generation for a function
 *
 * Emits function epilogue: restore callee-saved registers, deallocate stack.
 */
static void leave_function(struct Var *func) {
    /* Epilogue */
    /* TODO Phase 1: Emit epilogue
     * - Restore callee-saved registers
     * - Deallocate stack space
     * - Return (RET pseudo-instruction)
     * - For now, emit placeholder
     */
    emit_instruction("RET", "");
    printf("\n");
}

/* ========================================================================
 * Instruction Emission (Placeholder)
 * ======================================================================== */

/*
 * gen_code - Main code generation entry point
 *
 * vbcc calls this for each statement/expression in the function.
 * This is where the real instruction selection happens.
 *
 * SKELETON: Currently emits NOP. In Phase 2, implement:
 * - Load/store operations
 * - Arithmetic operations
 * - Branch generation
 * - Function calls
 */
static void gen_code(struct IC *ic) {
    /* TODO Phase 2: Real instruction selection
     * - Pattern match on ic->code (operation type)
     * - Allocate registers for operands
     * - Emit appropriate Little-64 instruction(s)
     * - Handle immediate values (via LDI64 if needed)
     * - Update stack_offset for local variables
     */
    emit_instruction("NOP", "# Code generation placeholder");
}

/* ========================================================================
 * External Functions (Required by vbcc Backend Interface)
 * ======================================================================== */

/*
 * init_machine - Initialize machine backend
 *
 * Called once at compiler startup. Set up any global state, register names, etc.
 */
void init_machine(void) {
    /* TODO: Register any machine-specific options, target names, etc. */
}

/*
 * gen_function - Generate code for one function
 *
 * vbcc calls this once per function definition.
 * Coordinates prologue, code generation, and epilogue.
 */
void gen_function(struct Var *func, FILE *out) {
    enter_function(func);

    /* Generate code for function body
     * TODO: Iterate through function's IR and call gen_code for each statement
     */

    leave_function(func);
}

/*
 * gen_globals - Generate code/data for global variables
 *
 * Called for global variable definitions and initialization.
 */
void gen_globals(struct SymbolList *syms, FILE *out) {
    /* TODO: Emit data section with global variable initializers */
}

/*
 * target_specific_init - Target-specific initialization
 *
 * Called during compiler initialization. Set up target-specific data structures.
 */
void target_specific_init(void) {
    /* TODO: Initialize target-specific options, sizes, offsets */
}

/*
 * get_abi_regparam - Get the register for a function parameter
 *
 * vbcc calls this to determine which register to use for function arguments.
 * Maps argument indices to R10–R6.
 */
int get_abi_regparam(int arg_index) {
    /* Arguments 0–4: R10, R9, R8, R7, R6 */
    static const int arg_regs[] = {10, 9, 8, 7, 6};
    if (arg_index >= 0 && arg_index < 5)
        return arg_regs[arg_index];
    return -1; /* Stack-based argument */
}

/*
 * get_abi_return_register - Get the register for return value
 *
 * vbcc calls this to determine where function return values are placed.
 */
int get_abi_return_register(struct Type *return_type) {
    /* Single return value: R1 */
    return 1;
}

/*
 * gen_inline_asm - Generate inline assembly
 *
 * If vbcc supports inline assembly, emit it directly to output.
 * TODO: Implement if needed in Phase 5.
 */
void gen_inline_asm(const char *asm_code, FILE *out) {
    fprintf(out, "%s\n", asm_code);
}

/* ========================================================================
 * Register Allocation Stubs
 * ======================================================================== */

/*
 * These functions are called by vbcc's register allocator.
 * Provide Little-64 specific allocation strategy.
 * TODO: Implement in Phase 1/2.
 */

int allocate_register(struct IC *ic) {
    /* TODO: Choose a register for this value */
    return 1; /* Placeholder: always use R1 */
}

void free_register(int reg) {
    /* TODO: Mark register as free for reallocation */
}

void spill_register(int reg) {
    /* TODO: Save register contents to stack */
}

void restore_register(int reg) {
    /* TODO: Restore register contents from stack */
}

/* ========================================================================
 * End of Skeleton
 * ======================================================================== */

/*
 * Next Steps (Phases):
 *
 * Phase 1:
 *   - Flesh out enter_function() and leave_function()
 *   - Implement register allocation strategy
 *   - Make sure compiled code builds and links
 *
 * Phase 2:
 *   - Implement gen_code() with real instruction selection
 *   - Handle load/store, arithmetic, branches, calls
 *
 * Phase 3:
 *   - Add libcall stubs for __muldi3, __divdi3, etc.
 *
 * Phase 4+:
 *   - Optimize, validate, test on emulator
 */
