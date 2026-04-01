#!/usr/bin/env python3
import argparse
from pathlib import Path


def snake_case(name: str) -> str:
    out = []
    for idx, ch in enumerate(name):
        if ch.isupper() and idx > 0 and not name[idx - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a new Little-64 MMIO device skeleton")
    parser.add_argument("name", help="Device class name, e.g. TimerDevice")
    parser.add_argument("--base", default="0xFFFFFFFFFFFF1000", help="Default MMIO base constant")
    parser.add_argument("--size", default="8", help="MMIO size in bytes")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    emulator_dir = root / "emulator"

    class_name = args.name
    stem = snake_case(class_name)
    header_path = emulator_dir / f"{stem}.hpp"
    source_path = emulator_dir / f"{stem}.cpp"

    if header_path.exists() or source_path.exists():
        raise SystemExit(f"Refusing to overwrite existing files: {header_path.name} / {source_path.name}")

    header = f'''#pragma once

#include "device.hpp"
#include <string>

class {class_name} : public Device {{
public:
    static constexpr uint64_t DEFAULT_BASE = {args.base};
    static constexpr uint64_t DEFAULT_SIZE = {args.size};

    explicit {class_name}(uint64_t base = DEFAULT_BASE, std::string_view name = "{class_name.upper()}");

    uint8_t read8(uint64_t addr) override;
    void    write8(uint64_t addr, uint8_t val) override;

    void reset() override;
    void tick() override;

    std::string_view name() const override {{ return _name; }}

private:
    std::string _name;
}};
'''

    source = f'''#include "{stem}.hpp"

{class_name}::{class_name}(uint64_t base, std::string_view name)
    : Device(base, DEFAULT_SIZE), _name(name) {{
}}

uint8_t {class_name}::read8(uint64_t addr) {{
    switch (addr - _base) {{
        default:
            return 0xFF;
    }}
}}

void {class_name}::write8(uint64_t addr, uint8_t val) {{
    (void)addr;
    (void)val;
}}

void {class_name}::reset() {{
}}

void {class_name}::tick() {{
}}
'''

    header_path.write_text(header)
    source_path.write_text(source)

    print(f"Created {header_path.relative_to(root)}")
    print(f"Created {source_path.relative_to(root)}")
    print("Next steps:")
    print(f"  1) Add {source_path.relative_to(root)} to core_emulator_src in meson.build")
    print(f"  2) Register {class_name} in MachineConfig")
    print(f"  3) Add tests in tests/test_devices.cpp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
