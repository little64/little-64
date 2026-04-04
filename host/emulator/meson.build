core_emulator_src = [
  'address_translator.cpp',
  'cpu.cpp',
  'debug_server.cpp',
  'debug_transport.cpp',
  'emulator_session.cpp',
  'headless_runtime.cpp',
  'machine_config.cpp',
  'memory_region.cpp',
  'page_table_builder.cpp',
  'memory_bus.cpp',
  'ram_region.cpp',
  'rom_region.cpp',
  'serial_device.cpp',
]

emulator_lib = static_library('little-64-cpu',
  core_emulator_src,
  include_directories : [emulator_inc, arch_inc],
  install : false,
)

little64_exe = executable('little-64',
  ['main.cpp'],
  link_with : emulator_lib,
  include_directories : [emulator_inc, arch_inc],
  install : true,
)

little64_debug_exe = executable('little-64-debug',
  ['debug_main.cpp'],
  link_with : emulator_lib,
  include_directories : [emulator_inc, arch_inc],
  install : true,
)
