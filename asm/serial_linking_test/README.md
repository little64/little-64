# serial_linking_test

This example demonstrates splitting a small serial-output program across multiple modules and linking them.

## Files

- `part1.asm` — entry point, string data, external call site
- `part2.asm` — `serial_print` implementation and serial base usage

## Build and Link

From project root:

```bash
compilers/bin/llvm-mc -triple=little64 -filetype=obj asm/serial_linking_test/part1.asm -o asm/serial_linking_test/part1.o
compilers/bin/llvm-mc -triple=little64 -filetype=obj asm/serial_linking_test/part2.asm -o asm/serial_linking_test/part2.o

./builddir/little-64-linker -o asm/serial_linking_test/serial_boot_linked.bin \
  asm/serial_linking_test/part1.o \
  asm/serial_linking_test/part2.o
```

Run:

```bash
./builddir/little-64 asm/serial_linking_test/serial_boot_linked.bin
```

## What It Validates

- symbol export/import (`.global` / `.extern`)
- relocation resolution across object modules
- linked binary execution in emulator

## Update Checklist

If this example or linker behavior changes:

- update this README,
- verify commands run successfully end-to-end,
- update related docs if CLI contracts changed.
