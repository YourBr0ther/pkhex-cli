#!/bin/sh
# Download the real save files this project validates against.
#
# None of them are vendored here, since they are other people's game saves.
# They come from three public collections:
#   ncorgan/pksav-test-saves  Gen1-4, made for testing the PKSav C library
#   ReignOfComputer/RoCs-PC   Gen2-6, a living-dex collection
#   Viren070/NX_Saves         Gen7-9 Switch saves
#   SHRetro/Pokemon-Home-...  Gen3-9, including the only Brilliant Diamond and
#                             Violet saves I could find
#
# Usage: sh tools/fetch_test_saves.sh [destination]   (default: ./test-saves)
set -e
DEST="${1:-test-saves}"
mkdir -p "$DEST"

echo "pksav-test-saves (Gen1-4)..."
if [ ! -d "$DEST/pksav" ]; then
  git clone --depth 1 -q https://github.com/ncorgan/pksav-test-saves.git "$DEST/pksav"
fi

echo "RoCs-PC (Gen2-6)..."
mkdir -p "$DEST/rocs"
python3 - "$DEST/rocs" <<'PY'
import json, os, sys, urllib.parse, urllib.request
dest = sys.argv[1]
api = "https://api.github.com/repos/ReignOfComputer/RoCs-PC/git/trees/master?recursive=1"
raw = "https://raw.githubusercontent.com/ReignOfComputer/RoCs-PC/master/"
for entry in json.load(urllib.request.urlopen(api))["tree"]:
    path = entry["path"]
    if not path.lower().endswith((".sav", "main")):
        continue
    tag = [s for s in path.split("/") if " - " in s]
    label = tag[-1].split(" - ")[-1].replace(" ", "_") if tag else "save"
    name = f"{label}__{os.path.basename(path)}".replace(" ", "_")
    out = os.path.join(dest, name)
    if os.path.exists(out):
        continue
    urllib.request.urlretrieve(raw + urllib.parse.quote(path), out)
    print("  ", name)
PY

echo "NX_Saves (Gen7-9 Switch)..."
mkdir -p "$DEST/switch"
python3 - "$DEST/switch" <<'PY'
import json, os, sys, urllib.parse, urllib.request, zipfile, hashlib
dest = sys.argv[1]
api = "https://api.github.com/repos/Viren070/NX_Saves/git/trees/main?recursive=1"
raw = "https://raw.githubusercontent.com/Viren070/NX_Saves/main/"
want = ("Pokemon Scarlet [English Post Game]",
        "Pokemon Sword [Girl Post Game All Pokemon]",
        "Pokemon Shield [Girl Post Game - Full Living Dex]",
        "Legends Arceus [Starter",
        "Pokemon Lets Go Pikachu [Super Starter Boy]")
for entry in json.load(urllib.request.urlopen(api))["tree"]:
    path = entry["path"]
    if not path.endswith(".zip") or not any(w in path for w in want):
        continue
    tag = hashlib.md5(path.encode()).hexdigest()[:8]
    folder = os.path.join(dest, tag)
    if os.path.isdir(folder):
        continue
    archive = folder + ".zip"
    urllib.request.urlretrieve(raw + urllib.parse.quote(path), archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(folder)
    os.remove(archive)
    print("  ", os.path.basename(path))
PY

echo "SHRetro backups (Gen3-9, incl. BDSP and Violet)..."
mkdir -p "$DEST/shretro"
python3 - "$DEST/shretro" <<'PY'
import json, os, sys, urllib.parse, urllib.request
dest = sys.argv[1]
api = "https://api.github.com/repos/SHRetro/Pokemon-Home-and-Save-File-Backups/git/trees/main?recursive=1"
raw = "https://raw.githubusercontent.com/SHRetro/Pokemon-Home-and-Save-File-Backups/main/"
# One save per game; "backup" copies are duplicates of "main".
seen = set()
for entry in sorted(json.load(urllib.request.urlopen(api))["tree"], key=lambda e: e["path"]):
    path = entry["path"]
    if entry["type"] != "blob" or entry.get("size", 0) < 0x8000:
        continue
    if not path.startswith("Save Files/") or os.path.basename(path) == "backup":
        continue
    game = path.split("/")[2].split(" - TID")[0]
    if game in seen:
        continue
    seen.add(game)
    name = (game + "__" + os.path.basename(path)).replace(" ", "_").replace("'", "")
    out = os.path.join(dest, name)
    if os.path.exists(out):
        continue
    urllib.request.urlretrieve(raw + urllib.parse.quote(path), out)
    print("  ", name)
PY

echo
echo "Done. Point the tests at it with:"
echo "    PKHEXPY_SAVES=$DEST python3 -m pytest tests/ -q"
