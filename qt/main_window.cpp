#include "main_window.hpp"

#include "../frontend/debugger_views.hpp"

#include <QAction>
#include <QDockWidget>
#include <QFile>
#include <QFileDialog>
#include <QGridLayout>
#include <QGroupBox>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QMainWindow>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QStatusBar>
#include <QTableWidget>
#include <QTextEdit>
#include <QTextCursor>
#include <QTimer>
#include <QToolBar>
#include <QVBoxLayout>
#include <QWidget>

#include <cstdint>

namespace {

constexpr int kDisassemblyRows = 96;
constexpr int kMemoryRows = 128;
constexpr int kBytesPerMemoryRow = 16;

QString toHex64(uint64_t value) {
    return QString("0x%1").arg(value, 16, 16, QChar('0')).toUpper();
}

QString toHex16(uint16_t value) {
    return QString("0x%1").arg(value, 4, 16, QChar('0')).toUpper();
}

}

MainWindow::MainWindow()
    : exec_(runtime_) {
    buildUi();
    refreshAllViews();
}

void MainWindow::buildUi() {
    setWindowTitle("Little-64 Qt Emulator (Preview)");
    resize(1600, 980);

    auto* file_menu = menuBar()->addMenu("&File");
    auto* open_elf_action = file_menu->addAction("Open ELF...");
    auto* quit_action = file_menu->addAction("Quit");

    auto* view_menu = menuBar()->addMenu("&View");
    auto* reset_layout_action = view_menu->addAction("Reset Layout");

    auto* main_toolbar = addToolBar("Main");
    auto* step_action = main_toolbar->addAction("Step");
    auto* live_toggle_action = main_toolbar->addAction("Start Live Run");
    auto* reset_action = main_toolbar->addAction("Reset");
    auto* interrupt_action = main_toolbar->addAction("INT 63");

    run_speed_spin_ = new QSpinBox(this);
    run_speed_spin_->setRange(1, 100000);
    run_speed_spin_->setValue(250);
    run_speed_spin_->setPrefix("speed ");
    run_speed_spin_->setSuffix(" instr/tick");
    main_toolbar->addWidget(run_speed_spin_);

    cpu_status_ = new QLabel(this);
    cpu_status_->setMinimumWidth(220);
    main_toolbar->addWidget(cpu_status_);

    auto* central = new QWidget(this);
    auto* central_layout = new QVBoxLayout(central);
    auto* intro = new QLabel(
        "Qt frontend preview (in-process runtime).\n"
        "Use docks for OS-dev workflows; ImGui frontend remains available.",
        central);
    intro->setWordWrap(true);
    central_layout->addWidget(intro);
    central_layout->addStretch(1);
    setCentralWidget(central);

    auto* registers_dock = new QDockWidget("Registers", this);
    register_table_ = new QTableWidget(0, 2, registers_dock);
    register_table_->setHorizontalHeaderLabels({"Register", "Value"});
    register_table_->horizontalHeader()->setStretchLastSection(true);
    register_table_->verticalHeader()->setVisible(false);
    registers_dock->setWidget(register_table_);
    addDockWidget(Qt::RightDockWidgetArea, registers_dock);

    auto* disasm_dock = new QDockWidget("Disassembly", this);
    disasm_table_ = new QTableWidget(0, 4, disasm_dock);
    disasm_table_->setHorizontalHeaderLabels({"PC", "Address", "Word", "Instruction"});
    disasm_table_->horizontalHeader()->setSectionResizeMode(3, QHeaderView::Stretch);
    disasm_table_->verticalHeader()->setVisible(false);
    disasm_dock->setWidget(disasm_table_);
    addDockWidget(Qt::RightDockWidgetArea, disasm_dock);

    auto* memory_dock = new QDockWidget("Memory", this);
    auto* memory_host = new QWidget(memory_dock);
    auto* memory_layout = new QVBoxLayout(memory_host);

    auto* memory_controls = new QHBoxLayout();
    memory_controls->addWidget(new QLabel("Base:"));
    memory_base_edit_ = new QLineEdit("0x0000000000001000", memory_host);
    memory_controls->addWidget(memory_base_edit_);
    auto* memory_refresh_btn = new QPushButton("Refresh", memory_host);
    memory_controls->addWidget(memory_refresh_btn);
    memory_layout->addLayout(memory_controls);

    memory_table_ = new QTableWidget(0, 3, memory_host);
    memory_table_->setHorizontalHeaderLabels({"Address", "Hex Bytes", "ASCII"});
    memory_table_->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    memory_table_->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    memory_table_->verticalHeader()->setVisible(false);
    memory_layout->addWidget(memory_table_);

    memory_dock->setWidget(memory_host);
    addDockWidget(Qt::LeftDockWidgetArea, memory_dock);

    auto* map_dock = new QDockWidget("Memory Map", this);
    region_table_ = new QTableWidget(0, 3, map_dock);
    region_table_->setHorizontalHeaderLabels({"Name", "Base", "Size"});
    region_table_->horizontalHeader()->setStretchLastSection(true);
    region_table_->verticalHeader()->setVisible(false);
    map_dock->setWidget(region_table_);
    addDockWidget(Qt::BottomDockWidgetArea, map_dock);

    auto* serial_dock = new QDockWidget("Serial Output", this);
    serial_output_ = new QTextEdit(serial_dock);
    serial_output_->setReadOnly(true);
    serial_output_->setLineWrapMode(QTextEdit::NoWrap);
    serial_dock->setWidget(serial_output_);
    addDockWidget(Qt::BottomDockWidgetArea, serial_dock);

    tabifyDockWidget(registers_dock, disasm_dock);

    live_timer_ = new QTimer(this);
    live_timer_->setInterval(8);

    connect(open_elf_action, &QAction::triggered, this, [this]() { loadElfFromDialog(); });
    connect(quit_action, &QAction::triggered, this, [this]() { close(); });

    connect(step_action, &QAction::triggered, this, [this]() {
        std::string err;
        exec_.step(&err);
        if (!err.empty()) {
            setStatusMessage(QString::fromStdString(err));
        }
        refreshAllViews();
    });

    connect(live_toggle_action, &QAction::triggered, this, [this, live_toggle_action]() {
        live_running_ = !live_running_;
        if (live_running_) {
            live_timer_->start();
            live_toggle_action->setText("Stop Live Run");
        } else {
            live_timer_->stop();
            live_toggle_action->setText("Start Live Run");
        }
    });

    connect(reset_action, &QAction::triggered, this, [this]() {
        exec_.reset();
        refreshAllViews();
    });

    connect(interrupt_action, &QAction::triggered, this, [this]() {
        exec_.assertInterrupt(63);
        refreshAllViews();
    });

    connect(memory_refresh_btn, &QPushButton::clicked, this, [this]() {
        refreshMemoryView();
    });

    connect(reset_layout_action, &QAction::triggered, this, [this, registers_dock, disasm_dock, memory_dock, map_dock, serial_dock]() {
        removeDockWidget(registers_dock);
        removeDockWidget(disasm_dock);
        removeDockWidget(memory_dock);
        removeDockWidget(map_dock);
        removeDockWidget(serial_dock);

        addDockWidget(Qt::RightDockWidgetArea, registers_dock);
        addDockWidget(Qt::RightDockWidgetArea, disasm_dock);
        addDockWidget(Qt::LeftDockWidgetArea, memory_dock);
        addDockWidget(Qt::BottomDockWidgetArea, map_dock);
        addDockWidget(Qt::BottomDockWidgetArea, serial_dock);
        tabifyDockWidget(registers_dock, disasm_dock);
    });

    connect(live_timer_, &QTimer::timeout, this, [this]() {
        const int cycles = run_speed_spin_ ? run_speed_spin_->value() : 250;
        std::string err;
        exec_.runCycles(cycles, &err);
        if (!err.empty()) {
            setStatusMessage(QString::fromStdString(err));
        }
        if (!exec_.isRunning() && live_running_) {
            live_running_ = false;
            live_timer_->stop();
        }
        refreshAllViews();
    });
}

void MainWindow::setStatusMessage(const QString& text) {
    if (statusBar()) {
        statusBar()->showMessage(text, 4000);
    }
}

void MainWindow::loadElfFromDialog() {
    const QString file_path = QFileDialog::getOpenFileName(this, "Open ELF", QString(), "ELF Files (*.elf *.bin);;All Files (*)");
    if (file_path.isEmpty()) {
        return;
    }

    QFile f(file_path);
    if (!f.open(QIODevice::ReadOnly)) {
        QMessageBox::critical(this, "Load ELF", "Failed to open file.");
        return;
    }

    const QByteArray blob = f.readAll();
    std::vector<uint8_t> bytes(static_cast<size_t>(blob.size()));
    std::copy(blob.begin(), blob.end(), bytes.begin());

    if (!runtime_.loadProgramElf(bytes, 0)) {
        QMessageBox::critical(this, "Load ELF", "Failed to load ELF image.");
        return;
    }

    setStatusMessage(QString("Loaded ELF: %1").arg(file_path));
    refreshAllViews();
}

void MainWindow::refreshAllViews() {
    refreshRegisterView();
    refreshDisassemblyView();
    refreshMemoryView();
    refreshRegionsView();
    refreshSerialView();
    if (cpu_status_) {
        cpu_status_->setText(runtime_.isRunning() ? "CPU: running" : "CPU: stopped");
    }
}

void MainWindow::refreshRegisterView() {
    if (!register_table_) return;

    const auto rows = buildRegisterRows(runtime_.registers(), runtime_.pc());
    register_table_->setRowCount(static_cast<int>(rows.size()));

    for (int i = 0; i < static_cast<int>(rows.size()); ++i) {
        register_table_->setItem(i, 0, new QTableWidgetItem(QString::fromStdString(rows[i].name)));
        register_table_->setItem(i, 1, new QTableWidgetItem(toHex64(rows[i].value)));
    }
}

void MainWindow::refreshDisassemblyView() {
    if (!disasm_table_) return;

    const uint64_t pc = runtime_.pc();
    const auto rows = buildDisassemblyWindowRows(runtime_, pc, kDisassemblyRows, 64);

    disasm_table_->setRowCount(static_cast<int>(rows.size()));
    for (int row = 0; row < static_cast<int>(rows.size()); ++row) {
        disasm_table_->setItem(row, 0, new QTableWidgetItem(rows[row].is_pc ? "▶" : ""));
        disasm_table_->setItem(row, 1, new QTableWidgetItem(toHex64(rows[row].address)));
        disasm_table_->setItem(row, 2, new QTableWidgetItem(toHex16(rows[row].raw)));
        disasm_table_->setItem(row, 3, new QTableWidgetItem(QString::fromStdString(rows[row].text)));
    }
}

void MainWindow::refreshMemoryView() {
    if (!memory_table_) return;

    bool ok = false;
    const uint64_t base = memory_base_edit_ ? memory_base_edit_->text().toULongLong(&ok, 0) : 0;
    const uint64_t start = ok ? base : 0;

    const auto rows = buildMemoryRows(runtime_, start, kMemoryRows, kBytesPerMemoryRow, runtime_.pc());
    memory_table_->setRowCount(static_cast<int>(rows.size()));
    for (int row = 0; row < static_cast<int>(rows.size()); ++row) {
        memory_table_->setItem(row, 0, new QTableWidgetItem(toHex64(rows[row].address)));
        memory_table_->setItem(row, 1, new QTableWidgetItem(QString::fromStdString(rows[row].hex_bytes)));
        memory_table_->setItem(row, 2, new QTableWidgetItem(QString::fromStdString(rows[row].ascii)));
    }
}

void MainWindow::refreshRegionsView() {
    if (!region_table_) return;

    const auto regions = buildRegionRows(runtime_.memoryRegions());
    region_table_->setRowCount(static_cast<int>(regions.size()));
    for (int i = 0; i < static_cast<int>(regions.size()); ++i) {
        region_table_->setItem(i, 0, new QTableWidgetItem(QString::fromStdString(regions[i].name)));
        region_table_->setItem(i, 1, new QTableWidgetItem(toHex64(regions[i].base)));
        region_table_->setItem(i, 2, new QTableWidgetItem(toHex64(regions[i].size)));
    }
}

void MainWindow::refreshSerialView() {
    if (!serial_output_) return;
    std::string serial_buffer;
    if (drainSerialToBuffer(runtime_, serial_buffer)) {
        serial_output_->moveCursor(QTextCursor::End);
        serial_output_->insertPlainText(QString::fromStdString(serial_buffer));
        serial_output_->moveCursor(QTextCursor::End);
    }
}
