; Tests LDI64 relocation with external symbol
; CHECK_REG: R2 = 0x1234

.text
.global _start
_start:
    LDI64 #message, R1
    LOAD [R1], R2
    STOP

.data
message:
    .quad 0x1234
