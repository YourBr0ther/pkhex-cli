"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import saves as save_io
from .pkm import io as entity_io
from .pkm import serialize as entity_json
from .pkm.formats import ALL_FORMATS


def _write_json(document, out: Path | None, indent: int) -> None:
    text = json.dumps(document, ensure_ascii=False,
                      indent=None if indent < 0 else indent)
    if out is None:
        sys.stdout.write(text + "\n")
    else:
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)


def _load(path):
    """Load a file as either a save or a single entity."""
    raw = Path(path).read_bytes()
    save_error = None
    try:
        return "save", save_io.from_bytes(raw)
    except save_io.SaveFormatError as exc:
        save_error = exc
    try:
        return "entity", entity_io.from_bytes(raw, extension=Path(path).suffix)
    except entity_io.EntityFormatError as exc:
        # When the length names a game, that is the more useful complaint.
        if len(raw) in save_io.KNOWN_SIZES:
            raise save_io.SaveFormatError(f"{path}: {save_error}") from None
        raise entity_io.EntityFormatError(
            f"{path} is not a save file, and {exc}"
        ) from None


def cmd_to_json(args: argparse.Namespace) -> int:
    kind, obj = _load(args.input)
    if kind == "save":
        document = obj.to_dict(
            include_raw=not args.no_raw,
            include_boxes=not args.party_only,
            include_entity_raw=not args.no_raw,
        )
        _write_json(document, args.output, args.indent)
        return 0
    entity = obj
    document = entity_json.to_dict(
        entity,
        include_raw=not args.no_raw,
        include_derived=not args.no_derived,
    )
    _write_json(document, args.output, args.indent)
    return 0


def cmd_from_json(args: argparse.Namespace) -> int:
    document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    schema = document.get("schema") if isinstance(document, dict) else None
    if not isinstance(schema, str) or not schema.startswith("pkhexpy/"):
        raise ValueError(
            f"{args.input} is not a pkhexpy document; expected a schema of "
            f"pkhexpy/save/N or pkhexpy/entity/N, found {schema!r}")
    if schema.startswith("pkhexpy/save"):
        return _save_from_json(document, args)
    entity = entity_json.from_dict(document)
    out = args.output or Path(args.input).with_suffix(f".{type(entity).__name__.lower()}")
    entity_io.write_file(out, entity, encrypted=args.encrypted)
    print(f"wrote {out} ({len(entity.data)} bytes, "
          f"checksum {'ok' if entity.checksum_valid else 'INVALID'})", file=sys.stderr)
    return 0


def _save_from_json(document, args: argparse.Namespace) -> int:
    """Rebuild a save. Editing needs the original file to write the slots into."""
    if args.into:
        sav = save_io.read_file(args.into)
        _check_into_matches(document, sav, args.into)
    elif document.get("raw_base64"):
        import base64
        sav = save_io.from_bytes(base64.b64decode(document["raw_base64"]))
    else:
        print("pkhexpy: a save needs --into <original.sav>, or JSON exported "
              "with raw_base64 included", file=sys.stderr)
        return 1
    sav.apply_dict(document)
    out = args.output or Path(args.input).with_suffix(".sav")
    Path(out).write_bytes(sav.to_bytes())
    print(f"wrote {out} ({len(sav.data)} bytes, "
          f"checksums {'ok' if sav.checksums_valid else 'INVALID'})", file=sys.stderr)
    return 0


def _check_into_matches(document, sav, path) -> None:
    """Refuse to apply a document to a save it did not come from.

    Nothing downstream would notice: two saves of the same generation take each
    other's slot writes without complaint, and the result checksums clean.
    """
    wanted, found = document.get("save_format"), sav.KEY
    if wanted is not None and wanted != found:
        raise ValueError(
            f"this document came from a {wanted} save, but {path} is {found}; "
            f"--into needs the file the JSON was exported from")
    generation = document.get("generation")
    if generation is not None and generation != sav.GENERATION:
        raise ValueError(
            f"this document is generation {generation}, but {path} is "
            f"generation {sav.GENERATION}")


def _checksum_summary(sav) -> str:
    main = "valid" if sav.checksums_valid else "INVALID"
    if not getattr(sav, "extra_sectors_valid", True):
        return f"{main} (Hall of Fame region inconsistent; left untouched)"
    if not getattr(sav, "backup_checksum_valid", True):
        return f"{main} (backup copy holds an older save; left untouched)"
    return main


def _show_save(sav) -> int:
    played = sav.play_time
    rows = [
        ("Game", f"{sav.GAME} (generation {sav.GENERATION})"),
        ("Trainer", f"{sav.trainer_name} [{sav.tid16}/{sav.sid16}]"),
        ("Money", sav.money),
        ("Play time", f"{played[0]}h {played[1]}m {played[2]}s" if played else None),
        ("Checksums", _checksum_summary(sav)),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        if value not in (None, ""):
            print(f"{label:<{width}}  {value}")

    party = list(sav.iter_party())
    print(f"\nParty ({len(party)})")
    for slot, pk in party:
        print(f"  {slot + 1}. {pk.species_name} lv{pk.current_level}"
              f"{' *shiny*' if pk.is_shiny else ''}")

    counts: dict[int, int] = {}
    total = 0
    for box, _, _ in sav.iter_boxes():
        counts[box] = counts.get(box, 0) + 1
        total += 1
    print(f"\nBoxes ({total} stored across {len(counts)} boxes)")
    for box in sorted(counts):
        name = sav.box_name(box) or f"Box {box + 1}"
        print(f"  {name}: {counts[box]}")

    extra = list(sav.iter_extra())
    if extra:
        print(f"\nElsewhere ({len(extra)})")
        for slot, pk in extra:
            print(f"  {slot.kind} {slot.index + 1}: {pk.species_name} "
                  f"lv{pk.current_level}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    kind, obj = _load(args.input)
    if kind == "save":
        return _show_save(obj)
    entity = obj
    document = entity_json.to_dict(entity, include_raw=False)
    derived = document["derived"]
    rows = [
        ("File", str(args.input)),
        ("Format", f"{document['format']} (generation {document['generation']})"),
        ("Species", f"{derived.get('SpeciesName')} (#{entity.species})"),
        ("Nickname", document["fields"].get("Nickname", "")),
        ("Trainer", f"{document['fields'].get('OriginalTrainerName', '')} "
                    f"[{getattr(entity, 'tid16', 0)}/{getattr(entity, 'sid16', 0)}]"),
        ("Level", derived.get("Level")),
        ("Nature", derived.get("NatureName")),
        ("Ability", derived.get("AbilityName")),
        ("Held item", derived.get("HeldItemName")),
        ("Ball", derived.get("BallName")),
        ("Shiny", "yes" if derived.get("IsShiny") else "no"),
        ("IVs", " / ".join(str(v) for v in derived.get("IVs", []))),
        ("EVs", " / ".join(str(v) for v in derived.get("EVs", []))),
        ("Moves", ", ".join(m for m in derived.get("MoveNames", []) if m)),
        ("Met", derived.get("MetLocationName")),
        ("Met date", derived.get("MetDate")),
        ("Checksum", "valid" if document["checksum_valid"] else "INVALID"),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        if value in (None, "", []):
            continue
        print(f"{label:<{width}}  {value}")
    return 0


def cmd_boxes(args: argparse.Namespace) -> int:
    sav = save_io.read_file(args.input)
    for slot, pk in sav.iter_party():
        print(f"party {slot + 1:<3} {pk.species_name:<14} lv{pk.current_level:<4}"
              f"{pk.nickname}")
    for box, slot, pk in sav.iter_boxes():
        label = sav.box_name(box) or f"box {box + 1}"
        print(f"{label} {slot + 1:<3} {pk.species_name:<14} lv{pk.current_level:<4}"
              f"{pk.nickname}")
    for extra, pk in sav.iter_extra():
        print(f"{extra.kind} {extra.index + 1:<3} {pk.species_name:<14} "
              f"lv{pk.current_level:<4}{pk.nickname}")
    return 0


SAVE_CLASSES = (
    ("SAV1", "rby"), ("SAV2", "gsc"),
    ("SAV3RS", "rs"), ("SAV3E", "e"), ("SAV3FRLG", "frlg"),
    ("SAV4DP", "dp"), ("SAV4Pt", "pt"), ("SAV4HGSS", "hgss"),
    ("SAV5BW", "bw"), ("SAV5B2W2", "b2w2"),
    ("SAV6XY", "xy"), ("SAV6AO", "ao"),
    ("SAV7SM", "sm"), ("SAV7USUM", "usum"), ("SAV7b", "gg"),
    ("SAV8SWSH", "swsh"), ("SAV8LA", "la"), ("SAV8BS", "bdsp"),
    ("SAV9SV", "sv"), ("SAV9ZA", "za"),
)


def _save_classes():
    from .saves import gen3, gen8b, gen12, gen45, gen67, gen89
    modules = (gen12, gen3, gen45, gen67, gen89, gen8b)
    for name, _ in SAVE_CLASSES:
        for module in modules:
            cls = getattr(module, name, None)
            if cls is not None:
                yield cls
                break


def cmd_formats(_: argparse.Namespace) -> int:
    print("Entity formats")
    print(f"  {'Name':<8}{'Gen':<5}{'Context':<9}{'Stored':>8}{'Party':>8}  Games")
    for cls in ALL_FORMATS:
        doc = (cls.__doc__ or "").splitlines()[0].rstrip(".")
        print(f"  {cls.__name__:<8}{cls.FORMAT:<5}{cls.CONTEXT:<9}"
              f"{cls.SIZE_STORED:>8}{cls.SIZE_PARTY:>8}  {doc}")

    print("\nSave formats")
    print(f"  {'Name':<10}{'Gen':<5}{'Boxes':>7}{'Slots':>7}  Games")
    for cls in _save_classes():
        boxes = cls.BOX_COUNT or (cls.BOX_COUNTS[1] if hasattr(cls, "BOX_COUNTS") else 0)
        slots = cls.BOX_SLOT_COUNT
        print(f"  {cls.__name__:<10}{cls.GENERATION:<5}{boxes:>7}{slots:>7}  {cls.GAME}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkhexpy",
        description="Convert Pokemon save and entity files to JSON and back.",
    )
    parser.add_argument("--version", action="version", version=f"pkhexpy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("to-json", help="convert a .pkX file to JSON")
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    p.add_argument("--indent", type=int, default=2,
                   help="JSON indent; -1 for a single line (default: 2)")
    p.add_argument("--no-raw", action="store_true",
                   help="omit raw_base64; the result no longer round trips exactly")
    p.add_argument("--no-derived", action="store_true",
                   help="omit the read-only derived section")
    p.add_argument("--party-only", action="store_true",
                   help="save files: skip the boxes and export only the party")
    p.set_defaults(func=cmd_to_json)

    p = sub.add_parser("from-json", help="rebuild a .pkX file from JSON")
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--encrypted", action="store_true",
                   help="write the encrypted form a save file stores")
    p.add_argument("--into", type=Path,
                   help="save files: the original save to write the edits into")
    p.set_defaults(func=cmd_from_json)

    p = sub.add_parser("show", help="print a readable summary of a save or .pkX file")
    p.add_argument("input", type=Path)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("formats", help="list the supported formats")
    p.set_defaults(func=cmd_formats)

    p = sub.add_parser("boxes", help="list every Pokemon in a save file")
    p.add_argument("input", type=Path)
    p.set_defaults(func=cmd_boxes)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # Downstream closed the pipe, as `| head` does. Say nothing about it.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130
    except (entity_io.EntityFormatError, save_io.SaveFormatError,
            ValueError, OSError, NotImplementedError) as exc:
        print(f"pkhexpy: {exc}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        # A malformed document reaches the writers as a missing key or a value
        # of the wrong shape. Say so in one line rather than a stack trace.
        print(f"pkhexpy: {args.input if hasattr(args, 'input') else 'input'} "
              f"could not be applied: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
