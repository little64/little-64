ENTRY(_start)

MEMORY
{
  FLASH (rx) : ORIGIN = 0x0000000020000000, LENGTH = 0x00100000
  RAM (rwx)  : ORIGIN = 0x0000000000000000, LENGTH = 0x00100000
}

SECTIONS
{
  .text : ALIGN(16) {
    *(.text.boot)
    *(.text .text.*)
  } > FLASH

  .rodata : ALIGN(16) {
    *(.rodata .rodata.*)
  } > FLASH

  .data : ALIGN(16) {
    *(.data .data.*)
  } > FLASH

  .bss (NOLOAD) : ALIGN(16) {
    __bss_start = .;
    *(.bss .bss.*)
    *(COMMON)
    __bss_end = .;
  } > RAM
}