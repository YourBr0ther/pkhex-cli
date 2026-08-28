"""Build the packaged lookup data from the PKHeX reference resources.

Produces:
  data/names/<lang>.json      species, moves, items, abilities, natures, ...
  data/locations/<gen>.json   met-location names, keyed by location bank
  data/experience.json        the six EXP growth tables
  data/personal.json          growth rate and gender ratio per species per game

Run from the repo root with reference_PKHeX/ present:
    python3 tools/gen_data.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REF = Path("reference_PKHeX/PKHeX.Core")
TEXT = REF / "Resources/text"
OUT = Path("src/pkhexpy/data")

LANGUAGES = ["en", "ja", "fr", "it", "de", "es", "ko", "zh-Hans", "zh-Hant", "es-419"]

# PKHeX resource stem -> key in the generated JSON.
OTHER_LISTS = {
    "Species": "species",
    "Moves": "moves",
    "Abilities": "abilities",
    "Natures": "natures",
    "Types": "types",
    "Forms": "forms",
    "Games": "games",
    "Ribbons": "ribbons",
    "Language": "languages",
    "GroundTile": "ground_tiles",
    "Character": "characteristics",
}


def read_lines(path: Path) -> list[str]:
    """Read a resource list; PKHeX ships a mix of UTF-8 and BOM'd UTF-16."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    for bom, encoding in ((b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"),
                          (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
            # "utf-16" consumes the byte-order mark; the explicit -le/-were
            # variants leave it as a stray \ufeff on the first entry.
            return raw.decode(encoding).splitlines()
    return raw.decode("utf-8").splitlines()


def build_names() -> None:
    target = OUT / "names"
    target.mkdir(parents=True, exist_ok=True)
    for lang in LANGUAGES:
        bundle: dict[str, list[str]] = {}
        for stem, key in OTHER_LISTS.items():
            lines = read_lines(TEXT / "other" / lang / f"text_{stem}_{lang}.txt")
            if lines:
                bundle[key] = lines
        items = read_lines(TEXT / "items" / f"text_Items_{lang}.txt")
        if items:
            bundle["items"] = items
        # Generations 1-4 use their own, shorter item lists.
        for gen in range(1, 5):
            legacy = read_lines(TEXT / "items" / f"gen{gen}" / f"text_ItemsG{gen}_{lang}.txt")
            if legacy:
                bundle[f"items_gen{gen}"] = legacy
        if not bundle:
            continue
        path = target / f"{lang}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
        print(f"{path}: {sum(len(v) for v in bundle.values())} entries")


def build_locations() -> None:
    target = OUT / "locations"
    target.mkdir(parents=True, exist_ok=True)
    root = TEXT / "locations"
    for gen_dir in sorted(root.iterdir()):
        if not gen_dir.is_dir():
            continue
        bundle: dict[str, dict[str, list[str]]] = {}
        for path in sorted(gen_dir.iterdir()):
            m = re.fullmatch(r"text_([a-z0-9]+)_(\d+)_(.+)\.txt", path.name)
            if not m:
                continue
            game, bank, lang = m.group(1), str(int(m.group(2))), m.group(3)
            bundle.setdefault(lang, {})[f"{game}:{bank}"] = read_lines(path)
        out = target / f"{gen_dir.name}.json"
        out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
        print(f"{out}: {len(bundle)} languages")


NUM_ARRAY_RE = r"ReadOnlySpan<uint>\s+{name}\s*=>\s*\[(.*?)\];"


def build_experience() -> None:
    source = next(REF.rglob("Experience.cs")).read_text(encoding="utf-8")
    tables: list[list[int]] = []
    for i in range(6):
        m = re.search(NUM_ARRAY_RE.format(name=f"Growth{i}"), source, re.S)
        if not m:
            raise SystemExit(f"Growth{i} table not found")
        values = [int(v.strip()) for v in m.group(1).split(",") if v.strip()]
        if len(values) != 100:
            raise SystemExit(f"Growth{i} has {len(values)} entries, expected 100")
        tables.append(values)
    path = OUT / "experience.json"
    path.write_text(json.dumps(tables, separators=(",", ":")))
    print(f"{path}: 6 growth tables")


# Per-game personal table layout. Stat offsets are listed in the order the games
# use for battle stats: HP, ATK, DEF, SPE, SPA, SPD. Gen1 has one Special stat
# standing in for both SPA and SPD.
GEN1_STATS = (0x01, 0x02, 0x03, 0x04, 0x05, 0x05)
GEN2_STATS = (0x01, 0x02, 0x03, 0x04, 0x05, 0x06)
MODERN_STATS = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05)

#: Per-table entry size and field offsets. "forms" is the offset pair for the
#: form-entry index and the form count, absent in the games that have no form
#: entries. Form entries live past the species entries in the same table, so a
#: species with forms points at the first of its extra rows.
PERSONAL = {
    "rb":   dict(size=0x1C, growth=0x13, gender=0x00, stats=GEN1_STATS),
    "y":    dict(size=0x1C, growth=0x13, gender=0x00, stats=GEN1_STATS),
    "gs":   dict(size=0x20, growth=0x16, gender=0x0D, stats=GEN2_STATS),
    "c":    dict(size=0x20, growth=0x16, gender=0x0D, stats=GEN2_STATS),
    "rs":   dict(size=0x1C, growth=0x13, gender=0x10, stats=MODERN_STATS),
    "e":    dict(size=0x1C, growth=0x13, gender=0x10, stats=MODERN_STATS),
    "fr":   dict(size=0x1C, growth=0x13, gender=0x10, stats=MODERN_STATS),
    "lg":   dict(size=0x1C, growth=0x13, gender=0x10, stats=MODERN_STATS),
    "dp":   dict(size=0x2C, growth=0x13, gender=0x10, stats=MODERN_STATS, forms=(0x2A, 0x29)),
    "pt":   dict(size=0x2C, growth=0x13, gender=0x10, stats=MODERN_STATS, forms=(0x2A, 0x29)),
    "hgss": dict(size=0x2C, growth=0x13, gender=0x10, stats=MODERN_STATS, forms=(0x2A, 0x29)),
    "bw":   dict(size=0x3C, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "b2w2": dict(size=0x4C, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "xy":   dict(size=0x40, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "ao":   dict(size=0x50, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "sm":   dict(size=0x54, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "uu":   dict(size=0x54, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "gg":   dict(size=0x54, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1C, 0x20)),
    "swsh": dict(size=0xB0, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1E, 0x20)),
    "la":   dict(size=0xB0, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1E, 0x20)),
    "bdsp": dict(size=0x44, growth=0x15, gender=0x12, stats=MODERN_STATS, forms=(0x1E, 0x20)),
    "sv":   dict(size=0x50, growth=0x0F, gender=0x0C, stats=MODERN_STATS, forms=(0x18, 0x1A)),
    "za":   dict(size=0x50, growth=0x0F, gender=0x0C, stats=MODERN_STATS, forms=(0x18, 0x1A)),
}


def build_personal() -> None:
    source = REF / "Resources/byte/personal"
    bundle: dict[str, dict[str, list]] = {}
    for stem, spec in PERSONAL.items():
        path = source / f"personal_{stem}"
        if not path.exists():
            print(f"  skipped personal_{stem} (missing)")
            continue
        raw = path.read_bytes()
        size = spec["size"]
        count = len(raw) // size
        entry = {
            "growth": [raw[i * size + spec["growth"]] for i in range(count)],
            "gender": [raw[i * size + spec["gender"]] for i in range(count)],
            "stats": [[raw[i * size + off] for off in spec["stats"]]
                      for i in range(count)],
        }
        forms = spec.get("forms")
        if forms:
            index_off, count_off = forms
            entry["form_index"] = [
                int.from_bytes(raw[i * size + index_off:i * size + index_off + 2],
                               "little") for i in range(count)]
            entry["form_count"] = [raw[i * size + count_off] for i in range(count)]
        bundle[stem] = entry
    out = OUT / "personal.json"
    out.write_text(json.dumps(bundle, separators=(",", ":")))
    print(f"{out}: {len(bundle)} game tables")


def _parse_int(text: str) -> int:
    """Parse a C# numeric literal; the delta tables use zero-padded decimals."""
    text = text.strip()
    if text.lower().startswith(("0x", "-0x")):
        return int(text, 16)
    return int(text, 10)


SPECIES_TABLES = [
    ("Table1NationalToInternal", "1_to_internal"),
    ("Table1InternalToNational", "1_to_national"),
    ("Table3NationalToInternal", "3_to_internal"),
    ("Table3InternalToNational", "3_to_national"),
    ("Table9NationalToInternal", "9_to_internal"),
    ("Table9InternalToNational", "9_to_national"),
]


def build_species_converter() -> None:
    """Gen1, Gen3, and Gen9 store species by an internal id, not the Dex number."""
    source = next(REF.rglob("SpeciesConverter.cs")).read_text(encoding="utf-8")
    source = re.sub(r"//[^\n]*", "", source)
    bundle: dict[str, list[int]] = {}
    for name, key in SPECIES_TABLES:
        m = re.search(rf"ReadOnlySpan<(?:byte|sbyte|short|ushort)>\s+{name}\s*=>\s*\[(.*?)\];",
                      source, re.S)
        if not m:
            raise SystemExit(f"{name} not found")
        bundle[key] = [_parse_int(v) for v in m.group(1).split(",") if v.strip()]
    # Offsets the C# applies before indexing each shifted table.
    bundle["first_unaligned"] = {
        "national3": 252, "internal3": 277,
        "national9": 917, "internal9": 917,
    }
    path = OUT / "species_convert.json"
    path.write_text(json.dumps(bundle, separators=(",", ":")))
    print(f"{path}: {len(SPECIES_TABLES)} tables")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_names()
    build_locations()
    build_experience()
    build_personal()
    build_species_converter()


if __name__ == "__main__":
    main()
