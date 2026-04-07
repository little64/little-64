// CHECK_STDOUT: Hello from Little-64!

#define SERIAL_BASE ((volatile unsigned char *)0xFFFFFFFFFFFF0000ULL)

void print(const char *s) {
    while (*s) {
        *SERIAL_BASE = *s++;
    }
}

__attribute__((naked))
void _start(void) {
    // Basic setup: R13 = SP = 0x4000000
    __asm__ volatile (
        "LDI #0, R13\n\t"
        "LDI.S1 #0, R13\n\t"
        "LDI.S2 #0, R13\n\t"
        "LDI.S3 #4, R13\n\t"
        "LDI64 main, R1\n\t"
        "MOVE R1, PC"
    );
}

int main() {
    print("Hello from Little-64!");
    __asm__ volatile ("STOP");
    return 0;
}
