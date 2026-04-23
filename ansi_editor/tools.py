"""Drawing tools.

Each tool consumes cursor / drag / commit events and returns a batch of
`Edit(x, y, old_cell, new_cell)` tuples. The Editor applies them to the
canvas and pushes the batch onto the undo stack.

This decouples tool logic from canvas mutation, and makes undo/redo just
"apply old", "apply new" over a batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .canvas import Cell, Layer


@dataclass(frozen=True)
class Edit:
    x: int
    y: int
    old: Cell
    new: Cell


def _paint(layer: Layer, x: int, y: int, new: Cell) -> Edit | None:
    """Return an Edit describing the write, or None if out of bounds /
    the write is a no-op (already-same cell)."""
    if not (0 <= x < layer.cols and 0 <= y < layer.rows):
        return None
    old = layer.get(x, y)
    if old == new:
        return None
    return Edit(x, y, old, new)


# ---- Pencil ---------------------------------------------------------------

class PencilTool:
    """Single cell per position. Drag paints a line of cells via Bresenham."""
    name = "pencil"

    def __init__(self) -> None:
        self._pending: list[Edit] = []
        self._last: tuple[int, int] | None = None
        self._seen: set[tuple[int, int]] = set()

    def begin(self, layer: Layer, x: int, y: int, cell: Cell) -> list[Edit]:
        self._pending = []
        self._seen = set()
        self._last = (x, y)
        e = _paint(layer, x, y, cell)
        if e is not None and (x, y) not in self._seen:
            self._pending.append(e)
            self._seen.add((x, y))
        return self._pending[:]

    def drag(self, layer: Layer, x: int, y: int, cell: Cell) -> list[Edit]:
        """Paint a Bresenham line from last to (x,y)."""
        if self._last is None:
            return self.begin(layer, x, y, cell)
        x0, y0 = self._last
        new: list[Edit] = []
        for px, py in _line(x0, y0, x, y):
            if (px, py) in self._seen:
                continue
            e = _paint(layer, px, py, cell)
            if e is not None:
                new.append(e)
                self._seen.add((px, py))
        self._pending.extend(new)
        self._last = (x, y)
        return new

    def commit(self) -> list[Edit]:
        batch = self._pending
        self._pending = []
        self._last = None
        self._seen = set()
        return batch


# ---- Eraser ---------------------------------------------------------------

class EraserTool(PencilTool):
    """Same as pencil but writes a blank cell."""
    name = "eraser"

    def begin(self, layer, x, y, cell):
        return super().begin(layer, x, y, Cell())

    def drag(self, layer, x, y, cell):
        return super().drag(layer, x, y, Cell())


# ---- Fill (flood) ---------------------------------------------------------

class FillTool:
    """4-connected flood fill. Replaces contiguous region matching the
    cell at (x, y)."""
    name = "fill"

    def begin(self, layer: Layer, x: int, y: int, cell: Cell) -> list[Edit]:
        if not (0 <= x < layer.cols and 0 <= y < layer.rows):
            return []
        target = layer.get(x, y)
        if target == cell:
            return []
        edits: list[Edit] = []
        seen: set[tuple[int, int]] = set()
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            if not (0 <= cx < layer.cols and 0 <= cy < layer.rows):
                continue
            if layer.get(cx, cy) != target:
                continue
            seen.add((cx, cy))
            edits.append(Edit(cx, cy, target, cell))
            stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
        self._batch = edits
        return edits

    def drag(self, layer, x, y, cell):
        return []  # one-shot tool

    def commit(self) -> list[Edit]:
        return getattr(self, "_batch", [])


# ---- Line (preview + commit on release) -----------------------------------

class LineTool:
    """Interactive line from begin-anchor to current drag position."""
    name = "line"

    def __init__(self) -> None:
        self._anchor: tuple[int, int] | None = None
        self._last_batch: list[Edit] = []

    def begin(self, layer, x, y, cell):
        self._anchor = (x, y)
        self._last_batch = []
        e = _paint(layer, x, y, cell)
        return [e] if e is not None else []

    def drag(self, layer, x, y, cell):
        """Line tools ARE destructive during drag — we preview by letting the
        editor call commit() on every drag update. But here we just return
        the full line from anchor to (x,y) so the editor can revert on next
        drag. Strategy: the Editor treats every drag as a "transaction" —
        it reverts the previous batch, applies the new one."""
        if self._anchor is None:
            return []
        x0, y0 = self._anchor
        edits: list[Edit] = []
        seen: set[tuple[int, int]] = set()
        for px, py in _line(x0, y0, x, y):
            if (px, py) in seen:
                continue
            e = _paint(layer, px, py, cell)
            if e is not None:
                edits.append(e)
                seen.add((px, py))
        self._last_batch = edits
        return edits

    def commit(self) -> list[Edit]:
        batch = self._last_batch
        self._anchor = None
        self._last_batch = []
        return batch


# ---- Rectangle ------------------------------------------------------------

class RectangleTool:
    """Outline rectangle from begin-anchor to current position."""
    name = "rectangle"

    def __init__(self, filled: bool = False) -> None:
        self._anchor: tuple[int, int] | None = None
        self._last_batch: list[Edit] = []
        self.filled = filled

    def begin(self, layer, x, y, cell):
        self._anchor = (x, y)
        self._last_batch = []
        e = _paint(layer, x, y, cell)
        return [e] if e is not None else []

    def drag(self, layer, x, y, cell):
        if self._anchor is None:
            return []
        x0, y0 = self._anchor
        x1, y1 = x, y
        lo_x, hi_x = (x0, x1) if x0 <= x1 else (x1, x0)
        lo_y, hi_y = (y0, y1) if y0 <= y1 else (y1, y0)
        edits: list[Edit] = []
        for py in range(lo_y, hi_y + 1):
            for px in range(lo_x, hi_x + 1):
                on_edge = (
                    px == lo_x or px == hi_x or py == lo_y or py == hi_y
                )
                if not self.filled and not on_edge:
                    continue
                e = _paint(layer, px, py, cell)
                if e is not None:
                    edits.append(e)
        self._last_batch = edits
        return edits

    def commit(self) -> list[Edit]:
        batch = self._last_batch
        self._anchor = None
        self._last_batch = []
        return batch


# ---- Color picker ---------------------------------------------------------

class ColorPickerTool:
    """Read-only: sampling the clicked cell returns (fg, bg, ch). The editor
    sees the empty commit and doesn't push to undo."""
    name = "picker"

    def __init__(self) -> None:
        self.sampled: Cell | None = None

    def begin(self, layer, x, y, cell):
        self.sampled = layer.get(x, y)
        return []

    def drag(self, layer, x, y, cell):
        return []

    def commit(self) -> list[Edit]:
        return []


# ---- Selection (rectangular) ----------------------------------------------

class SelectionTool:
    """Tracks a rectangle; doesn't mutate. Editor uses the region for
    copy/cut operations downstream."""
    name = "selection"

    def __init__(self) -> None:
        self.anchor: tuple[int, int] | None = None
        self.cursor: tuple[int, int] | None = None

    def begin(self, layer, x, y, cell):
        self.anchor = (x, y)
        self.cursor = (x, y)
        return []

    def drag(self, layer, x, y, cell):
        self.cursor = (x, y)
        return []

    def commit(self) -> list[Edit]:
        return []

    def rect(self) -> tuple[int, int, int, int] | None:
        if self.anchor is None or self.cursor is None:
            return None
        x0, y0 = self.anchor
        x1, y1 = self.cursor
        lo_x, hi_x = (x0, x1) if x0 <= x1 else (x1, x0)
        lo_y, hi_y = (y0, y1) if y0 <= y1 else (y1, y0)
        return (lo_x, lo_y, hi_x, hi_y)


# ---- Bresenham line -------------------------------------------------------

def _line(x0: int, y0: int, x1: int, y1: int) -> Iterable[tuple[int, int]]:
    """Bresenham's algorithm over integer grid."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        yield (x, y)
        if x == x1 and y == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


TOOLS_BY_NAME = {
    "pencil":    PencilTool,
    "eraser":    EraserTool,
    "fill":      FillTool,
    "line":      LineTool,
    "rectangle": RectangleTool,
    "picker":    ColorPickerTool,
    "selection": SelectionTool,
}
