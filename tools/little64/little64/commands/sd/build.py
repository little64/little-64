"""Build the Little64 SD boot artifacts (stage-0 + SD image)."""

from __future__ import annotations

from typing import List

import little64.commands.sd.artifacts as artifacts


def run(argv: List[str]) -> int:
    return artifacts.run(argv)
