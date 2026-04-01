project('little-64', 'cpp',
  version : '0.1.0',
  default_options : ['cpp_std=c++26'])

arch_inc = include_directories('arch')

core_emulator_src = [
  'emulator/cpu.cpp',
  'emulator/debug_server.cpp',
  'emulator/debug_transport.cpp',
  'emulator/emulator_session.cpp',
  'emulator/headless_runtime.cpp',
  'emulator/memory_region.cpp',
  'emulator/memory_bus.cpp',
  'emulator/ram_region.cpp',
  'emulator/rom_region.cpp',
  'emulator/serial_device.cpp',
]

core_assembler_src = [
  'assembler/lexer.cpp',
  'assembler/encoder.cpp',
  'assembler/assembler.cpp',
]

core_linker_src = [
  'linker/linker.cpp',
]

core_disassembler_src = [
  'disassembler/disassembler.cpp',
]

core_project_src = [
  'project/project.cpp',
  'project/compiler.cpp',
]

ui_gui_src = [
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

# --- Emulator (static library) ---
emulator_lib = static_library('little-64-cpu',
  core_emulator_src,
  include_directories : [include_directories('emulator'), arch_inc],
  install : false,
)

executable('little-64',
  ['emulator/main.cpp'],
  link_with : emulator_lib,
  include_directories : [include_directories('emulator'), arch_inc],
  install : true,
)

executable('little-64-debug',
  ['emulator/debug_main.cpp'],
  link_with : emulator_lib,
  include_directories : [include_directories('emulator'), arch_inc],
  install : true,
)

# --- Assembler (static library) ---
asm_lib = static_library('little-64-asm-lib',
  core_assembler_src,
  include_directories : [include_directories('assembler'), arch_inc],
  install : false,
)

executable('little-64-asm',
  ['assembler/main.cpp'],
  link_with : asm_lib,
  include_directories : [include_directories('assembler'), arch_inc],
  install : true,
)

# --- Assembler test suite ---
test_asm = executable('test-assembler',
  ['tests/test_assembler.cpp'],
  link_with : asm_lib,
  include_directories : [include_directories('assembler'), arch_inc],
  install : false,
)
test('assembler', test_asm, suite : 'assembler')

linker_lib = static_library('little-64-linker-lib',
  core_linker_src,
  include_directories : [include_directories('linker')],
  install : false,
)

executable('little-64-linker',
  ['linker/main.cpp'],
  link_with : linker_lib,
  include_directories : [include_directories('linker')],
  install : false,
)

test_linker = executable('test-linker',
  ['tests/test_linker.cpp'],
  link_with : [linker_lib, asm_lib],
  include_directories : [include_directories('linker'), include_directories('assembler'), arch_inc],
  install : false,
)

test('linker', test_linker, suite : 'linker')

# --- CPU execution test suite ---
test_inc = include_directories('tests')

cpu_tests = {
    'gp':          'tests/test_cpu_gp.cpp',
    'ldi':         'tests/test_cpu_ldi.cpp',
    'memory':      'tests/test_cpu_memory.cpp',
    'jumps':       'tests/test_cpu_jumps.cpp',
    'special':     'tests/test_cpu_special.cpp',
    'integration': 'tests/test_cpu_integration.cpp',
}

foreach name, src : cpu_tests
    t = executable('test-cpu-' + name, src,
        link_with : [emulator_lib, asm_lib],
        include_directories : [
            include_directories('emulator'),
            include_directories('assembler'),
            arch_inc,
            test_inc,
        ],
        install : false,
    )
    test('cpu-' + name, t, suite : ['cpu', name], timeout : 60)
endforeach

# --- Project library and runner ---
project_lib = static_library('little-64-project-lib',
  core_project_src,
  include_directories : [include_directories('project')],
  install : false,
)

little64_run = executable('little-64-run',
  ['project/runner_main.cpp'],
  link_with : [project_lib, asm_lib, linker_lib, emulator_lib],
  include_directories : [
    include_directories('project'),
    include_directories('assembler'),
    include_directories('linker'),
    include_directories('emulator'),
    arch_inc,
  ],
  install : false,
)

test('project-runner',
  little64_run,
  args : [meson.source_root() / 'tests/projects/hello/hello.l64proj'],
)

# --- Disassembler (static library for embedding) ---
disasm_lib = static_library('little-64-disasm-lib',
  core_disassembler_src,
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

executable('little-64-gui',
  ui_gui_src,
  link_with : [asm_lib, disasm_lib, emulator_lib, linker_lib, project_lib],
  include_directories : [
    include_directories('gui'),
    include_directories('gui/panels'),
    include_directories('gui/vendor'),
    include_directories('emulator'),
    include_directories('assembler'),
    include_directories('disassembler'),
    include_directories('linker'),
    include_directories('project'),
    arch_inc,
  ],
  dependencies : [sdl2_dep, gl_dep, imgui_dep, nfd_dep],
  install : true,
)
