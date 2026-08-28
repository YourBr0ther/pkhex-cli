<p align="center">
  <img src="assets/banner.png" alt="pkhex-cli" width="820">
</p>

<p align="center">
  <strong>Read Pokémon save files and individual Pokémon, convert them to JSON, edit the JSON, and write real game files back.</strong>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#command-line">CLI</a> ·
  <a href="#the-json">JSON format</a> ·
  <a href="#supported-formats">Formats</a> ·
  <a href="#verification">Verification</a>
</p>

---

`pkhex-cli` is a Python port of the file-format layer of
[PKHeX](https://github.com/kwsch/PKHeX). It ships a library (`pkhexpy`) and a
command line tool (`pkhexpy`), reads every mainline save from Red through
Violet, and has no runtime dependencies.

The point is to get game data somewhere you can work with it. Once a save is
JSON you can query it, diff it, load it into a spreadsheet, or wire it into
something else, then push your edits back into a file the game will load.

```console
$ pkhexpy show ~/saves/violet/main
Game       Scarlet/Violet (generation 9)
Trainer    Chris [51328/59716]
Money      2434
Play time  5h 22m 8s
Checksums  valid

Party (5)
  1. Clodsire lv20
  2. Fuecoco lv15 *shiny*
  3. Lechonk lv15
```

## Install

```sh
pip install git+https://github.com/YourBr0ther/pkhex-cli.git
```

Or from a clone:

```sh
git clone https://github.com/YourBr0ther/pkhex-cli.git
cd pkhex-cli
pip install -e .
```

Python 3.10 or newer. Nothing else.

The installed package is `pkhexpy` and the command is `pkhexpy`; the repository
is `pkhex-cli`.

## Command line

```sh
pkhexpy show <file>              # readable summary of a save or a .pkX
pkhexpy boxes <save>             # every Pokémon in a save, one per line
pkhexpy to-json <file> [-o out]  # file to JSON (stdout if no -o)
pkhexpy from-json <json> [-o out]# JSON back to a game file
pkhexpy formats                  # what this build understands
```

`show` and `to-json` work out what you handed them. Saves are identified by
size plus a structural check, in the order PKHeX uses. Entity files fall back to
their extension when two formats share a length.

### Editing a save

```sh
pkhexpy to-json ~/saves/violet/main -o violet.json
# edit violet.json
pkhexpy from-json violet.json -o edited.main
```

Renaming one Pokémon this way changes 37 bytes of a 3 MB save and leaves every
checksum valid. Nothing else moves.

### Useful flags

`--no-raw` drops the embedded original bytes, which makes the JSON smaller.
Pair it with `--into <original>` on the way back so the bytes it cannot express
still survive:

```sh
pkhexpy to-json save.main --no-raw -o save.json
pkhexpy from-json save.json --into save.main -o edited.main
```

`--party-only` skips the boxes. `--indent -1` puts the JSON on one line.
`--encrypted` writes a .pkX in the form a save file stores rather than the
decrypted form PKHeX writes.

## Library

```python
from pkhexpy import saves
from pkhexpy.pkm import io, serialize

sav = saves.read_file("main")
print(sav.trainer_name, sav.money, sav.checksums_valid)

for box, slot, pk in sav.iter_boxes():
    print(box, slot, pk.species_name, pk.current_level, pk.is_shiny)

pk = sav.get_box_slot(0, 0)
pk.nickname = "Bulby"
pk.ivs = (31, 31, 31, 31, 31, 31)
sav.set_box_slot(0, 0, pk)
open("edited.main", "wb").write(sav.to_bytes())   # checksums recomputed
```

A single Pokémon works the same way:

```python
entity = io.read_file("pikachu.pk9")
document = serialize.to_dict(entity)
document["fields"]["EV_HP"] = 252
io.write_file("edited.pk9", serialize.from_dict(document))
```

## The JSON

An entity document has three parts.

**`fields`** is the editable view: one entry per byte-addressed field, keyed by
its PKHeX property name. `EV_HP` and `OriginalTrainerName` mean what they mean
in PKHeX. Change a value here and it lands in the bytes.

**`derived`** is read-only context. Species and move names, level, shininess,
met location, IV and EV totals. Importing ignores it. It exists so the JSON
reads without a lookup table on hand.

**`raw_base64`** is the original buffer. Importing starts from it and applies
only the fields you changed, so bytes no field covers survive untouched. Those
bytes are real: the games leave "trash" behind after a nickname, and PKHeX
preserves it.

```json
{
  "schema": "pkhexpy/entity/1",
  "format": "PK9",
  "generation": 9,
  "context": "gen9",
  "checksum_valid": true,
  "fields": {
    "Species": 89,
    "Nickname": "Muk",
    "EV_HP": 0,
    "IV_ATK": 27
  },
  "derived": {
    "SpeciesName": "Muk",
    "Level": 20,
    "IsShiny": true,
    "MoveNames": ["Minimize", "Disable", "Acid Spray", "Poison Fang"],
    "MetLocationName": "Pokémon GO"
  },
  "raw_base64": "..."
}
```

A save document wraps the same entity documents in `party` and `boxes`,
alongside `trainer` and the save's own `raw_base64`.

Name lists ship for ten languages. A Pokémon's stored language picks the list,
so a Japanese one reports Japanese names.

Generations 1 through 4 use per-language glyph tables rather than Unicode, so a
Japanese Pokémon from those games has no half-width Latin letters available.
Writing a nickname the target encoding cannot represent raises an error naming
the problem instead of silently storing an empty name.

## Supported formats

**Saves**, all 20:

| Generation | Games |
| --- | --- |
| 1–2 | Red/Blue/Yellow, Gold/Silver/Crystal |
| 3 | Ruby/Sapphire, Emerald, FireRed/LeafGreen |
| 4 | Diamond/Pearl, Platinum, HeartGold/SoulSilver |
| 5 | Black/White, Black 2/White 2 |
| 6–7 | X/Y, Omega Ruby/Alpha Sapphire, Sun/Moon, Ultra Sun/Ultra Moon, Let's Go |
| 8 | Sword/Shield, Brilliant Diamond/Shining Pearl, Legends Arceus |
| 9 | Scarlet/Violet, Legends Z-A |

Japanese and Korean releases, half-size GBA saves, and emulator saves with a
trailing real-time-clock footer all work. The footer is preserved on write.

**Individual Pokémon**, all 18:

| Generation | Formats |
| --- | --- |
| 1–2 | PK1, PK2, SK2 |
| 3 | PK3, CK3 (Colosseum), XK3 (XD) |
| 4 | PK4, BK4 (Battle Revolution), RK4 (Ranch) |
| 5 | PK5 |
| 6–7 | PK6, PK7, PB7 (Let's Go) |
| 8 | PK8, PB8 (BDSP), PA8 (Legends Arceus) |
| 9 | PK9, PA9 (Legends Z-A) |

## Verification

Everything here is measured against files this project did not generate. A save
built from my own reading of a format only proves the code agrees with itself.

**Individual Pokémon.** All 207 .pkX files in the PKHeX test corpus. PKHeX names
those files `{Species}{-Form}{★} - {Nickname} - {Checksum}{EncryptionConstant}`,
which makes the filename an independent statement of six values. All 207 agree
on every one, and all 207 round trip byte for byte through both the binary and
the JSON path.

Getting the encryption constant right matters most of the six: it is the value
the block shuffle and the stream cipher are both keyed from, so reading it from
the wrong place would corrupt everything downstream.

**Saves.** 60 real save files covering 20 games:

| Generation | Games with a real save behind them |
| --- | --- |
| 1 | Red, Yellow |
| 2 | Gold, Silver, Crystal |
| 3 | Ruby, Sapphire, Emerald, FireRed, LeafGreen |
| 4 | Diamond, Pearl, Platinum, HeartGold, SoulSilver |
| 5 | Black, White, Black 2, White 2 |
| 6 | X, Y, Omega Ruby, Alpha Sapphire |
| 7 | Sun, Moon, Ultra Sun, Ultra Moon, Let's Go Pikachu, Let's Go Eevee |
| 8 | Sword, Shield, Brilliant Diamond, Legends Arceus |
| 9 | Scarlet, Violet |

All 60 round trip byte for byte, binary and JSON. 18,513 Pokémon read out of
them, every one with a valid checksum.

**Field values.** Round trips prove no data is lost. They prove nothing about
interpretation, since reading a field from the wrong offset still writes it back
to that same wrong offset. So the test suite also reads every field of all
18,513 Pokémon and checks that no value exceeds what the field could hold, that
fields expected to vary are not stuck on one value, and that the level implied
by a Pokémon's experience matches the level the game stored.

Legends Z-A is the one save format with no real file behind it. No public dump
exists yet, so its geometry is exercised against a constructed save and should
be treated as unverified.

`tools/fetch_test_saves.sh` downloads the corpus, so the numbers above are
reproducible. The tests skip without it.

## Limits worth knowing

Writing an edited 3DS save back to real hardware needs a MemeCrypto signature,
which is not implemented. Sun/Moon and Ultra Sun/Ultra Moon files are otherwise
correct, and the existing signature is left alone rather than invalidated, so an
unedited file round trips byte for byte. Emulators that skip signature checks
load edited files without complaint.

There is no legality checking. PKHeX will tell you a Pokémon could never have
existed; this will not. It reads and writes what the bytes say.

Not covered: Colosseum, XD, Battle Revolution and Ranch *save* files, though the
Pokémon formats from those games are; GameCube memory-card containers (`.gci`);
Pokémon Bank and Pokéstock bulk binaries; Stadium saves.

Some dumps in the wild are still console-encrypted or wrapped in a container the
dumper added. Those are rejected with a message saying so rather than parsed
into nonsense.

## How it is built

Most of the byte layout is generated, not transcribed. PKHeX writes its entity
classes as walls of one-line properties that each read a fixed offset, so
`tools/extract_fields.py` parses those C# properties and `tools/gen_pkm.py`
emits Python descriptor classes from them. That covers 2,728 fields across 24
classes. A property matching no known pattern is reported rather than dropped,
and the handful that are logic rather than an offset are written by hand in
`src/pkhexpy/pkm/formats.py`.

The character tables, name lists in ten languages, experience curves, growth
rates, species id conversion tables, and save block tables come out of the PKHeX
resources the same way.

To regenerate everything, clone PKHeX into `reference_PKHeX/` and run:

```sh
sh tools/gen_tables.sh
python3 tools/gen_data.py
python3 tools/gen_blocks.py
python3 tools/extract_fields.py <PKM sources> > tools/_raw_fields.json
python3 tools/gen_pkm.py tools/_raw_fields.json src/pkhexpy/pkm/_layouts.py
```

`tools/make_artwork.py` regenerates the icon and banner. Both are drawn from
geometry rather than set in a typeface, so they render identically anywhere and
need no fonts installed.

## Development

```sh
python3 -m pytest tests/ -q          # 73 tests, no downloads needed

sh tools/fetch_test_saves.sh         # ~40 MB of real saves
python3 -m pytest tests/ -q          # 85, including the corpus
```

Tests needing the PKHeX fixtures skip when `reference_PKHeX/` is missing; point
`PKHEX_REFERENCE` elsewhere to move it. Tests needing real saves skip when
`test-saves/` is missing; `PKHEXPY_SAVES` moves that one.

The save corpus comes from four public collections, none of it vendored here:
[ncorgan/pksav-test-saves](https://github.com/ncorgan/pksav-test-saves) for
generations 1 to 4,
[ReignOfComputer/RoCs-PC](https://github.com/ReignOfComputer/RoCs-PC) for 2 to
6, [Viren070/NX_Saves](https://github.com/Viren070/NX_Saves) for the Switch
games, and
[SHRetro/Pokemon-Home-and-Save-File-Backups](https://github.com/SHRetro/Pokemon-Home-and-Save-File-Backups)
for the Brilliant Diamond and Violet saves.

## Credit and license

Every byte offset, checksum, and encryption routine here comes from
[PKHeX](https://github.com/kwsch/PKHeX) by Kurt (kwsch), which is AGPL-3.0. This
port is AGPL-3.0 as well. See [LICENSE](LICENSE).

Pokémon is a trademark of Nintendo, Creatures Inc., and GAME FREAK Inc. This
project is not affiliated with them, or with PKHeX.
