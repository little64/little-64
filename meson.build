project('little-64', 'cpp',
  version : '0.1.0',
  default_options : ['cpp_std=c++26'])

arch_inc = include_directories('arch')

# --- Emulator (static library) ---
emulator_lib = static_library('little-64-cpu',
  [
    'emulator/cpu.cpp',
    'emulator/memory_region.cpp',
    'emulator/memory_bus.cpp',
    'emulator/ram_region.cpp',
    'emulator/rom_region.cpp',
    'emulator/serial_device.cpp',
  ],
  include_directories : [include_directories('emulator'), arch_inc],
  install : false,
)

executable('little-64',
  ['emulator/main.cpp'],
  link_with : emulator_lib,
  include_directories : [include_directories('emulator'), arch_inc],
  install : true,
)

# --- Assembler (static library) ---
asm_lib = static_library('little-64-asm-lib',
  [
    'assembler/lexer.cpp',
    'assembler/encoder.cpp',
    'assembler/assembler.cpp',
  ],
  include_directories : [include_directories('assembler'), arch_inc],
  install : false,
)

executable('little-64-asm',
  ['assembler/main.cpp'],
  link_with : asm_lib,
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

# --- GUI Debugger/Emulator/Assembler ---
sdl2_dep = dependency('sdl2')
gl_dep   = dependency('gl')

imgui_dep = dependency('imgui',
  fallback : ['imgui', 'imgui_dep'],
)

nfd_dep = dependency('nativefiledialog-extended',
  fallback : ['nativefiledialog-extended', 'nfde_dep'],
)

gui_src = [
  'gui/main.cpp',
  'gui/app.cpp',
  'gui/panels/assembler_panel.cpp',
  'gui/panels/control_panel.cpp',
  'gui/panels/disassembly_panel.cpp',
  'gui/panels/register_panel.cpp',
  'gui/panels/memory_panel.cpp',
  'gui/panels/serial_output_panel.cpp',
  'gui/panels/memmap_panel.cpp',
  'gui/vendor/TextEditor.cpp',
]

executable('little-64-gui',
  gui_src,
  link_with : [asm_lib, disasm_lib, emulator_lib],
  include_directories : [
    include_directories('gui'),
    include_directories('gui/panels'),
    include_directories('gui/vendor'),
    include_directories('emulator'),
    include_directories('assembler'),
    include_directories('disassembler'),
    arch_inc,
  ],
  dependencies : [sdl2_dep, gl_dep, imgui_dep, nfd_dep],
  install : true,
)
