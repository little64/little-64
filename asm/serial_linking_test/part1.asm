.org 0x0000

.global start
.extern serial_print

JUMP @start

_stack_base:
.long 0x4000000

start:
	LD @_stack_base, R13
	MOVE @hello_world, R10
	; Call serial_print via JAL pseudo
	JAL @serial_print
	STOP

hello_world:
.asciiz "Hello, world!"

