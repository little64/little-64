core_assembler_src = [
  'lexer.cpp',
  'encoder.cpp',
  'assembler.cpp',
]

asm_lib = static_library('little-64-asm-lib',
  core_assembler_src,
  include_directories : [assembler_inc, arch_inc],
  install : false,
)

executable('little-64-asm',
  ['main.cpp'],
  link_with : asm_lib,
  include_directories : [assembler_inc, arch_inc],
  install : true,
)
