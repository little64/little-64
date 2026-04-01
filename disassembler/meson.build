core_disassembler_src = [
  'disassembler.cpp',
]

disasm_lib = static_library('little-64-disasm-lib',
  core_disassembler_src,
  include_directories : [disassembler_inc, arch_inc],
  install : true,
)

executable('little-64-disasm',
  ['main.cpp'],
  link_with : disasm_lib,
  include_directories : [disassembler_inc, arch_inc],
  install : true,
)
