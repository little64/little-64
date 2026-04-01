// CHECK_REG: R5 = 0x5
// Fibonacci test (iterative) to check loops, arithmetic, and calling convention

long fib(long n) {
    long a = 0;
    long b = 1;
    while (n > 0) {
        long next = a + b;
        a = b;
        b = next;
        --n;
    }
    return a;
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
