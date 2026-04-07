dtb_embed_dep = declare_dependency()
dtc_prog = find_program('dtc', required : false)
xxd_prog = find_program('xxd', required : false)

if dtc_prog.found() and xxd_prog.found()
  little64_dtb = custom_target('little64-dtb',
    input : 'little64.dts',
    output : 'little64.dtb',
    command : [dtc_prog, '-b', '0', '@INPUT@', '-o', '@OUTPUT@'],
    build_by_default : true,
  )

  # xxd emits `embedded_dtb` and `embedded_dtb_len`, consumed by dtb_loader.cpp.
  little64_dtb_header = custom_target('little64-dtb-embed-header',
    input : little64_dtb,
    output : 'little64_dtb_embed.hpp',
    command : [xxd_prog, '-i', '-n', 'embedded_dtb', '@INPUT@'],
    capture : true,
    build_by_default : true,
  )

  dtb_embed_dep = declare_dependency(sources : [little64_dtb_header])
else
  warning('dtc/xxd not found: direct boot runs without embedded DTB')
endif

core_emulator_src = [
  'address_translator.cpp',
  'cpu.cpp',
  'debug_server.cpp',
  'debug_transport.cpp',
  'dtb_loader.cpp',
  'emulator_clock.cpp',
  'emulator_session.cpp',
  'headless_runtime.cpp',
  'machine_config.cpp',
  'memory_region.cpp',
  'page_table_builder.cpp',
  'memory_bus.cpp',
  'ram_region.cpp',
  'rom_region.cpp',
  'serial_device.cpp',
  'timer_device.cpp',
]

emulator_lib = static_library('little-64-cpu',
  core_emulator_src,
  include_directories : [emulator_inc, arch_inc],
  dependencies : [dtb_embed_dep],
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
