from __future__ import annotations

from .basic import Little64BasicCore
from .config import CACHE_TOPOLOGIES, CORE_VARIANTS, Little64CoreConfig
from .v2 import Little64V2Core


LITEX_CPU_VARIANT_CONFIGS = {
    'standard': ('basic', 'none'),
    'standard-basic': ('basic', 'none'),
    'standard-v2': ('v2', 'none'),
    'standard-v2-none': ('v2', 'none'),
    'standard-v2-unified': ('v2', 'unified'),
    'standard-v2-split': ('v2', 'split'),
}


def core_class_for_variant(core_variant: str):
    if core_variant == 'basic':
        return Little64BasicCore
    if core_variant == 'v2':
        return Little64V2Core
    raise ValueError(f'Unsupported Little64 core variant: {core_variant}')


def create_core(config: Little64CoreConfig | None = None):
    resolved_config = config or Little64CoreConfig()
    return core_class_for_variant(resolved_config.core_variant)(resolved_config)


def resolve_litex_core_variant(cpu_variant: str) -> str:
    try:
        return LITEX_CPU_VARIANT_CONFIGS[cpu_variant][0]
    except KeyError as exc:
        raise ValueError(f'Unsupported Little64 LiteX CPU variant: {cpu_variant}') from exc


def resolve_litex_cache_topology(cpu_variant: str) -> str:
    try:
        return LITEX_CPU_VARIANT_CONFIGS[cpu_variant][1]
    except KeyError as exc:
        raise ValueError(f'Unsupported Little64 LiteX CPU variant: {cpu_variant}') from exc


def config_for_litex_variant(cpu_variant: str, *, reset_vector: int = 0) -> Little64CoreConfig:
    return Little64CoreConfig(
        reset_vector=reset_vector,
        core_variant=resolve_litex_core_variant(cpu_variant),
        cache_topology=resolve_litex_cache_topology(cpu_variant),
    )


__all__ = [
    'CACHE_TOPOLOGIES',
    'CORE_VARIANTS',
    'LITEX_CPU_VARIANT_CONFIGS',
    'Little64BasicCore',
    'Little64V2Core',
    'config_for_litex_variant',
    'core_class_for_variant',
    'create_core',
    'resolve_litex_cache_topology',
    'resolve_litex_core_variant',
]