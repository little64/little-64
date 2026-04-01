; Tests core ALU operations
; CHECK_REG: R1 = 0x42
; CHECK_REG: R2 = 0x100
; CHECK_REG: R3 = 0xBE
; CHECK_REG: R4 = 0x1

.text
.global _start
_start:
    LDI #0x42, R1
    LDI #0x1, R2
    LDI.S1 #0x1, R2     ; R2 = 0x101
    LDI #1, R11         ; R11 = 1
    SUB R11, R2         ; R2 = 0x100
    
    LDI #0xFE, R3
    LDI #0x40, R12
    SUB R12, R3         ; R3 = 0xBE
    
    LDI #0, R4
    LDI #0x42, R13
    TEST R13, R1        ; R1 is 0x42, so Z flag should be 1? Wait, TEST in Little64 is comparison.
    JUMP.Z @target
    STOP
target:
    LDI #1, R4
    STOP
