"""Single-source registry for ``LITTLE64_*`` environment variables.

Every env var the CLI reads is declared here with a docstring and a default,
so there is exactly one place to document their meaning. Modules elsewhere
should read env vars via :func:`get` / :func:`get_flag` (or directly via
``os.environ`` for speed) but the **names** should always come from here to
avoid typos and drift.

The helpers are intentionally thin; this is a registry, not a framework.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EnvVar:
    name: str
    description: str
    default: str | None = None

    def get(self, env: Mapping[str, str] | None = None) -> str | None:
        environment = os.environ if env is None else env
        return environment.get(self.name, self.default)

    def get_flag(self, env: Mapping[str, str] | None = None) -> bool:
        """Read a boolean flag; truthy when value is ``"1"``."""
        return (self.get(env) or "") == "1"


# ---- Repository & build directories ----

REPO_ROOT = EnvVar(
    "LITTLE64_REPO_ROOT",
    "Override the detected repository root (normally discovered by walking up from this file).",
)
BUILDDIR = EnvVar(
    "LITTLE64_BUILDDIR",
    "Override the ``<repo>/builddir`` Meson build directory location.",
)

# ---- Linux kernel build ----

LINUX_DEFCONFIG = EnvVar(
    "LITTLE64_LINUX_DEFCONFIG",
    "Default Little64 Linux defconfig name when neither --machine nor --defconfig is given.",
)
LINUX_BUILD_DIR = EnvVar(
    "LITTLE64_LINUX_BUILD_DIR",
    "Override the kernel build output directory (otherwise derived from the profile).",
)
KERNEL_DEBUG_CFLAGS = EnvVar(
    "LITTLE64_KERNEL_DEBUG_CFLAGS",
    "KCFLAGS used for kernel debug builds when none is passed on the make command line.",
    default="-O2 -g -fno-omit-frame-pointer -fno-optimize-sibling-calls",
)

# ---- Clang-guard wrapper (kernel build) ----

CLANG_GUARD = EnvVar(
    "LITTLE64_CLANG_GUARD",
    "When ``1``, wrap the kernel-build clang invocation with ``target/linux_port/clang_guard.sh``.",
    default="0",
)
CLANG_TIMEOUT_SEC = EnvVar(
    "LITTLE64_CLANG_TIMEOUT_SEC",
    "Per-clang timeout (seconds) enforced by the clang-guard wrapper.",
    default="120",
)
CLANG_MAX_VMEM_KB = EnvVar(
    "LITTLE64_CLANG_MAX_VMEM_KB",
    "Per-clang virtual-memory cap (KB) enforced by the clang-guard wrapper.",
    default="10485760",
)
CLANG_GUARD_LOG_DIR = EnvVar(
    "LITTLE64_CLANG_GUARD_LOG_DIR",
    "Directory where the clang-guard wrapper records per-invocation logs.",
    default="/tmp/little64-clang-guard",
)

# ---- Python tooling interpreter ----

PYTHON = EnvVar(
    "LITTLE64_PYTHON",
    "Override the Python interpreter used for LiteX-backed artifact generation.",
)

# ---- LiteX profile knobs ----

LITEX_OUTPUT_DIR = EnvVar(
    "LITTLE64_LITEX_OUTPUT_DIR",
    "Override the LiteX machine profile's output directory.",
)
LITEX_RAM_SIZE = EnvVar(
    "LITTLE64_LITEX_RAM_SIZE",
    "Override RAM size passed to the LiteX SoC generator.",
)
LITEX_CPU_VARIANT = EnvVar(
    "LITTLE64_LITEX_CPU_VARIANT",
    "CPU variant selected for the LiteX SoC (default ``standard``).",
)
LITEX_TARGET = EnvVar(
    "LITTLE64_LITEX_TARGET",
    "Target platform name passed to the LiteX SoC generator.",
)
SKIP_LITEX_KERNEL_CONFIG_CHECK = EnvVar(
    "LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK",
    "When ``1``, bypass the LiteX kernel-config validation before boot/sd builds.",
)

# ---- Vivado / HDL ----

LITEX_ENV_VIVADO = EnvVar(
    "LITEX_ENV_VIVADO",
    "Directory containing Vivado's ``settings64.sh`` (sourced before ``vivado`` calls).",
)

# ---- RSP / debug ----

RSP_PORT = EnvVar(
    "LITTLE64_RSP_PORT",
    "Default RSP debug server port (subject to the 1..65535 range).",
    default="9000",
)
RSP_TRACE_PATH = EnvVar(
    "LITTLE64_RSP_TRACE_PATH",
    "Path for the RSP debug server's trace output.",
)

# ---- Rootfs build ----

ROOTFS_IMAGE = EnvVar(
    "LITTLE64_ROOTFS_IMAGE",
    "Default rootfs image used by ``little64 boot run`` when no flag overrides it.",
)
ROOTFS_SIZE_MB = EnvVar(
    "LITTLE64_ROOTFS_SIZE_MB",
    "Size in MB of the generated minimal ext4 rootfs image.",
    default="8",
)

# ---- Boot tracing / instrumentation ----

TRACE_LR = EnvVar(
    "LITTLE64_TRACE_LR",
    "Enable the targeted LR (link register) tracing window in ``boot run``.",
)
TRACE_LR_START = EnvVar(
    "LITTLE64_TRACE_LR_START",
    "Inclusive PC start bound for LR tracing.",
)
TRACE_LR_END = EnvVar(
    "LITTLE64_TRACE_LR_END",
    "Exclusive PC end bound for LR tracing.",
)
TRACE_WATCH = EnvVar(
    "LITTLE64_TRACE_WATCH",
    "Enable the targeted memory write-watch window in ``boot run``.",
)
TRACE_WATCH_START = EnvVar(
    "LITTLE64_TRACE_WATCH_START",
    "Inclusive address start bound for the memory watch window.",
)
TRACE_WATCH_END = EnvVar(
    "LITTLE64_TRACE_WATCH_END",
    "Exclusive address end bound for the memory watch window.",
)
TRACE_START_CYCLE = EnvVar(
    "LITTLE64_TRACE_START_CYCLE",
    "Inclusive cycle at which boot-event tracing begins.",
)
TRACE_END_CYCLE = EnvVar(
    "LITTLE64_TRACE_END_CYCLE",
    "Exclusive cycle at which boot-event tracing ends.",
)
BOOT_EVENTS_FILE = EnvVar(
    "LITTLE64_BOOT_EVENTS_FILE",
    "Path for the binary boot-event trace written by ``boot run --mode=trace``.",
    default="/tmp/little64_boot_events.l64t",
)
BOOT_LOG = EnvVar(
    "LITTLE64_BOOT_LOG",
    "Path for the stderr log captured by ``boot run --mode=trace``.",
    default="/tmp/little64_boot.log",
)
BOOT_EVENTS_MAX_MB = EnvVar(
    "LITTLE64_BOOT_EVENTS_MAX_MB",
    "Cap (in MB) for the boot-event trace file before it is truncated.",
    default="500",
)

# ---- Global CLI flags (consumed by little64/proc.py) ----

VERBOSE = EnvVar(
    "LITTLE64_VERBOSE",
    "When ``1``, echo every tool shell-out before it runs.",
)
DRY_RUN = EnvVar(
    "LITTLE64_DRY_RUN",
    "When ``1``, echo every tool shell-out but skip execution.",
)
