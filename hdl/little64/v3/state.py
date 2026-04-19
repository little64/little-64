from __future__ import annotations

from enum import IntEnum


class V3PipelineState(IntEnum):
    RESET = 0
    FETCH = 1
    FETCH_TRANSLATE = 2
    DECODE = 3
    EXECUTE = 4
    MEM_TRANSLATE = 5
    MEMORY = 6
    RETIRE = 7
    INTERRUPT_VECTOR_TRANSLATE = 8
    VECTOR_LOAD = 9
    WALK = 10
    WALK_PROCESS = 11
    STALLED = 12
    HALTED = 13
    LOCKED_UP = 14


__all__ = ['V3PipelineState']