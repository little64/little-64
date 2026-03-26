project('little-64', 'cpp',
  version : '0.1.0',
  default_options : ['cpp_std=c++17'])

arch_inc = include_directories('arch')

# --- Emulator ---
emulator_src = [
  'emulator/main.cpp',
  'emulator/cpu.cpp',
]

executable('little-64',
  emulator_src,
  include_directories : [include_directories('emulator'), arch_inc],
  install : true,
)

# --- Assembler ---
assembler_src = [
  'assembler/main.cpp',
  'assembler/lexer.cpp',
  'assembler/encoder.cpp',
  'assembler/assembler.cpp',
]

executable('little-64-asm',
  assembler_src,
  include_directories : [include_directories('assembler'), arch_inc],
  install : true,
)

# --- Disassembler (static library for embedding) ---
disasm_lib = static_library('little-64-disasm-lib',
  ['disassembler/disassembler.cpp'],
  include_directories : [include_directories('disassembler'), arch_inc],
  install : true,
)

# CLI tool that links the library
executable('little-64-disasm',
  ['disassembler/main.cpp'],
  link_with : disasm_lib,
  include_directories : [include_directories('disassembler'), arch_inc],
  install : true,
)
