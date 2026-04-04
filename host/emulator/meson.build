# Device Tree (DTB) support - manual integration for now
# To enable DTB embedding:
# 1. Ensure dtc (device tree compiler) is installed: apt-get install device-tree-compiler
# 2. From the project root, run:
#    dtc -b0 host/emulator/little64.dts -o builddir/little64.dtb
#    xxd -i < builddir/little64.dtb > builddir/little64_dtb_embed.hpp
# 3. Move little64_dtb_embed.hpp to host/emulator/ or ensure it's in the include path
# 4. The DTB will then be available via DTBLoader::getEmbeddedDTB()

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
