"""Generate the project icon and banner.

Everything is drawn from geometry rather than set in a typeface, so the output
is identical on any machine and needs no fonts installed. Run:

    python3 tools/make_artwork.py
"""

from __future__ import annotations

import os
from pathlib import Path

# Homebrew installs cairo outside the default dyld search path on macOS.
os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")

OUT = Path("assets")

# Deep slate plate, amber for the structure, pale mint for the data.
PLATE_TOP = "#20243A"
PLATE_BOTTOM = "#13151F"
EDGE = "#333A55"
AMBER = "#F2A93B"
AMBER_DIM = "#8A6224"
MINT = "#7FE3C0"
INK = "#EEF1F8"
MUTED = "#8F97AE"


def brace(x: float, cy: float, height: float, width: float, thickness: float,
          flip: bool = False) -> str:
    """A curly brace drawn as a stroked path, centred vertically on ``cy``."""
    d = -1 if flip else 1
    top, bottom = cy - height / 2, cy + height / 2
    w = width * d
    path = (
        f"M {x + w} {top} "
        f"C {x + w * 0.35} {top}, {x + w * 0.45} {top + height * 0.06}, {x + w * 0.45} {top + height * 0.16} "
        f"L {x + w * 0.45} {cy - height * 0.10} "
        f"C {x + w * 0.45} {cy - height * 0.03}, {x + w * 0.2} {cy}, {x} {cy} "
        f"C {x + w * 0.2} {cy}, {x + w * 0.45} {cy + height * 0.03}, {x + w * 0.45} {cy + height * 0.10} "
        f"L {x + w * 0.45} {bottom - height * 0.16} "
        f"C {x + w * 0.45} {bottom - height * 0.06}, {x + w * 0.35} {bottom}, {x + w} {bottom}"
    )
    return (f'<path d="{path}" fill="none" stroke="{AMBER}" '
            f'stroke-width="{thickness}" stroke-linecap="round" stroke-linejoin="round"/>')


def cartridge(cx: float, cy: float, w: float, h: float, scale: float = 1.0) -> str:
    """A game cartridge silhouette: rounded body, notched shoulder, contacts."""
    x, y = cx - w / 2, cy - h / 2
    notch = w * 0.30
    shoulder = h * 0.26
    r = w * 0.10
    body = (
        f"M {x + r} {y} L {x + w - notch} {y} L {x + w - notch} {y + shoulder} "
        f"L {x + w - r} {y + shoulder} Q {x + w} {y + shoulder} {x + w} {y + shoulder + r} "
        f"L {x + w} {y + h - r} Q {x + w} {y + h} {x + w - r} {y + h} "
        f"L {x + r} {y + h} Q {x} {y + h} {x} {y + h - r} "
        f"L {x} {y + r} Q {x} {y} {x + r} {y} Z"
    )
    parts = [f'<path d="{body}" fill="{MINT}" opacity="0.92"/>']
    # Contact pins along the bottom edge.
    pin_w, gap = w * 0.11, w * 0.055
    total = pin_w * 4 + gap * 3
    px = cx - total / 2
    for i in range(4):
        parts.append(
            f'<rect x="{px + i * (pin_w + gap):.2f}" y="{y + h - h * 0.20:.2f}" '
            f'width="{pin_w:.2f}" height="{h * 0.13:.2f}" rx="{pin_w * 0.25:.2f}" '
            f'fill="{PLATE_BOTTOM}" opacity="0.75"/>')
    # Label window on the upper body.
    parts.append(
        f'<rect x="{x + w * 0.16:.2f}" y="{y + h * 0.30:.2f}" '
        f'width="{w * 0.52:.2f}" height="{h * 0.26:.2f}" rx="{w * 0.05:.2f}" '
        f'fill="{PLATE_BOTTOM}" opacity="0.45"/>')
    return "".join(parts)


def icon() -> str:
    size = 512
    cx = cy = size / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" \
width="{size}" height="{size}" role="img" aria-label="pkhex-cli">
  <defs>
    <linearGradient id="plate" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{PLATE_TOP}"/>
      <stop offset="1" stop-color="{PLATE_BOTTOM}"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="116" fill="url(#plate)"/>
  <rect x="6" y="6" width="{size - 12}" height="{size - 12}" rx="112"
        fill="none" stroke="{EDGE}" stroke-width="4"/>
  {brace(150, cy, 260, 46, 22)}
  {brace(362, cy, 260, 46, 22, flip=True)}
  {cartridge(cx, cy, 134, 178)}
</svg>
"""


def banner() -> str:
    w, h = 1280, 320
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img" aria-label="pkhex-cli banner">',
        '<defs>'
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{PLATE_TOP}"/>'
        f'<stop offset="1" stop-color="{PLATE_BOTTOM}"/></linearGradient>'
        '</defs>',
        f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
    ]

    # Byte field on the left, thinning out as it moves right: raw data becoming
    # structure. Deterministic so the banner is reproducible.
    seed = 20260827
    cols, rows = 26, 9
    for r in range(rows):
        for c in range(cols):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            fade = 1 - (c / cols)
            if (seed >> 16) % 100 > 34 + fade * 52:
                continue
            x = 44 + c * 15
            y = 46 + r * 26
            parts.append(f'<rect x="{x}" y="{y}" width="9" height="9" rx="2" '
                         f'fill="{AMBER_DIM}" opacity="{0.16 + fade * 0.5:.2f}"/>')

    parts.append(brace(486, h / 2, 190, 34, 15))
    parts.append(cartridge(566, h / 2, 96, 122))
    parts.append(brace(648, h / 2, 190, 34, 15, flip=True))

    # Wordmark, drawn as geometry.
    parts.append(word_mark(738, 126, 8.4))
    parts.append(f'<rect x="738" y="162" width="458" height="2" fill="{EDGE}"/>')
    parts.append(tagline(738, 188))
    parts.append(gen_pips(738, 234))
    parts.append("</svg>")
    return "\n".join(parts)


# --- geometric type --------------------------------------------------------
# A compact 5x7 stroke font, enough for the wordmark and tagline.

GLYPHS: dict[str, list[tuple[float, float, float, float]]] = {}


def _g(ch: str, segments: list[tuple[float, float, float, float]]) -> None:
    GLYPHS[ch] = segments


_g("p", [(0, 2, 0, 9), (0, 2, 3, 2), (3, 2, 3, 5), (0, 5, 3, 5)])
_g("k", [(0, 0, 0, 7), (3, 3, 0, 5), (0, 5, 3, 7)])
_g("h", [(0, 0, 0, 7), (0, 3, 3, 3), (3, 3, 3, 7)])
_g("e", [(3, 3, 0, 3), (0, 3, 0, 7), (0, 7, 3, 7), (0, 5, 3, 5)])
_g("x", [(0, 3, 3, 7), (3, 3, 0, 7)])
_g("c", [(3, 3, 0, 3), (0, 3, 0, 7), (0, 7, 3, 7)])
_g("l", [(0.8, 0, 0.8, 7)])
_g("i", [(1, 1, 1, 1.4), (1, 3, 1, 7)])
_g("-", [(0, 5, 3, 5)])
_g(" ", [])
_g("j", [(2, 1, 2, 1.4), (2, 3, 2, 7), (2, 7, 0, 7)])
_g("s", [(3, 3, 0, 3), (0, 3, 0, 5), (0, 5, 3, 5), (3, 5, 3, 7), (3, 7, 0, 7)])
_g("o", [(0, 3, 3, 3), (3, 3, 3, 7), (3, 7, 0, 7), (0, 7, 0, 3)])
_g("n", [(0, 3, 0, 7), (0, 3, 3, 3), (3, 3, 3, 7)])
_g("a", [(0, 3, 3, 3), (3, 3, 3, 7), (0, 5, 3, 5), (0, 5, 0, 7), (0, 7, 3, 7)])
_g("v", [(0, 3, 1.5, 7), (1.5, 7, 3, 3)])
_g("d", [(3, 0, 3, 7), (3, 3, 0, 3), (0, 3, 0, 7), (0, 7, 3, 7)])
_g("t", [(1, 1, 1, 7), (1, 7, 3, 7), (0, 3, 3, 3)])
_g("r", [(0, 3, 0, 7), (0, 3, 3, 3)])
_g("m", [(0, 3, 0, 7), (0, 3, 3, 3), (1.5, 3, 1.5, 7), (3, 3, 3, 7)])
_g("f", [(3, 1, 1, 1), (1, 1, 1, 7), (0, 3, 3, 3)])
_g("g", [(3, 3, 0, 3), (0, 3, 0, 7), (0, 7, 3, 7), (3, 3, 3, 9), (3, 9, 0, 9)])
_g("u", [(0, 3, 0, 7), (0, 7, 3, 7), (3, 3, 3, 7)])
_g("y", [(0, 3, 0, 5), (0, 5, 3, 5), (3, 3, 3, 9), (3, 9, 0, 9)])
_g("b", [(0, 0, 0, 7), (0, 3, 3, 3), (3, 3, 3, 7), (0, 7, 3, 7)])
_g("w", [(0, 3, 0.7, 7), (0.7, 7, 1.5, 4), (1.5, 4, 2.3, 7), (2.3, 7, 3, 3)])
_g(".", [(1, 7, 1.4, 7)])
_g("0", [(0, 0, 3, 0), (3, 0, 3, 7), (3, 7, 0, 7), (0, 7, 0, 0)])
_g("1", [(0.6, 1, 1.6, 0), (1.6, 0, 1.6, 7), (0.4, 7, 2.8, 7)])
_g("2", [(0, 0, 3, 0), (3, 0, 3, 3.5), (3, 3.5, 0, 3.5), (0, 3.5, 0, 7), (0, 7, 3, 7)])
_g("3", [(0, 0, 3, 0), (3, 0, 3, 7), (3, 7, 0, 7), (0, 3.5, 3, 3.5)])
_g("4", [(0, 0, 0, 3.5), (0, 3.5, 3, 3.5), (3, 0, 3, 7)])
_g("5", [(3, 0, 0, 0), (0, 0, 0, 3.5), (0, 3.5, 3, 3.5), (3, 3.5, 3, 7), (3, 7, 0, 7)])
_g("6", [(3, 0, 0, 0), (0, 0, 0, 7), (0, 7, 3, 7), (3, 7, 3, 3.5), (3, 3.5, 0, 3.5)])
_g("7", [(0, 0, 3, 0), (3, 0, 3, 7)])
_g("8", [(0, 0, 3, 0), (3, 0, 3, 7), (3, 7, 0, 7), (0, 7, 0, 0), (0, 3.5, 3, 3.5)])
_g("9", [(3, 3.5, 0, 3.5), (0, 3.5, 0, 0), (0, 0, 3, 0), (3, 0, 3, 7), (3, 7, 0, 7)])


def _draw(text: str, x: float, y: float, unit: float, colour: str,
          weight: float, spacing: float = 1.9) -> str:
    out, cursor = [], x
    for ch in text:
        for x1, y1, x2, y2 in GLYPHS.get(ch, []):
            out.append(
                f'<line x1="{cursor + x1 * unit:.2f}" y1="{y + y1 * unit:.2f}" '
                f'x2="{cursor + x2 * unit:.2f}" y2="{y + y2 * unit:.2f}" '
                f'stroke="{colour}" stroke-width="{weight:.2f}" stroke-linecap="round"/>')
        cursor += (3 + spacing) * unit if ch != " " else 2.6 * unit
    return "".join(out)


def word_mark(x: float, y: float, unit: float) -> str:
    return (_draw("pkhex", x, y - 7 * unit, unit, INK, unit * 0.78)
            + _draw("-cli", x + (3 + 1.9) * unit * 5, y - 7 * unit, unit, AMBER, unit * 0.78))


def tagline(x: float, y: float) -> str:
    return _draw("pokemon save files as json", x, y, 4.2, MUTED, 2.5, spacing=2.0)


def gen_pips(x: float, y: float) -> str:
    """One pip per generation, each carrying its number: the coverage at a glance."""
    radius = 13.0
    unit = 1.85                     # glyphs are 3 units wide and 7 tall
    out = [_draw("gen", x, y + 4, 3.6, MUTED, 2.1, spacing=2.0)]
    start = x + 80
    for i in range(9):
        cx, cy = start + i * 33, y + 13
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{AMBER}"/>')
        out.append(_draw(str(i + 1), cx - 1.5 * unit, cy - 3.5 * unit, unit,
                         PLATE_BOTTOM, 2.1, spacing=2.0))
    return "".join(out)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "icon.svg").write_text(icon())
    (OUT / "banner.svg").write_text(banner())
    try:
        import cairosvg
    except ImportError:
        print("wrote SVGs; install cairosvg for PNGs")
        return
    cairosvg.svg2png(url=str(OUT / "icon.svg"), write_to=str(OUT / "icon.png"),
                     output_width=512, output_height=512)
    cairosvg.svg2png(url=str(OUT / "icon.svg"), write_to=str(OUT / "icon-128.png"),
                     output_width=128, output_height=128)
    cairosvg.svg2png(url=str(OUT / "banner.svg"), write_to=str(OUT / "banner.png"),
                     output_width=1280, output_height=320)
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
