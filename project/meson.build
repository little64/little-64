core_project_src = [
  'project.cpp',
  'compiler.cpp',
  'boot_frame_builder.cpp',
]

project_lib = static_library('little-64-project-lib',
  core_project_src,
  include_directories : [root_inc, project_inc, boot_inc],
  install : false,
)

little64_run = executable('little-64-run',
  ['runner_main.cpp'],
  link_with : [project_lib, asm_lib, linker_lib, emulator_lib],
  include_directories : [
    root_inc,
    project_inc,
    boot_inc,
    assembler_inc,
    linker_inc,
    emulator_inc,
    arch_inc,
  ],
  install : false,
)
