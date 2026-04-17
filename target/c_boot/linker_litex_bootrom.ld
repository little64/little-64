ENTRY(_start)

MEMORY
{
  ROM (rx)  : ORIGIN = 0x0000000000000000, LENGTH = 0x00008000
  RAM (rwx) : ORIGIN = 0x0000000010000000, LENGTH = 0x00004000
}

SECTIONS
{
  .text : ALIGN(16) {
    *(.text.boot)
    *(.text .text.*)
  } > ROM

  .rodata : ALIGN(16) {
    *(.rodata .rodata.*)
  } > ROM

  .data : ALIGN(16) {
    *(.data .data.*)
  } > ROM

  .bss (NOLOAD) : ALIGN(16) {
    __bss_start = .;
    *(.bss .bss.*)
    *(COMMON)
    __bss_end = .;
  } > RAM
}