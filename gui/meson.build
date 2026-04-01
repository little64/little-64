ui_gui_src = [
  'main.cpp',
  'app.cpp',
  'panels/assembler_panel.cpp',
  'panels/control_panel.cpp',
  'panels/disassembly_panel.cpp',
  'panels/register_panel.cpp',
  'panels/memory_panel.cpp',
  'panels/serial_output_panel.cpp',
  'panels/memmap_panel.cpp',
  'vendor/TextEditor.cpp',
]

sdl2_dep = dependency('sdl2')
gl_dep = dependency('gl')

imgui_dep = dependency('imgui',
  fallback : ['imgui', 'imgui_dep'],
)

nfd_dep = dependency('nativefiledialog-extended',
  fallback : ['nativefiledialog-extended', 'nfde_dep'],
)

executable('little-64-gui',
  ui_gui_src,
  link_with : [asm_lib, disasm_lib, emulator_lib, linker_lib, project_lib],
  include_directories : [
    gui_inc,
    gui_panels_inc,
    gui_vendor_inc,
    emulator_inc,
    assembler_inc,
    disassembler_inc,
    linker_inc,
    project_inc,
    arch_inc,
  ],
  dependencies : [sdl2_dep, gl_dep, imgui_dep, nfd_dep],
  install : true,
)
