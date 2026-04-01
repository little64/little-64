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
  'emulator/machine_config.cpp',
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
  'project/boot_frame_builder.cpp',
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

ui_qt_src = [
  'qt/main.cpp',
  'qt/main_window.cpp',
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
  include_directories : [include_directories('assembler'), arch_inc, include_directories('tests'), include_directories('tests/support')],
  install : false,
)
test('assembler', test_asm, suite : ['unit', 'assembler'])

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
  include_directories : [include_directories('linker'), include_directories('assembler'), arch_inc, include_directories('tests'), include_directories('tests/support')],
  install : false,
)

test('linker', test_linker, suite : ['unit', 'linker'])

# --- CPU execution test suite ---
test_inc = include_directories('tests')
test_support_inc = include_directories('tests/support')

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
    test('cpu-' + name, t, suite : ['unit', 'isa', 'cpu', name], timeout : 60)
endforeach

test_devices = executable('test-devices',
  ['tests/test_devices.cpp'],
  link_with : [emulator_lib],
  include_directories : [
    include_directories('emulator'),
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('devices', test_devices, suite : ['unit', 'device'], timeout : 60)

# --- Project library and runner ---
project_lib = static_library('little-64-project-lib',
  core_project_src,
  include_directories : [include_directories('project'), include_directories('boot')],
  install : false,
)

little64_run = executable('little-64-run',
  ['project/runner_main.cpp'],
  link_with : [project_lib, asm_lib, linker_lib, emulator_lib],
  include_directories : [
    include_directories('project'),
    include_directories('boot'),
    include_directories('assembler'),
    include_directories('linker'),
    include_directories('emulator'),
    arch_inc,
  ],
  install : false,
)

little64_test_env = [
  'LITTLE64_LD=' + meson.project_source_root() + '/compilers/bin/ld.lld',
]

python3 = import('python').find_installation('python3')

little64_runner_test_env = little64_test_env + [
  'LITTLE64_LOAD_ELF=0',
  'LITTLE64_USE_INTERNAL_LINKER=1',
]

test('project-runner',
  little64_run,
  args : [meson.project_source_root() / 'tests/projects/hello/hello.l64proj'],
  env : little64_runner_test_env,
  suite : ['integration', 'project'],
)

test_boot_frame = executable('test-boot-frame',
  ['tests/test_boot_frame.cpp'],
  link_with : [project_lib],
  include_directories : [
    include_directories('project'),
    include_directories('boot'),
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('boot-frame', test_boot_frame, suite : ['unit', 'boot'], timeout : 60)

test('boot-bios-run',
  python3,
  args : [
    meson.project_source_root() / 'tests/boot/test_bios_boot.py',
  ],
  suite : ['boot', 'integration'],
  timeout : 60,
)

llvm_report_path = meson.project_build_root() / 'meson-logs' / 'llvm-integration-report.json'
test('llvm-integration',
  python3,
  args : [
    meson.project_source_root() / 'tests/llvm/scripts/run_tests.py',
    '--no-color',
    '--report-json',
    llvm_report_path,
  ],
  env : little64_test_env,
  suite : ['llvm', 'integration', 'toolchain'],
  timeout : 120,
)

test('debug-rsp-integration',
  python3,
  args : [
    meson.project_source_root() / 'tests/debug/test_rsp_server.py',
  ],
  suite : ['debug', 'integration'],
  timeout : 60,
)

test('debug-lldb-remote-smoke',
  python3,
  args : [
    meson.project_source_root() / 'tests/debug/test_lldb_remote_smoke.py',
  ],
  suite : ['debug', 'integration', 'lldb'],
  timeout : 60,
)

# --- Disassembler (static library for embedding) ---
disasm_lib = static_library('little-64-disasm-lib',
  core_disassembler_src,
  include_directories : [include_directories('disassembler'), arch_inc],
  install : true,
)

test_disasm = executable('test-disassembler',
  ['tests/test_disassembler.cpp'],
  link_with : [disasm_lib],
  include_directories : [
    include_directories('disassembler'),
    arch_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('disassembler', test_disasm, suite : ['unit', 'disassembler'], timeout : 60)

test_memory_bus = executable('test-memory-bus',
  ['tests/test_memory_bus.cpp'],
  link_with : [emulator_lib],
  include_directories : [
    include_directories('emulator'),
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('memory-bus', test_memory_bus, suite : ['unit', 'memory'], timeout : 60)

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

qt_frontend_opt = get_option('qt_frontend')
qt_dep = dependency('qt6', modules : ['Core', 'Gui', 'Widgets'], required : false)
if not qt_dep.found()
  qt_dep = dependency('qt5', modules : ['Core', 'Gui', 'Widgets'], required : false)
endif

if qt_frontend_opt.enabled() and not qt_dep.found()
  error('qt_frontend is enabled but neither Qt6 nor Qt5 Widgets dependencies were found')
endif

if qt_dep.found()
  executable('little-64-qt',
    ui_qt_src,
    link_with : [emulator_lib, disasm_lib],
    include_directories : [
      include_directories('qt'),
      include_directories('emulator'),
      include_directories('disassembler'),
      arch_inc,
    ],
    dependencies : [qt_dep],
    install : true,
  )
elif qt_frontend_opt.enabled()
  error('qt_frontend is enabled but Qt was not detected')
else
  message('Qt frontend disabled: Qt dependencies not found (or qt_frontend=disabled)')
endif
