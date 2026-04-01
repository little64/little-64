ENTRY(kernel_main)

KERNEL_VIRT_BASE = 0xFFFF800000000000;
KERNEL_PHYS_BASE = 0x0000000000200000;

SECTIONS
{
  . = KERNEL_VIRT_BASE;

  .text : ALIGN(4096) {
    *(.text.boot)
    *(.text .text.*)
  }

  .rodata : ALIGN(4096) {
    *(.rodata .rodata.*)
  }

  .data : ALIGN(4096) {
    *(.data .data.*)
  }

  .bss : ALIGN(4096) {
    *(.bss .bss.*)
    *(COMMON)
  }

  __kernel_virt_start = ADDR(.text);
  __kernel_phys_start = KERNEL_PHYS_BASE;
  __kernel_virt_end = .;
  __kernel_phys_end = KERNEL_PHYS_BASE + (__kernel_virt_end - __kernel_virt_start);
}
