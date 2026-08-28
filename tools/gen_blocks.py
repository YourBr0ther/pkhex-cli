"""Extract the Gen6/7 save block tables from the PKHeX reference source.

Each 3DS-era save is a list of fixed blocks described by an array of
``new(metadataOffset, id, offset, length)`` entries. The block a value lives in
is identified by index, so these tables are what turn "party" into an offset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REF = Path("reference_PKHeX/PKHeX.Core/Saves/Access")
OUT = Path("src/pkhexpy/data/save_blocks.json")

ENTRY_RE = re.compile(
    r"new\(\s*\w+\s*,\s*(?P<id>\d+)\s*,\s*(?P<offset>0x[0-9A-Fa-f]+)\s*,"
    r"\s*(?P<length>0x[0-9A-Fa-f]+)\s*\)\s*,(?:[ \t]*//[ \t]*\d*[ \t]*(?P<name>[^\r\n]*))?"
)

# accessor file -> (key, total save size, checksum flavor)
SOURCES = {
    "SaveBlockAccessor6XY.cs": ("xy", 0x65600, "crc16_ccitt"),
    "SaveBlockAccessor6AO.cs": ("ao", 0x76000, "crc16_ccitt"),
    "SaveBlockAccessor6AODemo.cs": ("aodemo", 0x5A00, "crc16_ccitt"),
    "SaveBlockAccessor7SM.cs": ("sm", 0x6BE00, "crc16_invert"),
    "SaveBlockAccessor7USUM.cs": ("usum", 0x6CC00, "crc16_invert"),
    # Let's Go writes a 1 MB file but the save region ends at 0xB8800.
    "SaveBlockAccessor7b.cs": ("gg", 0xB8800, "crc16_noinvert"),
}


NDS_ENTRY_RE = re.compile(
    r"new\(\s*(?P<offset>0x[0-9A-Fa-f]+)\s*,\s*(?P<length>0x[0-9A-Fa-f]+)\s*,"
    r"\s*(?P<chk>0x[0-9A-Fa-f]+)\s*,\s*(?P<mirror>0x[0-9A-Fa-f]+)\s*\)\s*,"
    r"(?:[ \t]*//[ \t]*\d*[ \t]*(?P<name>[^\r\n]*))?"
)

NDS_SOURCES = {
    "SaveBlockAccessor5BW.cs": ("bw", 0x24000),
    "SaveBlockAccessor5B2W2.cs": ("b2w2", 0x26000),
}


def build_nds_blocks(bundle: dict) -> None:
    """Gen5 blocks carry their own checksum offset plus a mirror copy."""
    for filename, (key, main_size) in NDS_SOURCES.items():
        path = REF / filename
        if not path.exists():
            print(f"  skipped {filename} (missing)")
            continue
        text = path.read_text(encoding="utf-8")
        blocks = [
            {
                "offset": int(m.group("offset"), 16),
                "length": int(m.group("length"), 16),
                "checksum": int(m.group("chk"), 16),
                "mirror": int(m.group("mirror"), 16),
                "name": (m.group("name") or "").strip(),
            }
            for m in NDS_ENTRY_RE.finditer(text)
        ]
        if not blocks:
            print(f"  no entries parsed from {filename}")
            continue
        bundle[key] = {"size": main_size, "checksum": "crc16_ccitt", "blocks": blocks}
        print(f"{key}: {len(blocks)} blocks")


def main() -> None:
    bundle: dict[str, dict] = {}
    for filename, (key, size, checksum) in SOURCES.items():
        path = REF / filename
        if not path.exists():
            print(f"  skipped {filename} (missing)")
            continue
        text = path.read_text(encoding="utf-8")
        blocks = [
            {
                "id": int(m.group("id")),
                "offset": int(m.group("offset"), 16),
                "length": int(m.group("length"), 16),
                "name": (m.group("name") or "").strip(),
            }
            for m in ENTRY_RE.finditer(text)
        ]
        if not blocks:
            print(f"  no entries parsed from {filename}")
            continue
        m = re.search(r"BlockMetadataOffset\s*=\s*SaveUtil\.(\w+)\s*-\s*(0x[0-9A-Fa-f]+)", text)
        metadata_offset = size - int(m.group(2), 16) if m else size - 0x200
        bundle[key] = {
            "size": size,
            "metadata_offset": metadata_offset,
            "checksum": checksum,
            "blocks": blocks,
        }
        print(f"{key}: {len(blocks)} blocks, metadata @ 0x{metadata_offset:X}")

    build_nds_blocks(bundle)
    OUT.write_text(json.dumps(bundle, separators=(",", ":")))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
