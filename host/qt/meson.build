ui_qt_src = [
  'main.cpp',
  'main_window.cpp',
]

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
      qt_inc,
      emulator_inc,
      disassembler_inc,
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
