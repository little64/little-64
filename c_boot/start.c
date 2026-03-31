// start.c

#define SERIAL_BASE ((volatile unsigned char *)0xFFFFFFFFFFFF0000ULL)

static const char message[] = "GHello, world!";

__attribute__((naked))
void _start(void) {
    // Initialize stack pointer to 0x4000000
    // And jump to work() using LDI64 pseudo
    __asm__ volatile (
        "LDI #0, R13\n"
        "LDI.S1 #0, R13\n"
        "LDI.S2 #0, R13\n"
        "LDI.S3 #4, R13\n"
        "LDI64 #work, R1\n"
        "MOVE R1, PC"
    );
}


void work(void) {
    const unsigned char *p = (const unsigned char *)message;
    while (*p) {
        *SERIAL_BASE = *p;
        p++;
    }
    __asm__ volatile ("STOP");
}



