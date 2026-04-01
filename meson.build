project('little-64', 'cpp',
  version : '0.1.0',
  default_options : ['cpp_std=c++26'])

arch_inc = include_directories('arch')
root_inc = include_directories('.')
python3 = import('python').find_installation('python3')

emulator_inc = include_directories('emulator')
linker_inc = include_directories('linker')
disassembler_inc = include_directories('disassembler')
project_inc = include_directories('project')
boot_inc = include_directories('boot')
gui_inc = include_directories('gui')
gui_panels_inc = include_directories('gui/panels')
gui_vendor_inc = include_directories('gui/vendor')
qt_inc = include_directories('qt')
test_inc = include_directories('tests')
test_support_inc = include_directories('tests/support')

subdir('emulator')
subdir('linker')
subdir('disassembler')
subdir('project')
subdir('tests')
subdir('gui')
subdir('qt')

ln_prog = find_program('ln')

custom_target('compat-little-64-root',
  input : little64_exe,
  output : 'little-64',
  command : [ln_prog, '-sf', '@INPUT@', '@OUTPUT@'],
  build_by_default : true,
)

custom_target('compat-little-64-debug-root',
  input : little64_debug_exe,
  output : 'little-64-debug',
  command : [ln_prog, '-sf', '@INPUT@', '@OUTPUT@'],
  build_by_default : true,
)
