"""Canvas, frame, and movie data model.

- `Cell` is a (ch, fg, bg, attr) 4-tuple; attr is a bitmask (bold/blink/reverse).
- `Layer` is a 2D grid of cells for a single z-plane.
- `Frame` is a stack of layers plus a delay (for animation).
- `Movie` is a list of frames plus metadata — saved to `.dur`.

Characters with `ch == "\x00"` mean "transparent" on a layer; the compositor
shows the layer below. The bottom layer never shows transparent (we fall
through to space + default colors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List

# Attribute bitmask flags. Packed into one int so a cell tuple stays compact.
ATTR_NONE = 0
ATTR_BOLD = 1 << 0
ATTR_BLINK = 1 << 1
ATTR_REVERSE = 1 << 2
ATTR_UNDERLINE = 1 << 3

# Default colors — durdraw convention: fg 7 (light gray), bg 0 (black).
# Index 1 in the durdraw 16-color palette is blue-black which displays as
# "uncolored" in most terminals; we use 7 (white) + 0 (black) so new cells
# render visibly against the canvas bg.
DEFAULT_FG = 7
DEFAULT_BG = 0
TRANSPARENT = "\x00"  # layer transparency marker


@dataclass(frozen=True)
class Cell:
    """One character cell. Immutable so undo snapshots stay correct."""
    ch: str = " "
    fg: int = DEFAULT_FG
    bg: int = DEFAULT_BG
    attr: int = ATTR_NONE

    @classmethod
    def transparent(cls) -> "Cell":
        return cls(TRANSPARENT, DEFAULT_FG, DEFAULT_BG, ATTR_NONE)

    def is_transparent(self) -> bool:
        return self.ch == TRANSPARENT


class Layer:
    """2D grid of cells. Row-major (rows[y][x])."""

    def __init__(self, cols: int, rows: int, transparent: bool = False) -> None:
        self.cols = cols
        self.rows = rows
        self.name = "layer"
        self.visible = True
        fill = Cell.transparent() if transparent else Cell()
        self._grid: list[list[Cell]] = [
            [fill] * cols for _ in range(rows)
        ]

    def get(self, x: int, y: int) -> Cell:
        if 0 <= x < self.cols and 0 <= y < self.rows:
            return self._grid[y][x]
        return Cell()

    def set(self, x: int, y: int, cell: Cell) -> None:
        if 0 <= x < self.cols and 0 <= y < self.rows:
            self._grid[y][x] = cell

    def resize(self, cols: int, rows: int) -> None:
        """Grow or shrink, preserving overlapping region."""
        old = self._grid
        new: list[list[Cell]] = [[Cell()] * cols for _ in range(rows)]
        for y in range(min(rows, self.rows)):
            for x in range(min(cols, self.cols)):
                new[y][x] = old[y][x]
        self._grid = new
        self.cols, self.rows = cols, rows

    def iter_cells(self) -> Iterator[tuple[int, int, Cell]]:
        for y, row in enumerate(self._grid):
            for x, cell in enumerate(row):
                yield x, y, cell


@dataclass
class Frame:
    """One animation frame — stack of layers + playback delay (seconds)."""
    layers: list[Layer] = field(default_factory=list)
    delay: float = 0.1  # seconds on this frame during playback

    def composite(self, x: int, y: int) -> Cell:
        """Top-down walk through visible layers; return first non-transparent.
        If every layer is transparent at (x, y), return a default blank."""
        for layer in reversed(self.layers):
            if not layer.visible:
                continue
            c = layer.get(x, y)
            if not c.is_transparent():
                return c
        return Cell()


@dataclass
class Movie:
    """Full document — frames + metadata. Serialized to .dur."""
    cols: int = 80
    rows: int = 25
    framerate: float = 6.0
    color_format: str = "16"   # "16" or "256"
    encoding: str = "utf-8"    # "utf-8" or "cp437"
    name: str = ""
    artist: str = ""
    frames: list[Frame] = field(default_factory=list)

    def new_frame(self, transparent_top: bool = True) -> Frame:
        """Create a frame with 2 layers (the spec minimum)."""
        bottom = Layer(self.cols, self.rows, transparent=False)
        bottom.name = "bg"
        top = Layer(self.cols, self.rows, transparent=True)
        top.name = "fg"
        return Frame(layers=[bottom, top], delay=1.0 / self.framerate)

    @classmethod
    def blank(cls, cols: int = 80, rows: int = 25) -> "Movie":
        m = cls(cols=cols, rows=rows)
        m.frames.append(m.new_frame())
        return m

    @property
    def frame_count(self) -> int:
        return len(self.frames)
