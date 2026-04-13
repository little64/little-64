.global _start

	.section .text
_start:
	LDI	#1, R10
	LDI64	hello_msg, R9
	LDI	#48, R8
	LDI	#64, R4
	SYSCALL

yield_forever:
	LDI	#124, R4
	SYSCALL
	JUMP	@yield_forever

	.section .rodata
hello_msg:
	.ascii	"hello from little64 test init via single write\n"

.section .note.GNU-stack,"",@progbits