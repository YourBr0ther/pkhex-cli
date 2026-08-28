# Changelog

Notable changes per release. Dates are UTC.

## Unreleased

### Added

- Pokémon stored outside the party and boxes are read and written, and appear
  in a save document's `extra` section. Depending on the generation: the
  daycare, a Battle Box team, Poké Pelago, the Grand Underground's encounter
  cache, GTS and Global Link uploads, a staged gift, a Surprise Trade in
  transit, the ride legendary, the Pokéwalker, and the Pokémon fused into
  Kyurem, Necrozma or Calyrex. 141 across the test corpus that were previously
  unreachable.
- Trainer name, both ID halves, gender, money and play time are writable in
  every generation. They were exported to JSON and silently dropped on import.
- `calculated_stats` recomputes battle stats from base stats, IVs, EVs, level
  and nature, and both it and the stored block appear in the JSON.
- Base stats follow the form, so Giratina's two forms no longer share a row.
- `py.typed`, so the annotations reach anything importing the package.

### Fixed

- Out-of-range slot indices are rejected. `set_party_slot(99, pk)` used to
  compute an offset anyway and write over unrelated save data.
- A slot only accepts an entity of its own format. PK4 and PK5 share a stored
  size, so writing one into the other's slot succeeded and reinterpreted the
  bytes under the wrong layout, with the save still checksumming clean.
- The party count is maintained. Appending left the new Pokémon invisible to
  the game; removing one left a hole at the front.
- `from-json` checks the document's schema, and `--into` checks that the save
  matches it. Neither did, so a mismatch reached the writers as a stack trace.
- Save formats this port does not read are named rather than reported as
  unrecognizable.
- Gen1 and Gen2 can write both names of the single Special value they store.

### Changed

- **Relicensed from AGPL-3.0 to GPL-3.0-or-later.** PKHeX is GPL-3.0, not
  AGPL-3.0, and this project's license choice rested on that mistake. A
  GPL-3.0 derivative cannot add the AGPL network clause, so GPL-3.0-or-later
  is the license upstream actually permits. Nothing here was ever published
  under the wrong terms.
- Reading a record out of a buffer, and declaring where extra storage lives,
  each happen one way rather than five and three.
- The trainer record is declared with descriptors, which makes a field that can
  be read but not written impossible to write by accident.
