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
    fields.py         descriptors for the trainer record
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

**A slot write must be checked before it becomes an offset.** An out-of-range
index used to be turned into an offset anyway and written, which is how a Red
save stopped being recognizable. `box_offset`, `box_slot_offset` and
`party_offset` check the index and delegate to `_box_offset`, `_box_slot_offset`
and `_party_offset`, so a generation supplying its own offset math cannot skip
the check. Gen1/2 pack their own lists, so the check lives in `_pack`/`_unpack`.

**A slot only takes its own format.** PK4 and PK5 share a stored size, so an
unchecked write succeeds and the bytes are reinterpreted under the wrong layout
with the save still checksumming clean. Everything writing a slot goes through
`_slot_bytes`, which checks the type and fits the buffer together.

**The party is a list, not six independent slots.** The games read a count and
expect the occupants at the front. `set_party_slot` raises the count when
appending, refuses a write that would leave a gap, and closes the gap on
removal. Let's Go stores its party as pointers into the box list, so it raises
rather than shifting entities the pointers still name.

**A trainer field that can be read must be writable.** `apply_dict` used to
drop the trainer block, and underneath it every trainer field was a getter with
no setter, so an edit was accepted and then lost. They are descriptors now
(`saves/fields.py`), declared once against a named region each save resolves to
a buffer and a base, which makes a read-only stored field impossible to write by
accident. What stays hand-written is what a descriptor would obscure: Gen3 money
XOR-ed with the security key, the binary-coded decimal of Gen1 and Gen2, BDSP's
inverted gender flag, and `play_time`, whose three units differ per generation.

**A field the JSON exports must be a field the JSON can import.** `apply_dict`
used to write party and boxes and drop the trainer block without a word, so an
edit to money or trainer name vanished into a file that reported success.
`apply_trainer` writes it and raises on any key it does not know, and
`serialize._apply_fields` does the same for the entity half, where a misspelled
field name was accepted and then lost.

**Base stats depend on the form, not just the species.** Giratina's two forms
swap Attack with Defense and Sp. Atk with Sp. Def, so a species-only lookup gets
four of six stats wrong. Alternate-form rows sit past the species rows in the
same personal table; `data.form_entry` follows the index PKHeX calls
`FormStatsIndex`.

**A format with its own stat formula returns nothing rather than guessing.**
Let's Go adds Awakening Values and a friendship scalar, Legends Arceus adds
Ganbaru values. Both set `STAT_FORMULA = None` so `calculated_stats` returns
None instead of a plausible wrong answer. The inverse costs just as much:
Stadium 2 sat on the default `"modern"` formula with a 252 EV cap while holding
Gen2 stat experience, and `test_every_format_reads_its_derived_properties`
exists because PKHeX ships no `.sk2` fixture for the file-driven tests to walk.

**Reading past the end of a buffer raises.** Both directions, every width.
`binio._w` refuses a write, and `_u` refuses a read, because a short slice
decodes to a plausible smaller number and a negative offset decodes to zero.
Where a field legitimately may not be there, as a stored-size record's party
stat block is not, ask `Field.fits()` rather than catching. Catching also
swallows the decoder bug you wanted to hear about.

**Equality is per format, and entities are unhashable.** PK8, PK9 and PA9 are
all 0x158 bytes, so comparing buffers alone made a zeroed one of each equal.
Gen1/2 keep the egg flag and the language outside the record, so those count
too. Nothing hashes an entity: the buffer is what every setter writes, so a
hash taken now goes stale on the next assignment. Key on `to_bytes()`.

## Testing

```sh
python3 -m pytest tests/ -q          # 59 on a bare clone; the rest skip

git clone --depth 1 https://github.com/kwsch/PKHeX.git reference_PKHeX
python3 -m pytest tests/ -q          # 88, with the .pkX fixtures

sh tools/fetch_test_saves.sh         # ~40 MB of real saves from public repos
python3 -m pytest tests/ -q          # 120, with the save corpus too
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
GPL-3.0. This port is GPL-3.0-or-later. Keep it that way, and keep the
attribution in the README intact.

PKHeX is GPL-3.0, not AGPL-3.0. The two are easy to confuse: PKHeX's license
text mentions Affero three times, but those are GPL-3.0's own section 13,
"Use with the GNU Affero General Public License", which permits combining with
AGPL code rather than declaring the work to be AGPL. A GPL-3.0 derivative
cannot be relicensed under AGPL-3.0, because section 10 forbids adding
restrictions and the AGPL network clause is one.
