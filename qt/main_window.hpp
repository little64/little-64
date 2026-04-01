#pragma once

#include "../emulator/emulator_session.hpp"
#include "../frontend/debugger_execution.hpp"

#include <QMainWindow>

class QTextEdit;
class QTableWidget;
class QLabel;
class QLineEdit;
class QTimer;
class QSpinBox;

class MainWindow : public QMainWindow {
public:
    MainWindow();

private:
    void buildUi();
    void refreshAllViews();
    void refreshRegisterView();
    void refreshDisassemblyView();
    void refreshMemoryView();
    void refreshRegionsView();
    void refreshSerialView();

    void loadElfFromDialog();
    void setStatusMessage(const QString& text);

    EmulatorSession runtime_;
    DebuggerExecutionController exec_;

    QTextEdit* serial_output_ = nullptr;
    QTableWidget* register_table_ = nullptr;
    QTableWidget* disasm_table_ = nullptr;
    QTableWidget* memory_table_ = nullptr;
    QTableWidget* region_table_ = nullptr;
    QLabel* cpu_status_ = nullptr;
    QLineEdit* memory_base_edit_ = nullptr;
    QSpinBox* run_speed_spin_ = nullptr;

    QTimer* live_timer_ = nullptr;
    bool live_running_ = false;
};
