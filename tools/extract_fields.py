"""Extract byte-offset field definitions from PKHeX's C# entity classes.

Each PKx.cs is largely a wall of one-line properties that read and write a fixed
offset. Parsing them mechanically keeps the Python layout tables honest: a field
either matches a recognized C# pattern or it is reported as unhandled, so nothing
is silently dropped.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# One-line property: "public [override|virtual|new] TYPE Name { get => ...; set => ...; }"
PROPERTY_RE = re.compile(
    r"^\s*(?P<vis>public|private|internal|protected)\s+(?:override\s+|virtual\s+|new\s+|sealed\s+)*"
    r"(?P<type>[\w\.<>\?\[\]]+)\s+(?P<name>\w+)\s*\{\s*"
    r"get\s*=>\s*(?P<get>.+?);\s*"
    r"(?:set\s*(?:=>|\{)\s*(?P<set>.+?);?\s*\}?\s*)?"
    r"\}\s*$"
)

GET_ONLY_RE = re.compile(
    r"^\s*(?P<vis>public|private|internal|protected)\s+(?:override\s+|virtual\s+|new\s+|sealed\s+)*"
    r"(?P<type>[\w\.<>\?\[\]]+)\s+(?P<name>\w+)\s*=>\s*(?P<get>.+?);\s*$"
)

HEX = r"(?:0x[0-9A-Fa-f]+|0b[01_]+|\d+)"


def _num(text: str) -> int:
    return int(text.replace("_", ""), 0)


@dataclass
class FieldSpec:
    name: str
    kind: str
    offset: int
    cs_type: str
    readonly: bool = False
    shift: int | None = None
    mask: int | None = None
    bit: int | None = None
    length: int | None = None
    enum: str | None = None
    base_size: int | None = None
    max_value: int | None = None


# Getter patterns, tried in order. Each maps to a (kind, group-extractor).
SCALAR_READS = {
    "ReadUInt16LittleEndian": "u16",
    "ReadInt16LittleEndian": "i16",
    "ReadUInt32LittleEndian": "u32",
    "ReadInt32LittleEndian": "i32",
    "ReadUInt64LittleEndian": "u64",
    "ReadSingleLittleEndian": "f32",
    "ReadUInt16BigEndian": "u16be",
    "ReadUInt32BigEndian": "u32be",
}


def parse_getter(getter: str, cs_type: str) -> FieldSpec | None:
    """Translate one C# getter expression into a field kind and offset."""
    body = getter.strip()
    # Strip a leading cast: "(byte)(...)", "(Nature)Data[0x20]"
    enum = None
    cast = re.match(r"^\((?P<cast>[\w\.]+)\)\s*(?P<rest>.+)$", body)
    if cast and cast.group("cast") not in ("byte", "sbyte", "ushort", "short",
                                           "uint", "int", "ulong", "long", "bool", "char"):
        enum = cast.group("cast")
        body = cast.group("rest").strip()
    elif cast:
        body = cast.group("rest").strip()

    while body.startswith("(") and body.endswith(")") and _balanced(body[1:-1]):
        body = body[1:-1].strip()

    # Math.Min(byte.MaxValue, <read>) clamps a wider stored value on read.
    m = re.fullmatch(r"Math\.Min\((?P<cap>\(?\w*\)?\s*[\w\.]+),\s*(?P<inner>.+)\)", body)
    if m:
        cap = _parse_cap(m.group("cap"))
        inner = parse_getter(m.group("inner"), cs_type)
        if cap is not None and inner is not None:
            inner.max_value = cap
            inner.enum = enum
            return inner

    for fn, kind in SCALAR_READS.items():
        m = re.fullmatch(rf"{fn}\(Data\[({HEX})\.\.\]\)", body)
        if m:
            return FieldSpec("", kind, _num(m.group(1)), cs_type, enum=enum)
        if re.fullmatch(rf"{fn}\(Data\)", body):
            return FieldSpec("", kind, 0, cs_type, enum=enum)

    # Plain byte: Data[0x20]
    m = re.fullmatch(rf"Data\[({HEX})\]", body)
    if m:
        return FieldSpec("", "u8", _num(m.group(1)), cs_type, enum=enum)

    # FlagUtil.GetFlag(Data, 0x34, 0)
    m = re.fullmatch(rf"FlagUtil\.GetFlag\(Data,\s*({HEX}),\s*({HEX})\)", body)
    if m:
        return FieldSpec("", "flag", _num(m.group(1)), cs_type, bit=_num(m.group(2)))

    # Flag: (Data[0x22] & 1) == 1  /  (Data[0x16] & 8) != 0
    m = re.fullmatch(
        rf"\(?Data\[({HEX})\]\s*&\s*({HEX})\)?\s*(?:!=\s*0|==\s*({HEX}))", body)
    if m:
        mask = _num(m.group(2))
        if mask and (mask & (mask - 1)) == 0:
            return FieldSpec("", "flag", _num(m.group(1)), cs_type,
                             bit=mask.bit_length() - 1, enum=enum)
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=0, mask=mask, enum=enum)

    # Shifted bits: (Data[0x22] >> 1) & 0x3
    m = re.fullmatch(rf"\(?Data\[({HEX})\]\s*>>\s*(\d+)\)?\s*&\s*({HEX})", body)
    if m:
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=int(m.group(2)), mask=_num(m.group(3)), enum=enum)

    # Top bits with no mask: Data[0x125] >> 7
    m = re.fullmatch(rf"Data\[({HEX})\]\s*>>\s*(\d+)", body)
    if m:
        shift = int(m.group(2))
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=shift, mask=(1 << (8 - shift)) - 1, enum=enum)

    # Inverted mask: Data[0x125] & ~0x80
    m = re.fullmatch(rf"Data\[({HEX})\]\s*&\s*~({HEX})", body)
    if m:
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=0, mask=(~_num(m.group(2))) & 0xFF, enum=enum)

    # Mask then shift: (Data[0x1D] & 0xC0) >> 6
    m = re.fullmatch(rf"\(?Data\[({HEX})\]\s*&\s*({HEX})\)?\s*>>\s*(\d+)", body)
    if m:
        shift = int(m.group(3))
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=shift, mask=_num(m.group(2)) >> shift, enum=enum)

    # Bit test written long-hand: ((Data[0xC9] >> 0) & 1) == 1
    m = re.fullmatch(
        rf"\(\(?Data\[({HEX})\]\s*>>\s*(\d+)\)?\s*&\s*1\)\s*(?:==\s*1|!=\s*0)", body)
    if m:
        return FieldSpec("", "flag", _num(m.group(1)), cs_type, bit=int(m.group(2)))

    # Whole byte used as a boolean: Data[0xCB] == 1 / Data[0x23] != 0
    m = re.fullmatch(rf"Data\[({HEX})\]\s*(?:==\s*1|!=\s*0)", body)
    if m:
        return FieldSpec("", "boolbyte", _num(m.group(1)), cs_type)

    # Masked bits with no shift: Data[0x16] & 7
    m = re.fullmatch(rf"Data\[({HEX})\]\s*&\s*({HEX})", body)
    if m:
        return FieldSpec("", "bits", _num(m.group(1)), cs_type,
                         shift=0, mask=_num(m.group(2)), enum=enum)

    # String: GetString(Data.Slice(0x58, 26))
    m = re.fullmatch(rf"GetString\(Data\.Slice\(({HEX}),\s*({HEX})\)\)", body)
    if m:
        return FieldSpec("", "string", _num(m.group(1)), cs_type,
                         length=_num(m.group(2)))

    # Raw span: Data.Slice(0x58, 26)
    m = re.fullmatch(rf"Data\.Slice\(({HEX}),\s*({HEX})\)", body)
    if m:
        return FieldSpec("", "span", _num(m.group(1)), cs_type,
                         length=_num(m.group(2)))

    return None


_TYPE_MAX = {"byte": 0xFF, "sbyte": 0x7F, "ushort": 0xFFFF, "short": 0x7FFF,
             "uint": 0xFFFFFFFF, "int": 0x7FFFFFFF}


def _parse_cap(text: str) -> int | None:
    """Read the ceiling from a Math.Min clamp: ``byte.MaxValue`` or ``(ushort)31``."""
    text = re.sub(r"^\(\w+\)", "", text.strip()).strip()
    if text.endswith(".MaxValue"):
        return _TYPE_MAX.get(text[:-len(".MaxValue")])
    try:
        return _num(text)
    except ValueError:
        return None


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


SCALAR_SIZES = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u16be": 2,
                "u32": 4, "i32": 4, "u32be": 4, "u64": 8}


def parse_string_property(getter: str, cs_type: str,
                          spans: dict[str, FieldSpec]) -> FieldSpec | None:
    """Resolve ``GetString(NicknameTrash)`` against the span it reads."""
    m = re.fullmatch(r"(?:\w+\.)?GetString\((\w+)\)", getter.strip())
    if not m:
        return None
    span = spans.get(m.group(1))
    if span is None:
        return None
    return FieldSpec("", "string", span.offset, cs_type, length=span.length)


def parse_derived(getter: str, cs_type: str,
                  scalars: dict[str, FieldSpec]) -> FieldSpec | None:
    """Resolve a getter written against another property, e.g. ``(IV32 >> 5) & 0x1F``.

    Gen3 onward packs the six IVs, the egg flag, and the nicknamed flag into one
    32-bit word; the C# exposes that word as its own property and derives the
    rest from it. Following that indirection here keeps those fields generated
    rather than hand-written six times over.
    """
    body = getter.strip()
    cast = re.match(r"^\((?P<cast>[\w\.]+)\)\s*(?P<rest>.+)$", body)
    enum = None
    if cast:
        name = cast.group("cast")
        if name not in ("byte", "sbyte", "ushort", "short", "uint", "int",
                        "ulong", "long", "bool", "char"):
            enum = name
        body = cast.group("rest").strip()
    while body.startswith("(") and body.endswith(")") and _balanced(body[1:-1]):
        body = body[1:-1].strip()

    names = "|".join(re.escape(n) for n in scalars)
    if not names:
        return None

    def build(base: FieldSpec, shift: int, mask: int, kind: str) -> FieldSpec:
        return FieldSpec("", kind, base.offset, cs_type, shift=shift, mask=mask,
                         enum=enum, base_size=SCALAR_SIZES[base.kind],
                         bit=shift if kind == "packed_flag" else None)

    # ((NAME >> N) & 1) == 1  /  (NAME >> N) & 1 != 0
    m = re.fullmatch(rf"\(*({names})\s*>>\s*(\d+)\)*\s*&\s*1\)*\s*(?:==\s*1|!=\s*0)", body)
    if m:
        return build(scalars[m.group(1)], int(m.group(2)), 1, "packed_flag")

    # (NAME >> N) & MASK
    m = re.fullmatch(rf"\(*({names})\s*>>\s*(\d+)\)*\s*&\s*({HEX})\)*", body)
    if m:
        return build(scalars[m.group(1)], int(m.group(2)), _num(m.group(3)), "packed_bits")

    # NAME >> N, with the width implied by the cast or the base word size
    m = re.fullmatch(rf"({names})\s*>>\s*(\d+)", body)
    if m:
        base = scalars[m.group(1)]
        shift = int(m.group(2))
        width = 8 if cs_type in ("byte", "sbyte") else SCALAR_SIZES[base.kind] * 8 - shift
        return build(base, shift, (1 << width) - 1, "packed_bits")

    # Plain (byte)NAME truncation
    m = re.fullmatch(rf"({names})", body)
    if m and cs_type in ("byte", "sbyte"):
        return build(scalars[m.group(1)], 0, 0xFF, "packed_bits")

    # (NAME & MASK) >> N
    m = re.fullmatch(rf"\(?({names})\s*&\s*({HEX})\)?\s*>>\s*(\d+)", body)
    if m:
        shift = int(m.group(3))
        return build(scalars[m.group(1)], shift, _num(m.group(2)) >> shift, "packed_bits")

    # NAME & MASK
    m = re.fullmatch(rf"({names})\s*&\s*({HEX})", body)
    if m:
        mask = _num(m.group(2))
        base = scalars[m.group(1)]
        if mask and (mask & (mask - 1)) == 0 and cs_type == "bool":
            return build(base, mask.bit_length() - 1, 1, "packed_flag")
        return build(base, 0, mask, "packed_bits")

    # (NAME & (1 << N)) == 1 << N
    m = re.fullmatch(rf"\(*({names})\s*&\s*\(1\s*<<\s*(\d+)\)\)*\s*(?:==\s*1\s*<<\s*\d+|!=\s*0)", body)
    if m:
        return build(scalars[m.group(1)], int(m.group(2)), 1, "packed_flag")

    # (NAME & MASK) != 0
    m = re.fullmatch(rf"\(?({names})\s*&\s*({HEX})\)?\s*(?:!=\s*0|==\s*({HEX}))", body)
    if m:
        mask = _num(m.group(2))
        if mask and (mask & (mask - 1)) == 0:
            return build(scalars[m.group(1)], mask.bit_length() - 1, 1, "packed_flag")
    return None


MULTILINE_PROPERTY_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<head>(?:public|private|internal|protected)\s+"
    r"(?:override\s+|virtual\s+|new\s+|sealed\s+)*[\w\.<>\?\[\]]+\s+\w+)"
    r"[ \t]*\{?[ \t]*\r?\n"          # optional opening brace on the same line
    r"(?:[ \t]*\{[ \t]*\r?\n)?"      # or on its own line
    r"[ \t]*get\s*=>\s*(?P<get>[^;\n]+);[ \t]*\}?[ \t]*\r?\n"
    r"(?:[ \t]*set\s*=>\s*(?P<set>[^;\n]+);[ \t]*\}?[ \t]*\r?\n)?"
    r"[ \t]*\}?",
    re.M,
)


def collapse_multiline_properties(text: str) -> str:
    """Rewrite properties whose braces span lines into the single-line form.

    PKHeX formats a handful of properties across several lines; collapsing them
    first means one set of patterns covers both styles.
    """
    def repl(m: re.Match[str]) -> str:
        body = f"get => {m.group('get').strip()};"
        if m.group("set"):
            body += f" set => {m.group('set').strip()};"
        return f"{m.group('indent')}{m.group('head')} {{ {body} }}"

    return MULTILINE_PROPERTY_RE.sub(repl, text)


#: "private const int StringLength = 12;" and its siblings. SK2 sizes both of
#: its name buffers from one of these rather than repeating the number.
CONST_RE = re.compile(
    r"^\s*(?:public|private|internal|protected)\s+const\s+"
    r"(?:byte|sbyte|ushort|short|uint|int|ulong|long)\s+"
    rf"(?P<name>\w+)\s*=\s*(?P<value>{HEX})\s*;",
    re.M,
)


def substitute_constants(source: str) -> str:
    """Replace file-local numeric constants with their values.

    An offset or a length written as a named constant is still an offset or a
    length, but every pattern below matches digits. Resolving the names first
    means one more property is generated instead of reported unhandled.
    """
    constants = {m.group("name"): m.group("value")
                 for m in CONST_RE.finditer(source)}
    if not constants:
        return source
    names = "|".join(re.escape(n) for n in constants)
    # Skip the declarations themselves; rewriting "const int X = 12" to
    # "const int 12 = 12" would not parse on a re-read.
    declarations = {m.start() for m in CONST_RE.finditer(source)}

    def repl(m: re.Match[str]) -> str:
        line_start = source.rfind("\n", 0, m.start()) + 1
        if line_start in declarations:
            return m.group(0)
        return constants[m.group(0)]

    return re.sub(rf"\b(?:{names})\b", repl, source)


def extract(path: Path) -> tuple[list[FieldSpec], list[tuple[str, str]]]:
    candidates: list[tuple[str, str, str, bool, str]] = []
    source = substitute_constants(
        collapse_multiline_properties(path.read_text(encoding="utf-8")))
    for raw in source.splitlines():
        line = re.sub(r"//.*$", "", raw).rstrip()
        m = PROPERTY_RE.match(line)
        readonly = False
        if not m:
            m = GET_ONLY_RE.match(line)
            readonly = True
        if not m:
            continue
        has_setter = bool(m.groupdict().get("set"))
        candidates.append((m.group("name"), m.group("type"), m.group("get"),
                           readonly or not has_setter, m.group("vis")))

    fields: list[FieldSpec] = []
    scalars: dict[str, FieldSpec] = {}
    spans: dict[str, FieldSpec] = {}
    deferred: list[tuple[str, str, str, bool, str]] = []

    for name, cs_type, getter, readonly, vis in candidates:
        spec = parse_getter(getter, cs_type)
        if spec is None:
            deferred.append((name, cs_type, getter, readonly, vis))
            continue
        spec.name = name
        spec.readonly = readonly
        if spec.kind in SCALAR_SIZES:
            scalars[name] = spec
        elif spec.kind == "span":
            spans[name] = spec
        if vis == "public":
            fields.append(spec)

    unhandled: list[tuple[str, str]] = []
    for name, cs_type, getter, readonly, vis in deferred:
        spec = parse_string_property(getter, cs_type, spans)
        if spec is None:
            spec = parse_derived(getter, cs_type, scalars)
        if spec is None:
            unhandled.append((name, getter.strip()))
            continue
        spec.name = name
        spec.readonly = readonly
        if vis == "public":
            fields.append(spec)
    return fields, unhandled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+", type=Path)
    ap.add_argument("--report-unhandled", action="store_true")
    args = ap.parse_args()

    out: dict[str, object] = {}
    for path in args.sources:
        fields, unhandled = extract(path)
        out[path.stem] = {
            "fields": [asdict(f) for f in fields],
            "unhandled": unhandled,
        }
        if args.report_unhandled:
            print(f"{path.stem}: {len(fields)} parsed, {len(unhandled)} unhandled",
                  file=sys.stderr)
            for name, getter in unhandled:
                print(f"    {name}: {getter}", file=sys.stderr)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
