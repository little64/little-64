# Compiler Toolchains for Little-64

This directory hosts compiler/toolchain ports used by Little-64.

## Layout

- `llvm/` — LLVM-based toolchain and backend work
- `lily-cc/` — Lily-CC port work
- `bin/` — exported compiler/debugger binaries for project workflows
- `build.sh` — build orchestrator that delegates to per-toolchain scripts

## Separation Policy

LLVM and Lily-CC trees are intentionally independent.

- Keep `llvm/` and `lily-cc/` separate.
- Do not collapse their build scripts or source trees into a shared layout.
- Shared output is allowed only through `bin/`.

## Build Orchestrator

From `compilers/`:

```bash
./build.sh help
./build.sh llvm
./build.sh lily-cc
./build.sh all
./build.sh clean
./build.sh clean llvm
```

LLVM path always includes LLDB tools:

```bash
./build.sh llvm
```

## Expected Output

Compiler and debugger binaries are exported to:

- `compilers/bin/clang`
- `compilers/bin/ld.lld`
- `compilers/bin/llvm-mc`
- `compilers/bin/lldb`
- `compilers/bin/lldb-dap`

## Adding a New Compiler Port

1. Add `compilers/<name>/build.sh` with the same command contract used by `build.sh`.
2. Add `compilers/<name>/README.md` describing status and usage.
3. Ensure produced binaries are copied/symlinked into `compilers/bin/` when appropriate.
4. Update this file with a new section and command examples.

## Update Checklist

When changing any compiler build flow:

- verify `./build.sh help` output remains accurate,
- verify at least one real build command succeeds,
- update command examples here,
- update project-level docs if toolchain invocation changes.
