test_asm = executable('test-assembler',
  ['host/test_assembler.cpp'],
  link_with : [project_lib, linker_lib],
  include_directories : [project_inc, linker_inc, arch_inc, test_inc, test_support_inc],
  install : false,
)
test('assembler', test_asm, suite : ['unit', 'assembler'])

test_linker = executable('test-linker',
  ['host/test_linker.cpp'],
  link_with : [linker_lib, project_lib],
  include_directories : [project_inc, linker_inc, arch_inc, test_inc, test_support_inc],
  install : false,
)

test('linker', test_linker, suite : ['unit', 'linker'])

cpu_tests = {
  'gp':          'target/test_cpu_gp.cpp',
  'ldi':         'target/test_cpu_ldi.cpp',
  'memory':      'target/test_cpu_memory.cpp',
  'jumps':       'target/test_cpu_jumps.cpp',
  'special':     'target/test_cpu_special.cpp',
  'integration': 'target/test_cpu_integration.cpp',
}

foreach name, src : cpu_tests
  t = executable('test-cpu-' + name, src,
    link_with : [emulator_lib, linker_lib, project_lib],
    include_directories : [
      emulator_inc,
      linker_inc,
      project_inc,
      arch_inc,
      test_inc,
    ],
    install : false,
  )
  test('cpu-' + name, t, suite : ['unit', 'isa', 'cpu', name], timeout : 60)
endforeach

test_devices = executable('test-devices',
  ['host/test_devices.cpp'],
  link_with : [emulator_lib],
  include_directories : [
    emulator_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('devices', test_devices, suite : ['unit', 'device'], timeout : 60)

test_disasm = executable('test-disassembler',
  ['host/test_disassembler.cpp'],
  link_with : [disasm_lib],
  include_directories : [
    disassembler_inc,
    arch_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('disassembler', test_disasm, suite : ['unit', 'disassembler'], timeout : 60)

test_memory_bus = executable('test-memory-bus',
  ['host/test_memory_bus.cpp'],
  link_with : [emulator_lib],
  include_directories : [
    emulator_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('memory-bus', test_memory_bus, suite : ['unit', 'memory'], timeout : 60)

test_boot_frame = executable('test-boot-frame',
  ['host/test_boot_frame.cpp'],
  link_with : [project_lib],
  include_directories : [
    root_inc,
    project_inc,
    boot_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
test('boot-frame', test_boot_frame, suite : ['unit', 'boot'], timeout : 60)

little64_test_env = [
  'LITTLE64_LD=' + meson.project_source_root() + '/compilers/bin/ld.lld',
]

little64_runner_test_env = little64_test_env + [
  'LITTLE64_LOAD_ELF=0',
  'LITTLE64_USE_INTERNAL_LINKER=1',
]

test('project-runner',
  little64_run,
  args : [meson.project_source_root() / 'tests/host/projects/hello/hello.l64proj'],
  env : little64_runner_test_env,
  suite : ['integration', 'project'],
)

test('boot-bios-run',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/boot/test_bios_boot.py',
  ],
  suite : ['boot', 'integration'],
  timeout : 60,
)

llvm_report_path = meson.project_build_root() / 'meson-logs' / 'llvm-integration-report.json'
test('llvm-integration',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/llvm/scripts/run_tests.py',
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
    meson.project_source_root() / 'tests/host/debug/test_rsp_server.py',
  ],
  suite : ['debug', 'integration'],
  timeout : 60,
)

test('debug-bios-frame-sections',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/debug/test_bios_frame_sections.py',
  ],
  suite : ['debug', 'integration'],
  timeout : 60,
)

test('debug-lldb-remote-smoke',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/debug/test_lldb_remote_smoke.py',
  ],
  suite : ['debug', 'integration', 'lldb'],
  timeout : 60,
)

test('debug-lldb-step-over-once',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/debug/test_lldb_step_over_once.py',
  ],
  suite : ['debug', 'integration', 'lldb'],
  timeout : 60,
)

test('debug-lldb-arch-smoke',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/debug/test_lldb_arch_smoke.py',
  ],
  suite : ['debug', 'integration', 'lldb'],
  timeout : 60,
)
