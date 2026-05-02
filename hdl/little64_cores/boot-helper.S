.section .text, "ax", @progbits
.global boot_helper
boot_helper:
	MOVE R10, R1
	MOVE R9, R2
	MOVE R8, R3
	TEST R0, R2
	JUMP.Z @no_stack_override
	MOVE R2, R13
no_stack_override:
	MOVE R7, R15