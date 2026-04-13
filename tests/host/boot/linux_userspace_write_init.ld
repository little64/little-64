ENTRY(_start)

PHDRS {
    text PT_LOAD FLAGS(5);
    stack PT_GNU_STACK FLAGS(6);
}

SECTIONS {
    . = 0x10000;

    .text : {
        *(.text*)
        *(.rodata*)
    } :text

    /DISCARD/ : {
        *(.comment)
        *(.note*)
        *(.eh_frame*)
        *(.llvm*)
    }
}