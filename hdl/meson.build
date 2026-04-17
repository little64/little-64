hdl_python = find_program(
  meson.project_source_root() / '.venv/bin/python',
  'python3',
)

test('hdl-unit',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests',
    '--ignore',
    meson.project_source_root() / 'hdl/tests/test_shared_isa.py',
    '--ignore',
    meson.project_source_root() / 'hdl/tests/test_v2_shared_isa.py',
  ],
  suite : ['unit', 'hdl'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-shared-gp',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_shared_isa.py',
    '-k',
    'shared_gp',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'gp'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-shared-ldi',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_shared_isa.py',
    '-k',
    'shared_ldi',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'ldi'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-v2-shared-gp',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_shared_isa.py',
    '-k',
    'v2_shared_gp',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'gp', 'v2'],
  is_parallel : false,
  timeout : 180,
)

test('hdl-v2-shared-ldi',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_shared_isa.py',
    '-k',
    'v2_shared_ldi',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'ldi', 'v2'],
  is_parallel : false,
  timeout : 180,
)

test('hdl-shared-jumps',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_shared_programs.py',
    '-k',
    'shared_jump',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'jumps'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-v2-shared-jumps',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_shared_programs.py',
    '-k',
    'shared_jump',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'jumps', 'v2'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-v2-shared-memory',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_shared_programs.py',
    '-k',
    'shared_memory',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'memory', 'v2'],
  is_parallel : false,
  timeout : 180,
)

test('hdl-v2-unaligned',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_unaligned.py',
  ],
  suite : ['unit', 'hdl', 'memory', 'unaligned', 'v2'],
  is_parallel : false,
  timeout : 180,
)

test('hdl-v2-cache',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_cache.py',
  ],
  suite : ['unit', 'hdl', 'cache', 'v2'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-v2-traps',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_v2_traps.py',
  ],
  suite : ['unit', 'hdl', 'trap', 'mmu', 'v2'],
  is_parallel : false,
  timeout : 180,
)

test('hdl-shared-memory',
  hdl_python,
  args : [
    '-m',
    'pytest',
    '-q',
    meson.project_source_root() / 'hdl/tests/test_shared_programs.py',
    '-k',
    'shared_memory',
  ],
  suite : ['unit', 'hdl', 'isa', 'cpu', 'memory'],
  is_parallel : false,
  timeout : 60,
)

test('hdl-linux-boot-smoke',
  hdl_python,
  args : [
    meson.project_source_root() / 'hdl/tools/run_verilator_linux_boot_smoke.py',
  ],
  suite : ['hdl', 'linux', 'boot'],
  is_parallel : false,
  timeout : 600,
)
