#include "emulator_session.hpp"
#include "headless_runtime.hpp"
#include <csignal>
#include <iomanip>
#include <iostream>
#include <string>

namespace {
volatile std::sig_atomic_t g_stop_signal = 0;

void onSignal(int signal_number) {
    g_stop_signal = signal_number;
}

void dumpFinalRegisters(EmulatorSession& runtime, const char* reason) {
    const RegisterSnapshot regs = runtime.registers();
    auto print_hex = [](const char* name, uint64_t value) {
        std::cerr << "  " << std::left << std::setw(24) << name
                  << " = 0x" << std::hex << std::setw(16) << std::setfill('0')
                  << value << std::dec << std::setfill(' ') << "\n";
    };

    std::cerr << "[little64] final-registers: " << reason << "\n";
    for (int i = 0; i < 16; ++i) {
        std::string name = "R" + std::to_string(i);
        print_hex(name.c_str(), regs.gpr[i]);
    }

    print_hex("flags", regs.flags);
    print_hex("cpu_control", regs.cpu_control);
    print_hex("interrupt_table_base", regs.interrupt_table_base);
    print_hex("interrupt_mask", regs.interrupt_mask);
    print_hex("interrupt_states", regs.interrupt_states);
    print_hex("interrupt_epc", regs.interrupt_epc);
    print_hex("interrupt_eflags", regs.interrupt_eflags);
    print_hex("trap_cause", regs.trap_cause);
    print_hex("trap_fault_addr", regs.trap_fault_addr);
    print_hex("trap_access", regs.trap_access);
    print_hex("trap_pc", regs.trap_pc);
    print_hex("trap_aux", regs.trap_aux);
    print_hex("page_table_root_phys", regs.page_table_root_physical);
    print_hex("boot_info_frame_phys", regs.boot_info_frame_physical);
    print_hex("boot_source_page_size", regs.boot_source_page_size);
    print_hex("boot_source_page_count", regs.boot_source_page_count);
    print_hex("hypercall_caps", regs.hypercall_caps);
}
} // namespace

static void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0
              << " [-h | --help] [--boot-mode=auto|bios|direct] [--max-cycles=N] [--trace-mmio] [--boot-events] [--final-registers]"
              << " <binary.bin|object.o>\n"
              << "  Runs the assembled binary/ELF object and prints any serial (UART) output to stdout.\n"
              << "  --max-cycles=N   Stop after N cycles and dump boot event log.\n"
              << "  --trace-mmio     Log every MMIO read/write to stderr.\n"
              << "  --boot-events    Always dump boot event log to stderr on exit.\n"
              << "  --final-registers Dump final register state to stderr on exit.\n"
              << "  -h | --help        Show this help message.\n";
}

int main(int argc, char* argv[]) {
    if (argc < 2 || (std::string(argv[1]) == "--help") || (std::string(argv[1]) == "-h")) {
        printUsage(argv[0]);
        return 1;
    }

    HeadlessLoadOptions load_options;
    HeadlessRunOptions  run_options;
    std::string image_path;
    bool trace_mmio   = false;
    bool boot_events  = false;
    bool final_registers = false;

    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg.rfind("--boot-mode=", 0) == 0) {
            const std::string mode = arg.substr(std::string("--boot-mode=").size());
            if (mode == "auto") load_options.boot_mode = HeadlessBootMode::Auto;
            else if (mode == "bios") load_options.boot_mode = HeadlessBootMode::Bios;
            else if (mode == "direct") load_options.boot_mode = HeadlessBootMode::Direct;
            else {
                std::cerr << "Error: invalid --boot-mode value '" << mode << "'\n";
                printUsage(argv[0]);
                return 1;
            }
            continue;
        }
        if (arg.rfind("--max-cycles=", 0) == 0) {
            try {
                run_options.max_cycles = std::stoull(arg.substr(std::string("--max-cycles=").size()));
            } catch (...) {
                std::cerr << "Error: invalid --max-cycles value\n";
                return 1;
            }
            boot_events = true;  // always dump events when a cycle limit is set
            final_registers = true; // emit final state on forced stop paths
            continue;
        }
        if (arg == "--trace-mmio") { trace_mmio  = true; continue; }
        if (arg == "--boot-events") {
            boot_events = true;
            final_registers = true;
            continue;
        }
        if (arg == "--final-registers") { final_registers = true; continue; }

        if (!image_path.empty()) {
            std::cerr << "Error: multiple image paths provided\n";
            printUsage(argv[0]);
            return 1;
        }
        image_path = arg;
    }

    if (image_path.empty()) {
        printUsage(argv[0]);
        return 1;
    }

    EmulatorSession runtime;
    std::string error;
    if (!loadRuntimeImageFromPath(runtime, image_path, error, load_options)) {
        std::cerr << error << "\n";
        return 1;
    }

    if (trace_mmio)
        runtime.setMmioTrace(true);

    run_options.stop_signal = &g_stop_signal;
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);

    const int result = runRuntimeUntilStop(runtime, run_options, error);
    if (!error.empty())
        std::cerr << error << "\n";

    if (boot_events || result != 0)
        runtime.dumpBootLog(g_stop_signal != 0 ? "signal" : "exit");

    if (final_registers)
        dumpFinalRegisters(runtime, g_stop_signal != 0 ? "signal" : "exit");

    return result;
}
