"""Single source of truth for machine profiles and defconfig resolution.

Before this module existed, the same information lived in at least three
places: ``paths.py`` (BUILD_DIR_ALIASES), ``commands/kernel/build.py``
(MACHINE_DEFCONFIGS), and ``litex_boot_support.py`` (DEFAULT_LITEX_*).
Adding a new machine profile meant touching every call-site. All of those
modules now import from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_MACHINE = "litex"
DEFAULT_DEFCONFIG_NAME = "little64_litex_sim_defconfig"


@dataclass(frozen=True, slots=True)
class MachineProfile:
    name: str
    defconfig: str
    build_dir_name: str
    cpu_variant: str
    litex_target: str
    output_dirname: str


MACHINE_PROFILES: dict[str, MachineProfile] = {
    "litex": MachineProfile(
        name="litex",
        defconfig="little64_litex_sim_defconfig",
        build_dir_name="build-litex",
        cpu_variant="standard",
        litex_target="arty-a7-35",
        output_dirname="boot-direct-litex",
    ),
}


def available_machines() -> tuple[str, ...]:
    return tuple(sorted(MACHINE_PROFILES))


def get_machine_profile(machine: str) -> MachineProfile:
    try:
        return MACHINE_PROFILES[machine]
    except KeyError as exc:
        raise ValueError(f"Unsupported machine profile: {machine}") from exc


def default_defconfig_for_machine(machine: str) -> str:
    return get_machine_profile(machine).defconfig


def build_dir_name_for_defconfig(defconfig_name: str) -> str:
    for profile in MACHINE_PROFILES.values():
        if profile.defconfig == defconfig_name:
            return profile.build_dir_name
    return f"build-{defconfig_name}"


def resolve_defconfig(
    *,
    machine: str | None = None,
    defconfig: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Pick a defconfig name.

    Precedence: explicit ``defconfig`` > ``machine`` lookup > env var > default.
    """
    environment = os.environ if env is None else env
    if defconfig:
        return defconfig
    if machine:
        return default_defconfig_for_machine(machine)
    return environment.get("LITTLE64_LINUX_DEFCONFIG", DEFAULT_DEFCONFIG_NAME)
