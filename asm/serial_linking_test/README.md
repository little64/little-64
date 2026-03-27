# serial_linking_test

This example demonstrates splitting `serial_boot.asm` into two modules and linking them.

## Files

- `part1.asm` — entry point plus `hello_world` string, extern `serial_print`.
- `part2.asm` — `serial_print` implementation and `_serial_base` constant.

## Build + Link

```sh
cd /home/alexander/projects/little-64

# Assemble each module to ELF objects
./builddir/little-64-asm --elf -o asm/serial_linking_test/part1.o asm/serial_linking_test/part1.asm
./builddir/little-64-asm --elf -o asm/serial_linking_test/part2.o asm/serial_linking_test/part2.asm

# Link them to flat binary
./builddir/little-64-linker -o asm/serial_linking_test/serial_boot_linked.bin \
  asm/serial_linking_test/part1.o asm/serial_linking_test/part2.o

# Run in emulator
./builddir/little-64 ./asm/serial_linking_test/serial_boot_linked.bin
```

## Notes

- `part1.asm` declares `serial_print` with `.extern`, then uses `JAL @serial_print`.
- `part2.asm` exports `serial_print` via `.global serial_print`.
- Linking resolves `PCREL6` JAL relocation and ABS64 `_serial_base` reference.
