#include <picolibc.h>

# setjmp/longjmp for Little64.
# Preserves LR (R14), FP (R11), and SP (R13).

.global setjmp
.type setjmp, @function
setjmp:
	# R10 = jmp_buf*
	STORE [R10], R14
	STORE [R10+2], R11
	STORE [R10+4], R13
	LDI #0, R1
	MOVE R14, PC

.global longjmp
.type longjmp, @function
longjmp:
	# R10 = jmp_buf*, R9 = return value
	LOAD [R10], R14
	LOAD [R10+2], R11
	LOAD [R10+4], R13

	# longjmp must not return 0.
	MOVE R9, R1
	TEST R0, R1
	JUMP.Z @1f
	MOVE R14, PC
1:
	LDI #1, R1
	MOVE R14, PC
