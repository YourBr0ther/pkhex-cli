"""End-to-end tests for the command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkhexpy import cli, saves


def run(*args: str) -> int:
    return cli.main(list(args))


def test_version_and_help() -> None:
    for flag in ("--version", "--help"):
        with pytest.raises(SystemExit) as exit_info:
            run(flag)
        assert exit_info.value.code == 0


def test_formats_lists_everything(capsys) -> None:
    assert run("formats") == 0
    out = capsys.readouterr().out
    assert "Entity formats" in out and "Save formats" in out
    for name in ("PK1", "PK9", "PA8", "SAV1", "SAV9SV", "SAV7b"):
        assert name in out, f"{name} missing from the format listing"


def test_missing_file_reports_cleanly(capsys) -> None:
    assert run("show", "/nonexistent/path") == 1
    assert "pkhexpy:" in capsys.readouterr().err


def test_unrecognized_file_reports_cleanly(tmp_path: Path, capsys) -> None:
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not a pokemon file" * 7)
    assert run("show", str(junk)) == 1
    assert "pkhexpy:" in capsys.readouterr().err


def test_known_save_size_gets_a_specific_message(tmp_path: Path, capsys) -> None:
    """A file the right length but the wrong shape should say so."""
    pretend = tmp_path / "main"
    pretend.write_bytes(bytes(0x6BE00))
    assert run("show", str(pretend)) == 1
    assert "right size for Sun/Moon" in capsys.readouterr().err


def test_malformed_json_reports_cleanly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("this is not json")
    assert run("from-json", str(bad)) == 1


def test_unknown_format_in_json_reports_cleanly(tmp_path: Path) -> None:
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps({"format": "NOPE", "fields": {}}))
    assert run("from-json", str(doc)) == 1


def test_save_json_without_raw_or_into_reports_cleanly(tmp_path: Path, capsys) -> None:
    doc = tmp_path / "save.json"
    doc.write_text(json.dumps({"schema": "pkhexpy/save/1", "boxes": []}))
    assert run("from-json", str(doc)) == 1
    assert "--into" in capsys.readouterr().err


# --- entity paths ----------------------------------------------------------


@pytest.fixture
def entity(entity_files: list[Path]) -> Path:
    return next(p for p in entity_files if p.suffix == ".pk9")


def test_show_entity(entity: Path, capsys) -> None:
    assert run("show", str(entity)) == 0
    out = capsys.readouterr().out
    for label in ("Format", "Species", "Nickname", "IVs", "Checksum"):
        assert label in out


def test_entity_json_round_trip(entity: Path, tmp_path: Path) -> None:
    doc = tmp_path / "e.json"
    out = tmp_path / "e.pk9"
    assert run("to-json", str(entity), "-o", str(doc)) == 0
    assert run("from-json", str(doc), "-o", str(out)) == 0
    assert out.read_bytes() == entity.read_bytes()


def test_no_raw_and_no_derived_drop_their_sections(entity: Path, tmp_path: Path) -> None:
    lean = tmp_path / "lean.json"
    assert run("to-json", str(entity), "--no-raw", "--no-derived", "-o", str(lean)) == 0
    document = json.loads(lean.read_text())
    assert "raw_base64" not in document
    assert "derived" not in document
    assert document["fields"]


def test_from_json_default_output_name(entity: Path, tmp_path: Path) -> None:
    doc = tmp_path / "named.json"
    assert run("to-json", str(entity), "-o", str(doc)) == 0
    assert run("from-json", str(doc)) == 0
    assert (tmp_path / "named.pk9").exists()


def test_editing_an_entity_through_json(entity: Path, tmp_path: Path, capsys) -> None:
    doc = tmp_path / "e.json"
    out = tmp_path / "edited.pk9"
    assert run("to-json", str(entity), "-o", str(doc)) == 0
    document = json.loads(doc.read_text())
    document["fields"]["Nickname"] = "Renamed"
    doc.write_text(json.dumps(document, ensure_ascii=False))
    assert run("from-json", str(doc), "-o", str(out)) == 0

    capsys.readouterr()
    assert run("show", str(out)) == 0
    assert "Renamed" in capsys.readouterr().out


# --- save paths ------------------------------------------------------------


def test_show_save(save_file: Path, capsys) -> None:
    assert run("show", str(save_file)) == 0
    out = capsys.readouterr().out
    for label in ("Game", "Trainer", "Checksums", "Party", "Boxes"):
        assert label in out


def test_boxes_lists_stored_pokemon(save_file: Path, capsys) -> None:
    assert run("boxes", str(save_file)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 100


def test_save_json_round_trip(save_file: Path, tmp_path: Path) -> None:
    doc = tmp_path / "s.json"
    out = tmp_path / "s.main"
    assert run("to-json", str(save_file), "-o", str(doc)) == 0
    assert run("from-json", str(doc), "-o", str(out)) == 0
    assert out.read_bytes() == save_file.read_bytes()


def test_save_round_trip_without_raw_needs_into(save_file: Path, tmp_path: Path) -> None:
    """Dropping raw keeps the JSON smaller; --into supplies the missing bytes."""
    doc = tmp_path / "s.json"
    out = tmp_path / "s.main"
    assert run("to-json", str(save_file), "--no-raw", "-o", str(doc)) == 0
    assert "raw_base64" not in json.loads(doc.read_text())
    assert run("from-json", str(doc), "--into", str(save_file), "-o", str(out)) == 0
    assert out.read_bytes() == save_file.read_bytes()


def test_party_only_skips_boxes(save_file: Path, tmp_path: Path) -> None:
    doc = tmp_path / "party.json"
    assert run("to-json", str(save_file), "--party-only", "-o", str(doc)) == 0
    document = json.loads(doc.read_text())
    assert "boxes" not in document
    assert document["party"]


def test_unicode_path_with_spaces(entity: Path, tmp_path: Path) -> None:
    folder = tmp_path / "dir with spaces"
    folder.mkdir()
    target = folder / "名前.pk9"
    target.write_bytes(entity.read_bytes())
    assert run("show", str(target)) == 0
    assert run("to-json", str(target), "-o", str(folder / "out.json")) == 0


def test_from_json_rejects_a_document_that_is_not_ours(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"hello": 1}')
    assert run("from-json", str(path), "-o", str(tmp_path / "x.pk9")) == 1
    assert "not a pkhexpy document" in capsys.readouterr().err


def test_from_json_rejects_json_that_is_not_an_object(tmp_path: Path, capsys) -> None:
    path = tmp_path / "arr.json"
    path.write_text("[1, 2, 3]")
    assert run("from-json", str(path), "-o", str(tmp_path / "x.pk9")) == 1
    assert "not a pkhexpy document" in capsys.readouterr().err


def test_into_must_match_the_document(real_saves: list[Path], tmp_path: Path,
                                      capsys) -> None:
    """Two saves of the same generation take each other's slot writes without
    complaint and the result checksums clean, so nothing downstream notices."""
    by_key: dict[str, Path] = {}
    for path in real_saves:
        try:
            sav = saves.from_bytes(path.read_bytes())
        except saves.SaveFormatError:
            continue
        by_key.setdefault(sav.KEY, path)
    if len(by_key) < 2:
        pytest.skip("need saves from two different games")
    first, second = (by_key[key] for key in list(by_key)[:2])
    document = tmp_path / "doc.json"
    assert run("to-json", str(first), "--no-raw", "-o", str(document)) == 0
    capsys.readouterr()
    assert run("from-json", str(document), "--into", str(second),
               "-o", str(tmp_path / "out.sav")) == 1
    assert "--into needs the file the JSON was exported from" in capsys.readouterr().err


def test_the_package_is_licensed_to_match_pkhex() -> None:
    """PKHeX is GPL-3.0. A derivative cannot add the AGPL network clause, so
    this must not drift back to AGPL because the two look alike.
    """
    root = Path(__file__).resolve().parent.parent
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert license_text.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "Remote Network Interaction" not in license_text, "this is the AGPL"
    assert "13. Use with the GNU Affero General Public License." in license_text

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = { text = "GPL-3.0-or-later" }' in pyproject
    assert "Affero" not in pyproject
