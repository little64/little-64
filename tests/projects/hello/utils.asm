; Hello project — utility module
;
; double_it: computes R2 = R1 + R1 (R1 is left unchanged)

.global double_it

double_it:
    ADD R1, R2    ; R2 = R2 + R1 = 0 + 42 = 42
    ADD R1, R2    ; R2 = R2 + R1 = 42 + 42 = 84
    RET

