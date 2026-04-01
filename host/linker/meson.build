core_linker_src = [
  'linker.cpp',
]

linker_lib = static_library('little-64-linker-lib',
  core_linker_src,
  include_directories : [linker_inc],
  install : false,
)

executable('little-64-linker',
  ['main.cpp'],
  link_with : linker_lib,
  include_directories : [linker_inc],
  install : false,
)
