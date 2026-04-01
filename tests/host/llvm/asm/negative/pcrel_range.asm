; Tests out-of-range PC-relative jump
; SHOULD_FAIL: PC-relative offset out of range

.text
.global _start
_start:
    JUMP.Z @target
    STOP

.space 3000

target:
    STOP
