"""``little64 hdl`` — HDL/LiteX bitstream, simulation, and export tooling.

Each subcommand module under this package owns the LiteX/Amaranth imports
for its own operation.
"""

from __future__ import annotations

from typing import List

from little64.commands._group import SubcommandSpec, dispatch


_SUBCOMMANDS: tuple[SubcommandSpec, ...] = (
    ("arty-build", "arty_build", "Build a LiteX Arty A7-35T bitstream (optionally program it)."),
    ("arty-ila", "arty_ila", "Insert/capture a Vivado ILA against an Arty build."),
    ("arty-patch-bootrom", "arty_patch_bootrom", "Patch the integrated bootrom of an existing Arty build."),
    ("flash-image", "flash_image", "Build a LiteX SPI-flash image (stage-0 + Linux + DTB)."),
    ("dts-linux", "dts_linux", "Emit a Linux DTS for the LiteX SoC shape."),
    ("wrappers-llvm", "wrappers_llvm", "Emit LiteX-compatible triple-prefixed LLVM tool wrappers."),
    ("export-cpu", "export_cpu", "Export the generic LiteX CPU wrapper to Verilog."),
    ("export-core", "export_core", "Export the Little64 CPU core to Verilog."),
    ("export-linux-boot", "export_linux_boot", "Export the Linux-boot top-level to Verilog."),
    ("sim-litex", "sim_litex", "Run the LiteX-native Linux boot smoke."),
)


def run(argv: List[str]) -> int:
    return dispatch(
        argv,
        prog="little64 hdl",
        description="HDL/LiteX bitstream, simulation, and export helpers.",
        package="little64.commands.hdl",
        subcommands=_SUBCOMMANDS,
    )
