.org 0x0000

; ─────────────────────────────────────────────────────────────────────────────
; Interrupt example
;
; Sets up a handler for interrupt 63, enables interrupts, then busy-waits.
; Press "Fire Interrupt (63)" in the Control Panel to trigger the handler,
; which writes "INT\n" to the serial port and returns via IRET.
;
; Memory layout:
;   0x0000 – 0x01FF  Setup code + spin loop
;   0x0200 – 0x03F7  Interrupt table entries 0–62 (null, ROM zero-filled)
;   0x03F8 – 0x03FF  Interrupt table entry 63 → handler address (0x0400)
;   0x0400 – …       Interrupt 63 handler
; ─────────────────────────────────────────────────────────────────────────────

start:
    ; ── Set interrupt_table_base (SR 1) = 0x0200 ──────────────────────────────
    LDI.S0 0,   R1         ; R1  = 0x0000 (clear)
    LDI.S1 2,   R1         ; R1 |= 0x0200  →  R1 = 0x0200
    LDI.S0 1,   R2         ; R2  = 1 (SR index: interrupt_table_base)
    SSR R2, R1             ; SR[1] = 0x0200

    ; ── Build mask = 1 << 63, set interrupt_mask (SR 2) ──────────────────────
    LDI.S0 1,   R3         ; R3  = 1
    LDI.S0 63,  R4         ; R4  = 63 (shift amount)
    SLL R4, R3             ; R3  = 1 << 63
    LDI.S0 2,   R2         ; R2  = 2 (SR index: interrupt_mask)
    SSR R2, R3             ; SR[2] = 1<<63  (unmask interrupt 63 only)

    ; ── Enable interrupts: cpu_control (SR 0) |= 1 ───────────────────────────
    LDI.S0 0,   R2         ; R2  = 0 (SR index: cpu_control)
    LSR R2, R1             ; R1  = cpu_control (currently 0 after reset)
    LDI.S0 1,   R5         ; R5  = 1 (interrupt-enable bit)
    OR  R5, R1             ; R1 |= 1
    SSR R2, R1             ; SR[0] = R1 (interrupts enabled)

spin:
    JUMP @spin             ; busy-wait; handler will fire on button press

; ─────────────────────────────────────────────────────────────────────────────
; Interrupt handler table (64 × 8 bytes)
;
; Entries 0–62 are null (the ROM is zero-filled by loadProgram).
; Entry 63 sits at offset 63*8 = 504 = 0x01F8 from the table base (0x0200),
; so its absolute address is 0x03F8.
; ─────────────────────────────────────────────────────────────────────────────
.org 0x03F8
.long 0x0400               ; entry 63: jump to handler at 0x0400

; ─────────────────────────────────────────────────────────────────────────────
; Interrupt 63 handler
; ─────────────────────────────────────────────────────────────────────────────
.org 0x0400

handler:
    ; ── Clear bit 63 in interrupt_states (SR 3) ──────────────────────────────
    ; Required before IRET; otherwise the interrupt re-fires immediately.
    LDI.S0 3,   R1         ; R1  = 3 (SR index: interrupt_states)
    LSR R1, R2             ; R2  = interrupt_states
    LDI.S0 1,   R3
    LDI.S0 63,  R4
    SLL R4, R3             ; R3  = 1 << 63
    XOR R3, R2             ; R2 ^= (1<<63)  — clears the pending bit
    SSR R1, R2             ; SR[3] = R2

    ; ── Load serial base address ──────────────────────────────────────────────
    LOAD @_serial_base, R9 ; R9  = 0xFFFFFFFFFFFF0000

    ; ── Write "INT\n" ─────────────────────────────────────────────────────────
    LDI.S0 73,  R1         ; 'I'
    ST.B [R9], R1
    LDI.S0 78,  R1         ; 'N'
    ST.B [R9], R1
    LDI.S0 84,  R1         ; 'T'
    ST.B [R9], R1
    LDI.S0 10,  R1         ; '\n'
    ST.B [R9], R1

    IRET

_serial_base:
.long 0xFFFFFFFFFFFF0000
