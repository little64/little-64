; Little-64 test program — demonstrates all four instruction formats
        .org 0x0000

start:
        ; Format 10 (LDI): build a 32-bit value in R1 using shift-OR
        LDI    #0x01, R1        ; R1 = 0x01 (clears R1 first, then loads)
        LDI.S1 #0x02, R1       ; R1 = 0x0201 (OR 0x02 << 8)
        LDI.S2 #0x03, R1       ; R1 = 0x030201
        LDI.S3 #0x04, R1       ; R1 = 0x04030201

        ; Format 10 (LDI): load a simple immediate
        LDI    #10, R2

        ; Format 11 (GP ALU)
        ADD    R1, R2           ; R2 = R2 + R1
        SUB    R2, R1           ; R1 = R1 - R2
        AND    R2, R1           ; R1 = R1 & R2
        OR     R2, R1           ; R1 = R1 | R2
        TEST   R2, R1           ; set flags based on R1 - R2, no store

        ; Format 01 (LS PC-Relative): load from a data label
        LOAD   @data, R3        ; R3 = MEM64[PC-rel to data]

        ; Format 00 (LS Register): load and store with offset
        LOAD   [R3], R4         ; R4 = MEM64[R3 + 0]
        LOAD   [R3+2], R5       ; R5 = MEM64[R3 + 2]
        STORE  [R3+4], R4       ; MEM64[R3 + 4] = R4

        ; Byte and short width variants
        BYTE_LOAD  [R3], R6     ; R6 = (uint8_t) MEM8[R3]
        SHORT_LOAD [R3+2], R7   ; R7 = (uint16_t) MEM16[R3 + 2]

        ; Conditional jump (Format 01): JUMP.Z branches to loop if zero flag set
        TEST   R2, R2           ; set zero flag if R2 == 0
        JUMP.Z @loop            ; branch to loop if zero (Rd = R15 inferred)

        ; Unconditional move of a PC-relative address into R15 (acts as an unconditional jump)
        MOVE   @start, R15

loop:
        ; Format 00 (INC_LOAD / DEC_STORE): stack-style operations
        INC_LOAD  [R13], R8    ; R8 = MEM64[R13]; R13 += 8
        DEC_STORE [R13], R8    ; R13 -= 8; MEM64[R13] = R8

        ; JUMP.* bare register form (Format 00): conditional branch via register
        JUMP.Z R14              ; if Z, PC = R14 (branch to address in link register)
        JUMP.Z R14, R1          ; if Z, R1 = R14 (conditional move, not a branch)

        STOP                    ; halt execution
data:
        .word 0xBEEF
        .word 0xDEAD
