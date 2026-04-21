from __future__ import annotations

from amaranth import Elaboratable

from .basic import Little64BasicCore
from .basic.core import CoreState
from .config import Little64CoreConfig
from .variants import create_core


def Little64Core(config: Little64CoreConfig | None = None) -> Elaboratable:
	return create_core(config)

__all__ = ['CoreState', 'Little64BasicCore', 'Little64Core']