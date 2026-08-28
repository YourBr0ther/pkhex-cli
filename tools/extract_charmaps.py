"""Extract C# character tables from the PKHeX reference source into Python.

The Gen1-4 encodings are index tables written as C# collection literals. Rather
than transcribe several thousand glyphs by hand, parse the literals directly so
the Python tables are provably identical to upstream's.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TABLE_RE_TMPL = r"ReadOnlySpan<char>\s+{name}\s*=>\s*\[(.*?)\];"

ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "f": "\f", "n": "\n",
    "r": "\r", "t": "\t", "v": "\v", "'": "'", '"': '"', "\\": "\\",
}


def parse_char_literal(token: str, symbols: dict[str, str]) -> str:
    token = token.strip()
    if token in symbols:
        return symbols[token]
    if not (token.startswith("'") and token.endswith("'")):
        raise ValueError(f"unrecognized table entry: {token!r}")
    body = token[1:-1]
    if not body.startswith("\\"):
        if len(body) != 1:
            raise ValueError(f"multi-char literal: {token!r}")
        return body
    tail = body[1:]
    if tail[0] in ("u", "x"):
        return chr(int(tail[1:], 16))
    if tail[0] in ESCAPES:
        return ESCAPES[tail[0]]
    raise ValueError(f"unknown escape: {token!r}")


def split_entries(body: str) -> list[str]:
    """Split a literal body on commas that are not inside a char literal."""
    entries: list[str] = []
    current: list[str] = []
    in_char = False
    escaped = False
    for ch in body:
        if in_char:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_char = False
            continue
        if ch == "'":
            in_char = True
            current.append(ch)
        elif ch == ",":
            entries.append("".join(current))
            current = []
        else:
            current.append(ch)
    if "".join(current).strip():
        entries.append("".join(current))
    return entries


def extract(source: str, name: str, symbols: dict[str, str]) -> list[str]:
    stripped = re.sub(r"//[^\n]*", "", source)
    match = re.search(TABLE_RE_TMPL.format(name=name), stripped, re.S)
    if not match:
        raise SystemExit(f"table {name} not found")
    return [parse_char_literal(tok, symbols) for tok in split_entries(match.group(1))]


def render(name: str, chars: list[str], start: int = 0) -> str:
    lines = [f"# {len(chars)} entries" + (f", index base 0x{start:X}" if start else "")]
    lines.append(f"{name} = (")
    for i in range(0, len(chars), 8):
        chunk = ", ".join(repr(c) for c in chars[i:i + 8])
        lines.append(f"    {chunk},  # 0x{start + i:03X}")
    lines.append(")")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--table", required=True)
    ap.add_argument("--pyname", required=True)
    ap.add_argument("--start", default="0")
    ap.add_argument("--symbol", action="append", default=[],
                    help="NAME=\\uXXXX substitution for named constants")
    args = ap.parse_args()

    symbols: dict[str, str] = {}
    for pair in args.symbol:
        key, _, value = pair.partition("=")
        symbols[key] = chr(int(value, 16))

    chars = extract(args.source.read_text(encoding="utf-8"), args.table, symbols)
    print(render(args.pyname, chars, int(args.start, 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
