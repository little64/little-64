# vbcc Backend for Little-64

## Overview

This directory contains the Little-64 backend for **vbcc** (Very Basic C Compiler).

vbcc is a small, modular C compiler with excellent documentation for adding new backends.
It was chosen for the initial Little-64 compiler port because:

- **Small codebase** (~100K LOC) — easier to understand than LLVM or GCC
- **Excellent backend documentation** — Section 13 of the vbcc manual is thorough
- **Modular architecture** — clean separation between frontend and backend
- **Proven track record** — existing backends for M68k, PowerPC, 6502, VideoCore, and others
- **Good code quality** — suitable for kernel-level code
- **Quick to port** — realistic 4–6 week timeline for a working compiler

## Project Structure

```
vbcc/
├── README.md              ← This file
├── PROGRESS.md            ← Detailed phased checklist
├── target/                ← Little-64 backend implementation
│   ├── machine.h          ← Register definitions, type sizes, calling convention
│   ├── machine.c          ← Instruction selector and code generator
│   └── machine.md         ← Target description (input to vbcc tools)
└── vbcc/                  ← vbcc source code (git submodule)
```

## Getting vbcc Source

The vbcc source code is maintained by Volker Barthelmann and distributed as a **tarball snapshot**
(not an official git repository). The latest source can be downloaded from:

**Official vbcc website:** http://www.compilers.de/vbcc.html

### Setup Instructions

1. **Download the latest vbcc snapshot:**
   ```bash
   # Visit http://www.compilers.de/vbcc.html to find the latest version
   # Download vbcc-<version>.tar.gz
   # Example:
   wget http://www.compilers.de/download/vbcc-<latest-version>.tar.gz
   ```

2. **Extract into the submodule directory:**
   ```bash
   cd /home/alexander/projects/little-64
   mkdir -p compilers/vbcc/vbcc
   tar -xzf vbcc-<latest-version>.tar.gz -C compilers/vbcc/vbcc --strip-components=1
   ```

3. **Create a git submodule to track the snapshot:**
   The submodule is already initialized in the repository. It points to a snapshot
   of vbcc committed as a subtree rather than a remote git repository.

4. **Verify the submodule:**
   ```bash
   git submodule status
   ```

## Building vbcc with the Little-64 Backend

Once vbcc source is present in `compilers/vbcc/vbcc/`:

1. **Read the vbcc manual** (bundled in the source):
   ```bash
   cat compilers/vbcc/vbcc/doc/vbcc.pdf
   # Or read Section 13 for backend porting guide
   ```

2. **Copy Little-64 backend files to vbcc**:
   ```bash
   cp compilers/vbcc/target/machine.h compilers/vbcc/vbcc/machines/
   cp compilers/vbcc/target/machine.c compilers/vbcc/vbcc/machines/
   cp compilers/vbcc/target/machine.md compilers/vbcc/vbcc/machines/
   ```

3. **Build vbcc**:
   ```bash
   cd compilers/vbcc/vbcc
   make
   ```

4. **Test compilation**:
   ```bash
   ./bin/vbcc -target=little64 test.c -o test.s
   ```

## Porting Progress

See [PROGRESS.md](PROGRESS.md) for a detailed checklist of porting phases.

Current status:
- **Phase 0 (Setup)** — Ready to start
- **Phase 1 (Skeleton)** — Pending
- **Phase 2 (Code Generation)** — Pending
- **Phase 3 (Libcalls)** — Pending
- **Phase 4 (Validation)** — Pending
- **Phase 5 (Kernel)** — Pending

## Backend Files

### `machine.h`

Defines the target architecture for vbcc:
- Register names and IDs
- Type sizes (int, short, long, pointer)
- Calling convention (argument passing, return values)
- Addressing mode constraints
- Special register usage (stack pointer, frame pointer)

### `machine.c`

Implements the code generator:
- Instruction selection (IR patterns → Little-64 instructions)
- Register allocation
- Stack frame management
- Function prologue/epilogue

### `machine.md`

A machine description file that vbcc tools use to understand the target:
- Instruction patterns
- Operand constraints
- Register usage rules

## References

- **vbcc Backend Manual**: `compilers/vbcc/vbcc/doc/vbcc.pdf` Section 13 (Writing a Backend)
- **Little-64 ISA**: `CPU_ARCH.md` and `docs/assembly-syntax.md`
- **Example Backends**: Study `compilers/vbcc/vbcc/machines/m68k.h` and `m68k.c` for reference
- **Official vbcc Website**: http://www.compilers.de/vbcc.html (maintained by Volker Barthelmann)

## Troubleshooting

### vbcc source not found

```
error: directory 'compilers/vbcc/vbcc' does not exist
```

**Fix**: Download vbcc and extract it:
```bash
cd /home/alexander/projects/little-64
wget http://www.compilers.de/download/vbcc-<latest>.tar.gz
mkdir -p compilers/vbcc/vbcc
tar -xzf vbcc-<latest>.tar.gz -C compilers/vbcc/vbcc --strip-components=1
```

### Backend files not found

Ensure `machine.h`, `machine.c`, and `machine.md` are copied to `compilers/vbcc/vbcc/machines/` before building.

### Build errors

Check the vbcc manual (Section 13) for required function signatures and data structures.
The error message will typically indicate which function is missing or malformed.

## Next Steps

1. Read PROGRESS.md and start Phase 0 (setup)
2. Initialize the git submodule
3. Study the vbcc manual and an existing backend
4. Begin Phase 1 (skeleton backend)
