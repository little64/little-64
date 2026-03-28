# Getting Started with vbcc Porting

Quick reference for starting the vbcc backend porting effort.

## Quick Start

1. **Navigate to the vbcc directory:**
   ```bash
   cd compilers/vbcc
   ```

2. **Read the overview:**
   ```bash
   cat README.md
   ```

3. **Check the progress checklist:**
   ```bash
   cat PROGRESS.md
   ```

4. **Start Phase 0 (Setup):**
   - Download vbcc from http://www.compilers.de/vbcc.html
   - Extract into `compilers/vbcc/vbcc/` directory
   - Read Section 13 of the vbcc manual (`compilers/vbcc/vbcc/doc/vbcc.pdf`)
   - Study the M68k or PowerPC backend for reference

## Directory Layout

```
compilers/
├── README.md             ← Overview of all compiler ports
├── SETUP.md              ← This file
└── vbcc/
    ├── README.md         ← vbcc backend overview and build instructions
    ├── PROGRESS.md       ← Detailed 5-phase checklist
    ├── target/           ← Backend implementation (Little-64 machine definition)
    │   ├── machine.h     ← Register file, types, calling convention
    │   ├── machine.c     ← Code generator skeleton
    │   └── machine.md    ← Target description for vbcc
    └── vbcc/             ← vbcc source (git submodule, not yet cloned)
```

## Key Files

| File | Purpose |
|------|---------|
| `compilers/README.md` | Index of all compiler ports and their status |
| `compilers/vbcc/README.md` | vbcc-specific setup and build instructions |
| `compilers/vbcc/PROGRESS.md` | Phase-by-phase checklist of porting work |
| `compilers/vbcc/target/machine.h` | Target architecture definition (registers, types, ABI) |
| `compilers/vbcc/target/machine.c` | Code generation implementation skeleton |
| `compilers/vbcc/target/machine.md` | vbcc target description (machine-readable) |

## Key Little-64 Documentation

- **ISA Reference**: `CPU_ARCH.md` — Full instruction set, registers, calling convention
- **Assembly Syntax**: `docs/assembly-syntax.md` — Assembler language reference
- **Developer Guide**: `CLAUDE.md` — How to modify instructions and the assembler

## Next Steps

1. Read `compilers/vbcc/README.md`
2. Download vbcc from http://www.compilers.de/vbcc.html
3. Extract into `compilers/vbcc/vbcc/`
4. Open `PROGRESS.md` and start Phase 0
5. Document your progress in `PROGRESS.md` as you complete checklist items

## Useful Commands

**Check submodule status:**
```bash
git submodule status
```

**Update to a newer vbcc snapshot:**
1. Download the new vbcc tarball from http://www.compilers.de/vbcc.html
2. Extract over the existing `compilers/vbcc/vbcc/` directory
3. Commit the updated submodule

**Track progress:**
Edit `PROGRESS.md` and check off completed items as you go.

## Phases at a Glance

| Phase | Focus | Time | Blocker |
|-------|-------|------|---------|
| 0 | Setup & learning | 1–2 weeks | None |
| 1 | Minimal backend | 1–2 weeks | vbcc source |
| 2 | Real code generation | 2–3 weeks | Phase 1 |
| 3 | Libcalls (__muldi3, etc) | 1 week | Phase 2 |
| 4 | Validation (test compilation) | 2–3 weeks | Phase 3 |
| 5 | Kernel readiness | 1–2 weeks | Phase 4 |

**Total estimate: 8–14 weeks** for a full kernel-ready compiler.

Each phase builds on the previous one. Completion is tracked in `PROGRESS.md`.
