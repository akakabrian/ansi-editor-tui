"""Color palettes — 16 + 256 + ANSI SGR codes.

The 16-color palette maps durdraw indices 0–15 to RGB tuples. We don't use
terminal-specific color names; RGB lets the Textual/Rich render pipeline
paint exactly what the user picked regardless of the terminal theme.
"""

from __future__ import annotations

# Classic 16-color palette (standard VGA — matches Durdraw).
# Index convention:
#   0 black    1 blue     2 green    3 cyan
#   4 red      5 magenta  6 brown    7 light-gray
#   8 dark-gray 9 light-blue 10 light-green 11 light-cyan
#   12 light-red 13 light-magenta 14 yellow 15 white
PALETTE_16: list[tuple[int, int, int]] = [
    (0, 0, 0),        (0, 0, 170),      (0, 170, 0),      (0, 170, 170),
    (170, 0, 0),      (170, 0, 170),    (170, 85, 0),     (170, 170, 170),
    (85, 85, 85),     (85, 85, 255),    (85, 255, 85),    (85, 255, 255),
    (255, 85, 85),    (255, 85, 255),   (255, 255, 85),   (255, 255, 255),
]

# xterm 256-color table: 0-15 are the classic palette, 16-231 are a 6x6x6
# cube, 232-255 are grayscale. We generate the cube + grays programmatically.
def _build_256() -> list[tuple[int, int, int]]:
    pal: list[tuple[int, int, int]] = list(PALETTE_16)
    # 6×6×6 cube, indices 16..231
    steps = (0, 95, 135, 175, 215, 255)
    for r in range(6):
        for g in range(6):
            for b in range(6):
                pal.append((steps[r], steps[g], steps[b]))
    # Grayscale 232..255
    for i in range(24):
        v = 8 + i * 10
        pal.append((v, v, v))
    return pal


PALETTE_256: list[tuple[int, int, int]] = _build_256()


def rgb(index: int, mode: str = "16") -> tuple[int, int, int]:
    """Resolve a palette index to an RGB triple. Clamp out-of-range to a
    visible magenta so dev bugs are obvious, not silent."""
    pal = PALETTE_16 if mode == "16" else PALETTE_256
    if 0 <= index < len(pal):
        return pal[index]
    return (255, 0, 255)


# --- ANSI SGR codes (for .ans export) --------------------------------------

# Map 16-color indices to SGR foreground codes.
# 0–7 -> 30–37, 8–15 -> 90–97 (bright variants).
SGR_FG_16 = {
    0: 30, 1: 34, 2: 32, 3: 36, 4: 31, 5: 35, 6: 33, 7: 37,
    8: 90, 9: 94, 10: 92, 11: 96, 12: 91, 13: 95, 14: 93, 15: 97,
}
SGR_BG_16 = {
    0: 40, 1: 44, 2: 42, 3: 46, 4: 41, 5: 45, 6: 43, 7: 47,
    8: 100, 9: 104, 10: 102, 11: 106, 12: 101, 13: 105, 14: 103, 15: 107,
}


def sgr_fg(index: int, mode: str = "16") -> str:
    if mode == "16" and index in SGR_FG_16:
        return str(SGR_FG_16[index])
    # 256-color extended SGR.
    return f"38;5;{index}"


def sgr_bg(index: int, mode: str = "16") -> str:
    if mode == "16" and index in SGR_BG_16:
        return str(SGR_BG_16[index])
    return f"48;5;{index}"


def color_name(index: int) -> str:
    """Human label for index 0–15; stringified digit for higher."""
    names = [
        "black", "blue", "green", "cyan",
        "red", "magenta", "brown", "lt-gray",
        "dk-gray", "lt-blue", "lt-green", "lt-cyan",
        "lt-red", "lt-magenta", "yellow", "white",
    ]
    if 0 <= index < 16:
        return names[index]
    return str(index)
