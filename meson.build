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

# --- Assembler test suite ---
test_asm = executable('test-assembler',
  ['tests/test_assembler.cpp'],
  link_with : asm_lib,
  include_directories : [include_directories('assembler'), arch_inc],
  install : false,
)
test('assembler', test_asm, suite : 'assembler')

linker_lib = static_library('little-64-linker-lib',
  ['linker/linker.cpp'],
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
  [
    'project/project.cpp',
    'project/compiler.cpp',
  ],
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
