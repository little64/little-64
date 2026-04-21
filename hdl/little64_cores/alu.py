from __future__ import annotations

# Shared ALU metadata is definition-only; executable helpers now live in
# per-core helper modules under basic/, v2/, and v3/.
FLAG_Z_INDEX = 0
FLAG_C_INDEX = 1
FLAG_S_INDEX = 2
FLAGS_WIDTH = 3

__all__ = ['FLAGS_WIDTH', 'FLAG_C_INDEX', 'FLAG_S_INDEX', 'FLAG_Z_INDEX']