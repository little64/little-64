// CHECK_REG: R5 = 0x5
// Simple addition test to verify function calls and returns

int add(int a, int b) {
    return a + b;
}

__attribute__((naked))
void _start(void) {
    __asm__ volatile (
        "LDI #0, R13\n\t"
        "LDI.S1 #0, R13\n\t"
        "LDI.S2 #0, R13\n\t"
        "LDI.S3 #4, R13\n\t"
        "LDI64 #main, R1\n\t"
        "MOVE R1, PC"
    );
}

int main() {
    int res = add(2, 3);
    __asm__ volatile (
        "MOVE %0, R5\n\t"
        "STOP"
        : : "r"(res) : "R5"
    );
    return 0;
}
