.section .text
.global _start
.type _start, @function

_start:
	LDI64 _fstack, R13

	LDI64 _fdata_rom, R1
	LDI64 _fdata, R2
	LDI64 _edata, R3
	LDI #8, R5

.copy_data:
	MOVE R3, R12
	SUB R2, R12
	TEST R0, R12
	JUMP.Z @.clear_bss
	LOAD [R1], R4
	STORE [R2], R4
	ADD R5, R1
	ADD R5, R2
	JUMP @.copy_data

.clear_bss:
	LDI64 _fbss, R1
	LDI64 _ebss, R3
	LDI #0, R4

.clear_bss_loop:
	MOVE R3, R12
	SUB R1, R12
	TEST R0, R12
	JUMP.Z @.setup_irq_table
	STORE [R1], R4
	ADD R5, R1
	JUMP @.clear_bss_loop

/* Fill _irq_table (in BSS, just zeroed) with the address of _isr_entry so
 * that any interrupt or exception vector has a valid handler.  Then write
 * the table base address into special register 16 (interrupt_table_base).
 * R5=8 is still live from the BSS clear loop. */
.setup_irq_table:
	LDI64 _irq_table, R1
	LDI64 _isr_entry, R2
	LDI #128, R3
	LDI #1, R6

.fill_irq_table:
	TEST R0, R3
	JUMP.Z @.irq_table_done
	STORE [R1], R2
	ADD R5, R1
	SUB R6, R3
	JUMP @.fill_irq_table

.irq_table_done:
	LDI64 _irq_table, R1
	LDI #16, R2
	SSR R2, R1

.call_main:
	LDI #0, R10
	LDI #0, R9
	LDI64 main, R1
	MOVE R15, R14+2
	MOVE R1, R15

.halt:
	STOP
	JUMP @.halt

/* _isr_entry — interrupt and exception handler trampoline.
 *
 * The CPU jumps here for every vector (all 128 slots in _irq_table point
 * here).  Save every caller-saved GPR (R1-R12, R14), dispatch to the C
 * isr() function, restore them, then IRET.  R13 (stack pointer) is
 * managed implicitly: the 13 PUSHes are exactly balanced by 13 POPs. */
.global _isr_entry
.type _isr_entry, @function
_isr_entry:
	PUSH R1
	PUSH R2
	PUSH R3
	PUSH R4
	PUSH R5
	PUSH R6
	PUSH R7
	PUSH R8
	PUSH R9
	PUSH R10
	PUSH R11
	PUSH R12
	PUSH R14
	JUMP	@+4
	.quad	isr
	LOAD	@-5, R1
	MOVE	R15, R14+2
	MOVE	R1, R15
	POP	R14
	POP	R12
	POP	R11
	POP	R10
	POP	R9
	POP	R8
	POP	R7
	POP	R6
	POP	R5
	POP	R4
	POP	R3
	POP	R2
	POP	R1
	IRET

.section .bss
.global _irq_table
.align 8
_irq_table:
	.fill 128, 8, 0

.section .note.GNU-stack,"",@progbits