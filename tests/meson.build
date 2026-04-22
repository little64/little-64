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

test('shared-case-generation',
  python3,
  args : [
    meson.project_source_root() / 'tests/shared/generate_instruction_cases.py',
    '--check',
  ],
  suite : ['unit', 'isa', 'tests'],
  timeout : 60,
)

test('linux-port-build-helper',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/test_linux_port_build_helper.py',
  ],
  suite : ['unit', 'linux', 'tooling'],
  timeout : 60,
)

test('sd-build-helper',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/test_sd_build_helper.py',
  ],
  suite : ['unit', 'linux', 'tooling'],
  timeout : 60,
)

test('little64-cli-smoke',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/test_little64_cli.py',
  ],
  suite : ['unit', 'tooling'],
  timeout : 30,
)

test('no-shell-wrappers',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/test_no_shell_wrappers.py',
  ],
  suite : ['unit', 'tooling'],
  timeout : 30,
)

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

test_paging = executable('test-paging',
  ['host/test_paging.cpp'],
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
test('paging', test_paging, suite : ['unit', 'paging', 'memory'], timeout : 60)

test_tlb = executable('test-tlb',
  ['host/test_tlb.cpp'],
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
test('tlb', test_tlb, suite : ['unit', 'paging', 'memory'], timeout : 120)

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

test_clang_runtime_stress = executable('test-clang-runtime-stress',
  ['host/test_clang_runtime_stress.cpp'],
  link_with : [emulator_lib, linker_lib, project_lib],
  include_directories : [
    emulator_inc,
    linker_inc,
    project_inc,
    arch_inc,
    test_inc,
    test_support_inc,
  ],
  install : false,
)
clang_runtime_test_env = [
  'LITTLE64_LD=' + meson.project_source_root() + '/compilers/bin/ld.lld',
  'LITTLE64_CC=' + meson.project_source_root() + '/compilers/bin/clang',
]
test('clang-runtime-stress',
  test_clang_runtime_stress,
  env : clang_runtime_test_env,
  suite : ['integration', 'clang', 'cpu'],
  timeout : 600,
)

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

boot_bios_opt_levels = ['0', '1', '2', '3', 's', 'z']
foreach opt : boot_bios_opt_levels
  boot_bios_test_name = 'boot-bios-run-o' + opt
  if opt == '0'
    boot_bios_test_name = 'boot-bios-run'
  endif

  test(boot_bios_test_name,
    python3,
    args : [
      meson.project_source_root() / 'tests/host/boot/test_bios_boot.py',
      '--opt',
      opt,
    ],
    suite : ['boot', 'integration', 'opt-' + opt],
    timeout : 60,
  )
endforeach

test('boot-direct-physical-run',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/boot/test_direct_boot_paging.py',
  ],
  suite : ['boot', 'integration', 'direct'],
  timeout : 60,
)

test('boot-litex-bootrom-run',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/boot/test_litex_flash_boot.py',
  ],
  suite : ['boot', 'integration', 'litex'],
  timeout : 120,
)

test('boot-linux-userspace-write',
  python3,
  args : [
    meson.project_source_root() / 'tests/host/boot/test_linux_userspace_write.py',
  ],
  suite : ['boot', 'integration', 'linux'],
  timeout : 300,
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
