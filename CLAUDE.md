# Working in this repository

A Python port of the file-format layer of [PKHeX](https://github.com/kwsch/PKHeX).
Reads Pokémon save files and individual Pokémon, converts them to JSON and back.
The package is `pkhexpy`, the command is `pkhexpy`, the repository is `pkhex-cli`.

## The one rule

**`src/pkhexpy/pkm/_layouts.py` is generated. Never edit it by hand.**

It holds 2,728 field definitions extracted from PKHeX's C# source. Editing it
means your change disappears the next time anyone regenerates. Field behaviour
that needs more than a byte offset belongs in `src/pkhexpy/pkm/formats.py`,
whose classes subclass the generated ones.

The same applies to `src/pkhexpy/strings/tables.py` and everything under
`src/pkhexpy/data/`.

## Layout

```
src/pkhexpy/
  binio.py            little/big-endian primitives over bytearray
  crypto.py           entity encryption: block shuffle + LCRNG cipher
  cli.py              argparse front end
  strings/            per-generation character encodings
    tables.py         GENERATED glyph tables for gen1-4
  pkm/
    _layouts.py       GENERATED field definitions, 24 classes
    fields.py         descriptor types (U8, Flag, Bits, PackedBits, Str, ...)
    layout.py         buffer ownership, field registry, string plumbing
    entity.py         derived behaviour shared by all formats
    formats.py        the 18 concrete classes, hand-written constants and logic
    io.py             format detection, file read/write
    serialize.py      entity <-> JSON
  saves/
    base.py           shared save behaviour, slot iteration, JSON
    detect.py         which game a file came from
    gen12/3/45/67/89/8b.py   one module per era
    swish.py          SCBlock storage for the Switch games
    checksums.py      CRC16 variants, sector sums
  data/               GENERATED name lists, locations, growth curves, block tables

tools/                the generators, plus fetch_test_saves.sh and make_artwork.py
tests/                pytest suite
```

## Regenerating

Clone PKHeX into `reference_PKHeX/` first. It is gitignored.

```sh
git clone --depth 1 https://github.com/kwsch/PKHeX.git reference_PKHeX

sh tools/gen_tables.sh          # character tables
python3 tools/gen_data.py       # names, locations, experience, personal, species ids
python3 tools/gen_blocks.py     # gen5-7 save block tables
python3 tools/extract_fields.py <PKM sources> --report-unhandled > tools/_raw_fields.json
python3 tools/gen_pkm.py tools/_raw_fields.json src/pkhexpy/pkm/_layouts.py
```

`--report-unhandled` lists every C# property the extractor could not translate.
Read that list. A property matching no known pattern is reported rather than
dropped, and the remainder are constants and derived logic that belong in
`formats.py`. If a *new* pattern appears there, teach `extract_fields.py` about
it instead of hand-writing the field.

## Invariants worth protecting

Each of these was a real bug caught by a real save file.

**Byte-exact round trips.** `read(file) -> write()` must return identical bytes
for an unmodified file, and so must the JSON path. This is the core test.

**Never rewrite a region you did not touch.** Gen2 keeps an older save in a
backup region with its own checksum. Gen3 has a Hall of Fame area past the two
save copies. Both are legitimately inconsistent with the primary save in real
files. Recomputing their checksums breaks byte-exactness and corrupts data
nothing in this library reads. Report them separately instead, as
`backup_checksum_valid` and `extra_sectors_valid` do.

**Slot writes must be exactly slot-sized.** `saves.base.fit()` exists because
assigning a shorter `bytes` into a `bytearray` slice *shrinks the buffer* and
shifts everything after it. A stored-size record written into a party-size slot
does exactly that.

**Unknown attributes must raise.** `LayoutBase.__setattr__` rejects assignment
to anything that is not a registered field. Without it, `pk.speceis = 25`
silently creates a Python attribute that never reaches the bytes, and every test
still passes.

**Slot presence is not `species != 0`.** Unused box slots hold leftover bytes
that decrypt to a nonsense species. Use `SaveFile.slot_present()`, which ports
PKHeX's per-generation check. Getting this wrong inflates counts and rewrites
slots the caller never touched.

**Gen1-4 text is per-language glyph tables, not Unicode.** A Japanese Gen3
Pokémon has no half-width Latin letters, so writing an ASCII nickname would
terminate the string at the first character. `Entity._write_name` decodes what
it just encoded and raises if the text did not survive.

**Base stats depend on the form, not just the species.** Giratina's two forms
swap Attack with Defense and Sp. Atk with Sp. Def, so a species-only lookup gets
four of six stats wrong. Alternate-form rows sit past the species rows in the
same personal table; `data.form_entry` follows the index PKHeX calls
`FormStatsIndex`.

**A format with its own stat formula returns nothing rather than guessing.**
Let's Go adds Awakening Values and a friendship scalar, Legends Arceus adds
Ganbaru values. Both set `STAT_FORMULA = None` so `calculated_stats` returns
None instead of a plausible wrong answer.

## Testing

```sh
python3 -m pytest tests/ -q          # 52 on a bare clone; the rest skip

git clone --depth 1 https://github.com/kwsch/PKHeX.git reference_PKHeX
python3 -m pytest tests/ -q          # 80, with the .pkX fixtures

sh tools/fetch_test_saves.sh         # ~40 MB of real saves from public repos
python3 -m pytest tests/ -q          # 93, with the save corpus too
```

`PKHEX_REFERENCE` moves the PKHeX checkout, `PKHEXPY_SAVES` moves the save
corpus. Tests skip cleanly when either is absent.

Prefer real files over constructed ones. Synthetic saves built from this
library's own understanding of a format only prove the library agrees with
itself. Every format-level bug found so far came from a real save, including a
wrong Sinnoh box stride, a Gen6 money offset four bytes off, and a BDSP version
constant read out of a code comment.

Two independent checks are worth knowing about:

- PKHeX names its test files
  `{Species}{-Form}{★} - {Nickname} - {Checksum}{EncryptionConstant}`, which
  `tests/test_entities.py` uses to verify six values per file without trusting
  any of this code.
- `tests/test_field_audit.py` reads every field of every Pokémon in the corpus
  and flags values outside what a field could hold, fields stuck on one value
  where variation is expected, and levels disagreeing with stored experience.

## Style

Match the surrounding code. Some specifics that already hold throughout:

- Docstrings say what a thing is for and why it is shaped that way, not what the
  next line does. Where a layout is strange, name the game behaviour that makes
  it strange.
- Comments earn their place by explaining a decision or a game quirk. Skip the
  ones that restate the code.
- No em dashes in prose or comments.
- Type hints on public functions; `from __future__ import annotations` at the top.
- No runtime dependencies. The standard library covers everything, including the
  SHA-256 and MD5 the Switch-era saves need.

## Artwork

`python3 tools/make_artwork.py` regenerates `assets/icon.svg`, `assets/banner.svg`
and their PNGs. Both are drawn from geometry, including the lettering, so they
render identically on any machine and need no fonts installed. On macOS the
script points cairosvg at Homebrew's cairo.

## Licensing

Every byte offset, checksum, and encryption routine comes from PKHeX, which is
AGPL-3.0. This port is AGPL-3.0. Keep it that way, and keep the attribution in
the README intact.
