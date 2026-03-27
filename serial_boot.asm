.org 0x0000

	JUMP @start

_serial_base:
.long 0xFFFFFFFFFFFF0000

start:
	LOAD @_serial_base, R10
	MOVE @hello_world, R11
	; Call with link
	MOVE [R15+2], R14
	JUMP @serial_print
	STOP

hello_world:
.asciiz "Hello, world!"

; Prints the null-terminated string at R11 into the serial device at R10.
serial_print:
	MOVE [R11], R1 ; Copy the pointer
	LDI #1, R3
	_loop:
	BYTE_LOAD [R1], R2 ; Read the current char byte
	TEST R2, R0 ; Test if it is zero
	JUMP.Z @_exit ; Return if it is zero
	BYTE_STORE [R10], R2 ; Write it to serial
	ADD R3, R1
	JUMP @_loop
	
	_exit:
	MOVE [R14], R15 ; Return
