# Compiler Ports for Little-64

This directory contains ports of various C compilers and language tools to the Little-64 custom ISA.

## Overview

| Compiler | Language | Status | Backend | Notes |
|----------|----------|--------|---------|-------|
| LLVM | C/C++ | **Working** | — | Production compiler |
| lily-cc | C | **In Progress** | [lily-cc/](lily-cc/) | Active development, working Little-64 backend |
| Chibicc | C | Not started | — | Educational compiler (future comparison) |
| TCC | C | Not started | — | Tiny C Compiler (future comparison) |

## Building

Use the build orchestrator from this directory:

```bash
./build.sh lily-cc        # build lily-cc
./build.sh all            # build all compilers
./build.sh clean lily-cc  # clean lily-cc artifacts
./build.sh clean          # clean all
ENABLE_LLDB=1 ./build.sh llvm  # Build LLVM toolchain with LLDB + LLDB-DAP
```

Compiled binaries are placed in `bin/`.

## Getting Started with a Compiler Port

Each compiler gets a subdirectory with a `build.sh` that the orchestrator delegates to.

## Adding a New Compiler

1. Create `compilers/<compiler>/` directory
2. Add `README.md` with setup instructions and rationale
3. Add `build.sh` implementing the `[TARGET] [ACTION]` interface
4. Update this `README.md` with a new row in the table
