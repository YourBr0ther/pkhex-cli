"""Entity to JSON and back.

The document has three parts. ``fields`` is the editable view - one entry per
byte-addressed field, keyed by its PKHeX property name. ``derived`` is
read-only context (names, level, shininess) that importing ignores.
``raw_base64`` is the original buffer, which importing uses as the starting
point so bytes no field covers survive a round trip untouched.
"""

from __future__ import annotations

import base64
from typing import Any

from .. import data
from .formats import BY_NAME
from .io import from_bytes, to_bytes

SCHEMA = "pkhexpy/entity/1"

def _encode(value: Any) -> Any:
    if isinstance(value, bytes | bytearray):
        return value.hex()
    if isinstance(value, bool):
        return value
    return value


def _derived(entity) -> dict[str, Any]:
    """Human-facing context; never read back during import."""
    language = entity.name_language
    out: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value is not None:
            out[key] = value

    put("SpeciesName", data.lookup("species", entity.species, language))
    put("Level", entity.current_level)
    put("IsShiny", entity.is_shiny)
    put("TSV", entity.tsv)
    put("PSV", entity.psv)
    put("IVs", list(entity.ivs))
    put("EVs", list(entity.evs))
    put("IVTotal", entity.iv_total)
    put("EVTotal", entity.ev_total)
    put("BaseStats", list(entity.base_stats) if entity.base_stats else None)
    computed = entity.calculated_stats()
    if computed is not None:
        out["CalculatedStats"] = list(computed)
        # The games recompute only on level-up, so a party block can lag behind
        # the EVs stored beside it. A boxed Pokemon's block is older still.
        stored = entity.stored_stats
        if stored is not None and any(stored):
            out["StoredStats"] = list(stored)

    move_names = [data.lookup("moves", m, language) for m in entity.moves]
    if any(move_names):
        out["MoveNames"] = move_names
    relearn = entity.relearn_moves
    if relearn:
        out["RelearnMoveNames"] = [data.lookup("moves", m, language) for m in relearn]

    for attr, key, kind in (
        ("ability", "AbilityName", "abilities"),
        ("nature", "NatureName", "natures"),
        ("version", "VersionName", "games"),
    ):
        value = getattr(entity, attr, None)
        if value is not None:
            put(key, data.lookup(kind, int(value), language))

    held = getattr(entity, "held_item", None)
    if held is not None:
        put("HeldItemName", data.item_name(int(held), entity.FORMAT, language))
    ball = getattr(entity, "ball", None)
    if ball is not None:
        put("BallName", data.item_name(int(ball), entity.FORMAT, language))

    put("MetLocationName", entity.met_location_name)
    met = entity.met_date
    if met is not None:
        out["MetDate"] = met.isoformat()
    egg = entity.egg_met_date
    if egg is not None:
        out["EggMetDate"] = egg.isoformat()
    return out


def to_dict(entity, *, include_raw: bool = True,
            include_derived: bool = True) -> dict[str, Any]:
    """Build the JSON document for one entity."""
    fields = type(entity)._fields
    ordered = sorted(fields.items(), key=lambda kv: (kv[1].offset, kv[1].pkhex_name))

    values: dict[str, Any] = {}
    for _, field in ordered:
        # A stored-size record stops before the party stat block, so some of
        # the class's fields are not in this buffer. Asking is the check;
        # decode() is called directly here and so skips Field.__get__, which
        # is where the bounds check normally lives. Catching instead would
        # also swallow a decoder bug and silently shorten the document.
        if not field.fits(entity):
            continue
        values[field.pkhex_name] = _encode(field.decode(entity))

    # Names live outside the field table, so add them explicitly.
    for key, attr in (("Nickname", "nickname"),
                      ("OriginalTrainerName", "original_trainer_name"),
                      ("HandlingTrainerName", "handling_trainer_name")):
        try:
            text = getattr(entity, attr)
        except AttributeError:      # a format without this name at all
            continue
        if text or key != "HandlingTrainerName":
            values[key] = text

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "format": type(entity).__name__,
        "generation": entity.FORMAT,
        "context": entity.CONTEXT,
        "size": len(entity.data),
        "japanese": entity.japanese,
        "checksum_valid": entity.checksum_valid,
        "fields": values,
    }
    if getattr(entity, "is_egg", None) is not None and entity.FORMAT <= 2:
        document["is_egg"] = bool(entity.is_egg)
    if include_derived:
        document["derived"] = _derived(entity)
    if include_raw:
        # to_bytes refreshes the checksum, so hand it a copy. Otherwise a record
        # with a bad checksum would be silently repaired inside raw_base64 while
        # the document above still reported it as invalid.
        document["raw_base64"] = base64.b64encode(
            to_bytes(entity.clone())).decode("ascii")
    return document


def from_dict(document: dict[str, Any], base=None):
    """Rebuild an entity from a JSON document produced by :func:`to_dict`.

    ``base`` is the entity the document describes, when it is already on hand -
    the slot a save is about to overwrite, for instance. Starting from it means
    only the changed fields are rewritten, so bytes the document cannot express
    (trash after a name, unmapped padding) survive. Without a base and without
    ``raw_base64``, the entity is built from zeroes and those bytes are lost.
    """
    name = str(document.get("format", "")).lower()
    cls = BY_NAME.get(name)
    if cls is None:
        raise ValueError(f"unknown entity format {document.get('format')!r}")

    entity = _starting_entity(document, base, cls, name)
    _apply_fields(entity, document.get("fields") or {})
    if "is_egg" in document and hasattr(entity, "SLOT_EGG"):
        object.__setattr__(entity, "is_egg", bool(document["is_egg"]))
    entity.refresh_checksum()
    return entity


def _starting_entity(document: dict[str, Any], base, cls, name: str):
    """What to apply the document's fields on top of.

    The original bytes are best, the slot being overwritten is next, and a
    zeroed record is the last resort; only that one loses the bytes no field
    covers.
    """
    japanese = bool(document.get("japanese", False))
    raw = document.get("raw_base64")
    if raw:
        return from_bytes(base64.b64decode(raw), extension=name, japanese=japanese)
    if base is not None and isinstance(base, cls):
        return base.clone()
    return cls(japanese=japanese)


#: Text fields the layout does not own, exposed as ordinary attributes.
TEXT_ATTRIBUTES = {
    "Nickname": "nickname",
    "OriginalTrainerName": "original_trainer_name",
    "HandlingTrainerName": "handling_trainer_name",
}


def _apply_fields(entity, fields: dict[str, Any]) -> None:
    """Write only what the document actually changes.

    Fields overlap, and text fields are followed by "trash": bytes left over
    from a previous name that the games keep and that PKHeX preserves.
    Re-encoding an unchanged value would clear them and alter a file that
    should have been untouched.

    A key this format does not have is rejected rather than skipped. Dropping
    it silently is how an edit gets accepted and then lost, which is the same
    failure ``LayoutBase.__setattr__`` and ``SaveFile.apply_trainer`` refuse.
    """
    by_pkhex = {f.pkhex_name: f for f in type(entity)._fields.values()}
    for key, value in fields.items():
        field = by_pkhex.get(key)
        if field is not None:
            if field.readonly:
                # Derived, and exported so the document reads well. There is
                # nothing to write back, and saying so would break every round
                # trip of a document this code produced.
                continue
            # A field outside this buffer cannot be compared, and writing it
            # would run past the end. Same reasoning as to_dict above.
            if not field.fits(entity):
                continue
            if _encode(field.decode(entity)) == value:
                continue
            field.encode(entity,
                         bytes.fromhex(value) if field.kind == "span" else value)
            continue
        attr = TEXT_ATTRIBUTES.get(key)
        if attr is None:
            raise ValueError(
                f"{type(entity).__name__} has no field {key!r}; writing it "
                "would not change the underlying bytes")
        if not hasattr(type(entity), attr):
            raise ValueError(
                f"{type(entity).__name__} does not store a {key}")
        try:
            if getattr(entity, attr) == value:
                continue
        except (AttributeError, ValueError, IndexError, KeyError):
            pass
        setattr(entity, attr, value)
