"""Emit Python entity classes from the extracted C# field layouts.

Reads the JSON produced by tools/extract_fields.py and writes one descriptor
class per entity format. Derived properties that the extractor could not parse
are added by hand in the pkm/ modules that subclass these.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# C# class -> (python base class, module the base comes from)
INHERITANCE = {
    "GBPKM": "PKM",
    "GBPKML": "GBPKM",
    "G3PKM": "PKM",
    "G4PKM": "PKM",
    "G6PKM": "PKM",
    "G8PKM": "PKM",
    "PK1": "GBPKML",
    "PK2": "GBPKML",
    "SK2": "GBPKM",
    "PK3": "G3PKM",
    "CK3": "G3PKM",
    "XK3": "G3PKM",
    "PK4": "G4PKM",
    "BK4": "G4PKM",
    "RK4": "G4PKM",
    "PK5": "PKM",
    "PK6": "G6PKM",
    "PK7": "G6PKM",
    "PB7": "G6PKM",
    "PK8": "G8PKM",
    "PB8": "G8PKM",
    "PA8": "PKM",
    "PK9": "PKM",
    "PA9": "PKM",
}

KIND_TO_CLASS = {
    "u8": "U8", "i8": "I8", "u16": "U16", "i16": "I16",
    "u32": "U32", "i32": "I32", "u64": "U64", "f32": "F32",
    "u16be": "U16BE", "u32be": "U32BE",
    "flag": "Flag", "bits": "Bits", "boolbyte": "BoolByte",
    "span": "Span", "string": "Str",
    "packed_bits": "PackedBits", "packed_flag": "PackedFlag",
}

# Acronyms and tokens that should stay glued together in snake_case.
_ACRONYM_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def to_snake(name: str) -> str:
    """PascalCase (with PKHeX's underscores and digits) to snake_case."""
    parts = [p for p in name.split("_") if p]
    out: list[str] = []
    for part in parts:
        out.extend(_ACRONYM_RE.sub(" ", part).split())
    text = "_".join(w.lower() for w in out)
    # Keep trailing digit groups attached: "Move1_PPUps" -> "move1_pp_ups"
    text = re.sub(r"_(\d+)", r"\1", text)
    return text


def render_field(spec: dict) -> str:
    cls = KIND_TO_CLASS[spec["kind"]]
    args = [f"0x{spec['offset']:X}"]
    if spec["kind"] == "flag":
        args.append(str(spec["bit"]))
    elif spec["kind"] == "bits":
        args.append(str(spec["shift"]))
        args.append(f"0x{spec['mask']:X}")
    elif spec["kind"] in ("span", "string"):
        args.append(str(spec["length"]))
    elif spec["kind"] == "packed_bits":
        args.append(str(spec["shift"]))
        args.append(f"0x{spec['mask']:X}")
        args.append(str(spec["base_size"]))
    elif spec["kind"] == "packed_flag":
        args.append(str(spec["shift"]))
        args.append(str(spec["base_size"]))

    kwargs = [f'pkhex_name="{spec["name"]}"']
    if spec["readonly"]:
        kwargs.append("readonly=True")
    if spec.get("enum"):
        kwargs.append(f'enum="{spec["enum"]}"')
    if spec.get("max_value") is not None:
        kwargs.append(f"max_value=0x{spec['max_value']:X}")
    return f"{cls}({', '.join(args + kwargs)})"


def render_class(cs_name: str, entry: dict) -> str:
    base = INHERITANCE.get(cs_name, "PKM")
    lines = [f"class {cs_name}Layout({base}Layout):" if base in INHERITANCE
             else f"class {cs_name}Layout(LayoutBase):"]
    lines[0] = f"class {cs_name}Layout({base}Layout):" if base != "PKM" else \
        f"class {cs_name}Layout(LayoutBase):"
    lines.append(f'    """Field layout for {cs_name}, generated from {cs_name}.cs."""')
    lines.append("")

    fields = entry["fields"]
    if not fields:
        lines.append("    pass")
        return "\n".join(lines) + "\n"

    # Names are defined once on Entity, reading the *_trash spans; a generated
    # descriptor here would shadow that with a different character limit.
    skip = {"nickname", "original_trainer_name", "handling_trainer_name"}
    seen: set[str] = set()
    for spec in fields:
        py = to_snake(spec["name"])
        if py in seen or py in skip:
            continue
        seen.add(py)
        lines.append(f"    {py} = {render_field(spec)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    raw = json.loads(Path(sys.argv[1]).read_text())
    order = ["GBPKM", "GBPKML", "G3PKM", "G4PKM", "G6PKM", "G8PKM",
             "PK1", "PK2", "SK2", "PK3", "CK3", "XK3",
             "PK4", "BK4", "RK4", "PK5", "PK6", "PK7", "PB7",
             "PK8", "PB8", "PA8", "PK9", "PA9"]

    out = [
        '"""Generated entity field layouts.',
        "",
        "Produced by tools/gen_pkm.py from the PKHeX reference source. Do not edit by",
        "hand; regenerate instead. Behavior that needs more than a byte offset lives in",
        "the hand-written classes that subclass these.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from .fields import (  # noqa: F401",
        "    U8, I8, U16, I16, U32, I32, U64, F32, U16BE, U32BE,",
        "    Flag, Bits, BoolByte, Span, Str, PackedBits, PackedFlag,",
        ")",
        "from .entity import Entity as LayoutBase",
        "",
        "",
    ]
    for name in order:
        entry = raw.get(name)
        if entry is None:
            continue
        out.append(render_class(name, entry))
        out.append("")
    Path(sys.argv[2]).write_text("\n".join(out))
    total = sum(len(raw[n]["fields"]) for n in order if n in raw)
    print(f"wrote {sys.argv[2]}: {len([n for n in order if n in raw])} classes, {total} fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
