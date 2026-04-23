"""Character set handling.

Two modes:
 - "cp437" — the classic PC codepage used by DOS ANSI art (pipes, blocks,
   shades, box-drawing glyphs in codes 0xB0–0xDF etc.)
 - "unicode" — the equivalent Unicode block-drawing range (U+2500–U+259F).

The picker widget shows 16 rows of 16 glyphs (256 total) for cp437 mode, or
a curated set of common drawing + shading characters for unicode mode.
"""

from __future__ import annotations

# CP437 glyph table. Index = byte value (0..255), value = the Unicode char
# that displays as the CP437 glyph. We use the mapping from the Python
# codec "cp437" so round-trip through bytes stays lossless.
_CP437_TABLE: list[str] = [chr(i) if i >= 0x20 and i < 0x7F else "?" for i in range(256)]
# Decode bytes 0..255 via cp437 to get the actual glyph mapping — this is
# where the "magic" PC-ANSI characters (smileys, blocks, etc.) live.
_CP437_TABLE = [bytes([i]).decode("cp437", errors="replace") for i in range(256)]


def cp437_glyphs() -> list[str]:
    """The canonical 256-glyph CP437 table (for the palette picker)."""
    return list(_CP437_TABLE)


# Curated Unicode drawing set for the Unicode mode picker. One row per
# category so the picker reads as "categories of glyphs" not "alphabet soup".
UNICODE_PICKER: list[str] = list(
    # Shade blocks (density)
    " ░▒▓█"
    # Half blocks / rectangles
    "▀▁▂▃▄▅▆▇▉▊▋▌▍▎▏▐"
    # Quadrant shapes
    "▖▗▘▙▚▛▜▝▞▟"
    # Box-drawing (light + heavy, corners + crosses)
    "─│┌┐└┘├┤┬┴┼━┃┏┓┗┛┣┫┳┻╋"
    # Double-line box-drawing
    "═║╔╗╚╝╠╣╦╩╬"
    # Arrows + pointers
    "←↑→↓↖↗↘↙↔↕"
    # Dots + misc
    "•◦●○◉◎◆◇■□▪▫"
    # Stars, hearts, faces, geometric
    "★☆♥♦♣♠♪♫☺☻☼"
    # Common ASCII punctuation/symbols for tiling
    "!@#$%^&*()-_=+[]{}\\|;:'\",.<>/?`~"
)


def glyphs_for(mode: str) -> list[str]:
    if mode == "cp437":
        return cp437_glyphs()
    return UNICODE_PICKER
