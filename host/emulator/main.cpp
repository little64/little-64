#include "emulator_session.hpp"
#include "headless_runtime.hpp"
#include "disk_image.hpp"
#include "trace_writer.hpp"
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
                  << " = 0x" << std::right << std::hex << std::setw(16) << std::setfill('0')
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
    print_hex("interrupt_mask_high", regs.interrupt_mask_high);
    print_hex("interrupt_states_high", regs.interrupt_states_high);
    print_hex("interrupt_epc", regs.interrupt_epc);
    print_hex("interrupt_eflags", regs.interrupt_eflags);
    print_hex("interrupt_cpu_ctrl", regs.interrupt_cpu_control);
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
              << " [-h | --help] [--boot-mode=auto|bios|direct|litex-bootrom|litex-flash] [--disk=PATH] [--disk-readonly] [--direct-kernel-physical-base=ADDR] [--direct-dtb=PATH] [--direct-stack-reserve-bytes=N] [--max-cycles=N] [--trace-mmio] [--trace-control-flow] [--boot-events] [--boot-events-file=PATH] [--boot-events-max-mb=N] [--trace-start-cycle=N] [--trace-end-cycle=N] [--final-registers]"
              << " <binary.bin|object.o>\n"
              << "  Runs the assembled binary/ELF object and prints any serial (UART) output to stdout.\n"
              << "  --boot-mode=direct uses the LiteX-compatible direct-entry Linux loader and DTB contract.\n"
              << "  --boot-mode=litex-bootrom expects a raw LiteX bootrom image and boots it with the LiteX bootrom/UART map.\n"
              << "  --boot-mode=litex-flash expects a raw LiteX SPI flash image and boots it with the LiteX flash/UART map.\n"
              << "  --direct-kernel-physical-base=ADDR  Physical load base for --boot-mode=direct (default 0x40000000).\n"
              << "  --direct-dtb=PATH  Use PATH DTB bytes for --boot-mode=direct instead of the embedded DTB.\n"
              << "  --direct-stack-reserve-bytes=N  Reserve N bytes below RAM top for SP in --boot-mode=direct.\n"
              << "  --max-cycles=N   Stop after N cycles and dump boot event log.\n"
              << "  --disk=PATH      Attach PATH as the emulated root disk image.\n"
              << "  --disk-readonly  Expose the attached disk as read-only.\n"
              << "  --trace-mmio     Log mapped device MMIO reads/writes to stderr.\n"
              << "  --trace-control-flow  Record non-fallthrough PC changes into boot events.\n"
              << "  --boot-events    Always dump boot event log to stderr on exit.\n"
              << "  --boot-events-file=PATH  Stream full boot event history to PATH (binary L64T format).\n"
              << "                   Use `little64 trace` to decode binary traces.\n"
              << "  --boot-events-max-mb=N   Cap trace file at N megabytes (default: unlimited).\n"
              << "  --trace-start-cycle=N    Only trace events at or after cycle N.\n"
              << "  --trace-end-cycle=N      Only trace events at or before cycle N.\n"
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
    bool trace_control_flow = false;
    bool boot_events  = false;
    bool final_registers = false;
    std::string disk_path;
    bool disk_read_only = false;
    std::string boot_events_file;
    uint64_t boot_events_max_mb = 0;
    uint64_t trace_start_cycle = 0;
    uint64_t trace_end_cycle = UINT64_MAX;

    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg.rfind("--boot-mode=", 0) == 0) {
            const std::string mode = arg.substr(std::string("--boot-mode=").size());
            if (mode == "auto") load_options.boot_mode = HeadlessBootMode::Auto;
            else if (mode == "bios") load_options.boot_mode = HeadlessBootMode::Bios;
            else if (mode == "direct") load_options.boot_mode = HeadlessBootMode::Direct;
            else if (mode == "litex-bootrom") load_options.boot_mode = HeadlessBootMode::LiteXBootRom;
            else if (mode == "litex-flash") load_options.boot_mode = HeadlessBootMode::LiteXFlash;
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
        if (arg.rfind("--direct-kernel-physical-base=", 0) == 0) {
            try {
                load_options.direct_kernel_physical_base = std::stoull(
                    arg.substr(std::string("--direct-kernel-physical-base=").size()),
                    nullptr,
                    0);
            } catch (...) {
                std::cerr << "Error: invalid --direct-kernel-physical-base value\n";
                return 1;
            }
            continue;
        }
        if (arg.rfind("--direct-dtb=", 0) == 0) {
            load_options.direct_dtb_path = arg.substr(std::string("--direct-dtb=").size());
            if (load_options.direct_dtb_path.empty()) {
                std::cerr << "Error: --direct-dtb requires a non-empty path\n";
                return 1;
            }
            continue;
        }
        if (arg.rfind("--direct-stack-reserve-bytes=", 0) == 0) {
            try {
                load_options.direct_stack_reserve_bytes = std::stoull(
                    arg.substr(std::string("--direct-stack-reserve-bytes=").size()),
                    nullptr,
                    0);
            } catch (...) {
                std::cerr << "Error: invalid --direct-stack-reserve-bytes value\n";
                return 1;
            }
            continue;
        }
        if (arg.rfind("--disk=", 0) == 0) {
            disk_path = arg.substr(std::string("--disk=").size());
            if (disk_path.empty()) {
                std::cerr << "Error: --disk requires a non-empty path\n";
                return 1;
            }
            continue;
        }
        if (arg == "--disk-readonly") {
            disk_read_only = true;
            continue;
        }
        if (arg.rfind("--boot-events-file=", 0) == 0) {
            boot_events_file = arg.substr(std::string("--boot-events-file=").size());
            if (boot_events_file.empty()) {
                std::cerr << "Error: --boot-events-file requires a non-empty path\n";
                return 1;
            }
            continue;
        }
        if (arg == "--trace-mmio") { trace_mmio  = true; continue; }
        if (arg == "--trace-control-flow") { trace_control_flow = true; continue; }
        if (arg == "--boot-events") {
            boot_events = true;
            final_registers = true;
            continue;
        }
        if (arg == "--final-registers") { final_registers = true; continue; }
        if (arg.rfind("--boot-events-max-mb=", 0) == 0) {
            try {
                boot_events_max_mb = std::stoull(arg.substr(std::string("--boot-events-max-mb=").size()));
            } catch (...) {
                std::cerr << "Error: invalid --boot-events-max-mb value\n";
                return 1;
            }
            continue;
        }
        if (arg.rfind("--trace-start-cycle=", 0) == 0) {
            try {
                trace_start_cycle = std::stoull(arg.substr(std::string("--trace-start-cycle=").size()));
            } catch (...) {
                std::cerr << "Error: invalid --trace-start-cycle value\n";
                return 1;
            }
            continue;
        }
        if (arg.rfind("--trace-end-cycle=", 0) == 0) {
            try {
                trace_end_cycle = std::stoull(arg.substr(std::string("--trace-end-cycle=").size()));
            } catch (...) {
                std::cerr << "Error: invalid --trace-end-cycle value\n";
                return 1;
            }
            continue;
        }

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
    if (!disk_path.empty()) {
        auto disk = DiskImage::open(disk_path, disk_read_only);
        if (!disk || !disk->isValid() || !disk->lastError().empty()) {
            std::cerr << "Error: failed to attach disk image: "
                      << (disk ? disk->lastError() : std::string("unknown error")) << "\n";
            return 1;
        }
        runtime.setDiskImage(std::move(disk));
    }
    std::string error;
    if (!loadRuntimeImageFromPath(runtime, image_path, error, load_options)) {
        std::cerr << error << "\n";
        return 1;
    }

    if (trace_mmio)
        runtime.setMmioTrace(true);
    if (trace_control_flow)
        runtime.setControlFlowTrace(true);
    bool boot_events_stream_ok = false;
    if (!boot_events_file.empty()) {
        TraceWriter::Config tc;
        tc.path = boot_events_file;
        tc.max_bytes = boot_events_max_mb > 0
            ? boot_events_max_mb * 1024ULL * 1024ULL : 0;
        tc.start_cycle = trace_start_cycle;
        tc.end_cycle = trace_end_cycle;
        auto writer = std::make_unique<TraceWriter>(std::move(tc));
        if (writer->open()) {
            boot_events_stream_ok = true;
            runtime.setTraceWriter(std::move(writer));
        } else {
            std::cerr << "[little64] warning: failed to open boot events stream file: " << boot_events_file << "\n";
        }
    }

    run_options.stop_signal = &g_stop_signal;
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);

    const int result = runRuntimeUntilStop(runtime, run_options, error);
    if (!error.empty())
        std::cerr << error << "\n";

    const char* exit_reason = g_stop_signal != 0 ? "signal" : "exit";

    if (!boot_events_file.empty() && !boot_events_stream_ok &&
        !runtime.dumpBootLogToFile(exit_reason, boot_events_file)) {
        std::cerr << "[little64] warning: failed to write boot events fallback file: " << boot_events_file << "\n";
    }

    if (boot_events || result != 0)
        runtime.dumpBootLog(exit_reason);

    if (final_registers)
        dumpFinalRegisters(runtime, exit_reason);

    return result;
}
