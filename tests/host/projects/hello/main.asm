; Hello project — main module
;
; Jumps to double_it in utils.asm, which computes R2 = R1 * 2,
; then jumps back to done.
; Final state: R1 = 42, R2 = 84.
;
; EXPECT R1 = 42
; EXPECT R2 = 84

.global start
.global done
.extern double_it

start:
    LDI #42, R1
    JUMP @double_it

done:
    STOP

