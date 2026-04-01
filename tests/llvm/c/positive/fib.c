// CHECK_REG: R5 = 0x5
// Fibonacci test to check recursion and stack management

long fib(long n) {
    if (n < 2) return n;
    return fib(n-1) + fib(n-2);
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
    long res = fib(5);
    __asm__ volatile (
        "MOVE %0, R5\n\t"
        "STOP"
        : : "r"(res) : "R5"
    );
    return 0;
}
