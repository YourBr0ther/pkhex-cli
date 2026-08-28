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
    for bom, encoding in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
                          (b"\xef\xbb\xbf", "utf-8-sig")):
        if raw.startswith(bom):
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


# Per-game personal table: file stem -> (record size, growth offset, gender offset).
PERSONAL = {
    "rb":   (0x1C, 0x13, 0x0F), "y":    (0x1C, 0x13, 0x0F),
    "gs":   (0x20, 0x16, 0x12), "c":    (0x20, 0x16, 0x12),
    "rs":   (0x1C, 0x13, 0x10), "e":    (0x1C, 0x13, 0x10),
    "fr":   (0x1C, 0x13, 0x10), "lg":   (0x1C, 0x13, 0x10),
    "dp":   (0x2C, 0x13, 0x10), "pt":   (0x2C, 0x13, 0x10),
    "hgss": (0x2C, 0x13, 0x10),
    "bw":   (0x3C, 0x15, 0x12), "b2w2": (0x4C, 0x15, 0x12),
    "xy":   (0x40, 0x15, 0x12), "ao":   (0x50, 0x15, 0x12),
    "sm":   (0x54, 0x15, 0x12), "uu":   (0x54, 0x15, 0x12),
    "gg":   (0x54, 0x15, 0x12),
    "swsh": (0xB0, 0x15, 0x12), "la":   (0xB0, 0x15, 0x12),
    "bdsp": (0x44, 0x15, 0x12),
    "sv":   (0x50, 0x0F, 0x0C), "za":   (0x50, 0x0F, 0x0C),
}


def build_personal() -> None:
    source = REF / "Resources/byte/personal"
    bundle: dict[str, dict[str, list[int]]] = {}
    for stem, (size, growth_off, gender_off) in PERSONAL.items():
        path = source / f"personal_{stem}"
        if not path.exists():
            print(f"  skipped personal_{stem} (missing)")
            continue
        raw = path.read_bytes()
        count = len(raw) // size
        bundle[stem] = {
            "growth": [raw[i * size + growth_off] for i in range(count)],
            "gender": [raw[i * size + gender_off] for i in range(count)],
        }
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
