.org 0x0000

	JUMP @start

_stack_base:
.long 0x4000000

start:
	LD @_stack_base, R13
	MOVE @hello_world, R10
	; Call with link
	JAL @serial_print
	STOP

hello_world:
.asciiz "Hello, world!"

_serial_base:
.long 0xFFFFFFFFFFFF0000

; Prints the null-terminated string at R11 into the serial device at R10.
serial_print:
	PUSH R10
	PUSH R9
	
	LOAD @_serial_base, R9 ; Load the pointer to the serial device
	LD #1, R3
	_loop:
	LD.B [R10], R2 ; Read the current char byte
	TEST R2, R0 ; Test if it is zero
	JUMP.Z @_exit ; Return if it is zero
	ST.B [R9], R2 ; Write it to serial
	ADD R3, R10
	JUMP @_loop
	
	_exit:
	POP R9
	POP R10
	RET


