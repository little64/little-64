# Compiler Ports for Little-64

This directory contains ports of various C compilers and language tools to the Little-64 custom ISA.

## Overview

| Compiler | Language | Status | Backend | Notes |
|----------|----------|--------|---------|-------|
| vbcc | C | **In Progress** | [vbcc/](vbcc/) | Very Basic C Compiler — recommended for initial port |
| Chibicc | C | Not started | — | Educational compiler (future comparison) |
| TCC | C | Not started | — | Tiny C Compiler (future comparison) |
| LLVM | C/C++ | Not started | — | Production compiler (future comparison) |

## Getting Started with a Compiler Port

Each compiler gets a subdirectory with:

```
compilers/<compiler>/
├── README.md          ← Setup and build instructions
├── PROGRESS.md        ← Detailed checklist of porting phases
└── target/            ← Backend files (Little-64 machine definition)
    ├── machine.h      ← Target configuration (registers, types, calling convention)
    ├── machine.c      ← Code generator and instruction selector
    └── machine.md     ← Target description for compiler tools
```

## Checking Progress

Each compiler has a `PROGRESS.md` checklist tracking phases from setup through validation.
Check these files to see:
- What's been completed
- What's currently in progress
- What's blocked or pending

## Adding a New Compiler

1. Create `compilers/<compiler>/` directory
2. Add `README.md` with setup instructions and rationale
3. Add `PROGRESS.md` with a phased breakdown
4. Create `target/` subdirectory with backend template files
5. Update this `README.md` with a new row in the table

Follow the structure of `vbcc/` as a template.
