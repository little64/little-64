; Little-64 test program
        .org 0x0000

start:
        LOAD    #2, R1          ; Load from address 2, shift=0
        LOAD.S1 #1, R2          ; Load from address 256 (1 << 8), shift=1
        LOAD[BW] @table, R3     ; Load with mask=BW (both bytes) from PC-relative address
        STORE[B] @data, R4      ; Store with mask=B (low byte) to PC-relative address

loop:
        STORE   #10, R5         ; Store to address 10, shift=0
        DEC_STORE.S2 #1, R6     ; Decrement and store to address 65536 (1 << 16), shift=2

data:
        .word 0xABCD

table:
        .word 0x1234
        .word 0x5678
