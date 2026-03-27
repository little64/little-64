; Hello project — main module
;
; Calls double_it from utils.asm, which computes R2 = R1 * 2.
; After return: R1 = 42, R2 = 84.
;
; EXPECT R1 = 42
; EXPECT R2 = 84

.global start
.extern double_it

start:
    LDI #42, R1
    JAL @double_it
    STOP

