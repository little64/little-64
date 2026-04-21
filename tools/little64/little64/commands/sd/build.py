"""Build the Little64 SD boot artifacts (stage-0 + SD image)."""

from __future__ import annotations

from typing import List

from little64 import sd


def run(argv: List[str]) -> int:
    return sd.run(argv)
