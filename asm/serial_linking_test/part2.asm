.global serial_print

_serial_base:
.long 0xFFFFFFFFFFFF0000

serial_print:
	PUSH R10
	PUSH R9

	LOAD @_serial_base, R9
	LD #1, R3

_loop:
	LD.B [R10], R2
	TEST R2, R0
	JUMP.Z @_exit
	ST.B [R9], R2
	ADD R3, R10
	JUMP @_loop

_exit:
	POP R9
	POP R10
	RET
