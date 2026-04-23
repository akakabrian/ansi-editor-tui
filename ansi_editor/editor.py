"""Editor — the live document state.

Owns the Movie, active frame/layer/tool/brush, and the undo/redo stacks.
The Textual app delegates all mutations to this class so testing is trivial
(construct an Editor directly, no widget mount needed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .canvas import Cell, Frame, Layer, Movie
from .tools import (
    TOOLS_BY_NAME, ColorPickerTool, Edit, EraserTool, FillTool,
    LineTool, PencilTool, RectangleTool, SelectionTool,
)


@dataclass
class Brush:
    """The "pen" — what gets written when a tool fires."""
    ch: str = "█"
    fg: int = 15
    bg: int = 0
    attr: int = 0

    def as_cell(self) -> Cell:
        return Cell(self.ch, self.fg, self.bg, self.attr)


class Editor:
    """Document + cursor + undo stack. Pure logic, no UI."""

    def __init__(self, movie: Movie | None = None) -> None:
        self.movie: Movie = movie or Movie.blank(80, 25)
        self.frame_index: int = 0
        self.layer_index: int = len(self.movie.frames[0].layers) - 1
        self.cursor_x: int = 0
        self.cursor_y: int = 0
        self.brush: Brush = Brush()
        self.tool_name: str = "pencil"
        self._tool_instance = PencilTool()
        # Undo/redo: each entry is (frame_index, layer_index, batch).
        self._undo: list[tuple[int, int, list[Edit]]] = []
        self._redo: list[tuple[int, int, list[Edit]]] = []
        self.selection: SelectionTool | None = None
        self.dirty: bool = False

    # --- current frame / layer accessors --------------------------------

    @property
    def current_frame(self) -> Frame:
        return self.movie.frames[self.frame_index]

    @property
    def current_layer(self) -> Layer:
        layers = self.current_frame.layers
        # Clamp in case layer_index is stale after layer deletion.
        if self.layer_index >= len(layers):
            self.layer_index = len(layers) - 1
        if self.layer_index < 0:
            self.layer_index = 0
        return layers[self.layer_index]

    # --- cursor ---------------------------------------------------------

    def move_cursor(self, dx: int, dy: int) -> None:
        self.cursor_x = max(0, min(self.movie.cols - 1, self.cursor_x + dx))
        self.cursor_y = max(0, min(self.movie.rows - 1, self.cursor_y + dy))

    def set_cursor(self, x: int, y: int) -> None:
        self.cursor_x = max(0, min(self.movie.cols - 1, x))
        self.cursor_y = max(0, min(self.movie.rows - 1, y))

    # --- tool selection -------------------------------------------------

    def select_tool(self, name: str) -> None:
        cls = TOOLS_BY_NAME.get(name)
        if cls is None:
            return
        self.tool_name = name
        self._tool_instance = cls()
        if name == "selection":
            self.selection = self._tool_instance  # keep a handle

    # --- tool application ----------------------------------------------

    def apply_tool_at_cursor(self) -> list[Edit]:
        """Keyboard-driven apply: begin + commit in one shot at the cursor.
        Returns the batch that was committed."""
        tool = self._tool_instance
        layer = self.current_layer
        cell = self.brush.as_cell()
        tool.begin(layer, self.cursor_x, self.cursor_y, cell)
        return self._commit(tool.commit())

    def tool_press(self, x: int, y: int) -> list[Edit]:
        """Mouse press. Starts a stroke (pencil/line/rect) or one-shots (fill)."""
        self.set_cursor(x, y)
        tool = self._tool_instance
        layer = self.current_layer
        cell = self.brush.as_cell()
        tool.begin(layer, x, y, cell)
        # For pencil/eraser the "begin" edit is final — apply it immediately
        # so the user sees it. The commit still runs on release.
        if self.tool_name in ("pencil", "eraser"):
            # pencil.begin returns the one-cell edit already; apply + stash.
            edits = tool._pending[:]  # already produced in begin
            self._apply_batch(edits)
            return edits
        if self.tool_name == "fill":
            # fill is one-shot — commit right away.
            return self._commit(tool.commit())
        # line / rectangle: apply the anchor-only preview (1 cell).
        # We'll revert and re-apply on each drag.
        self._preview_batch = []
        return []

    def tool_drag(self, x: int, y: int) -> list[Edit]:
        """Mouse drag. For pencil/eraser, paint a line from last to (x,y).
        For line/rect, revert the previous preview and paint a new one."""
        self.set_cursor(x, y)
        tool = self._tool_instance
        layer = self.current_layer
        cell = self.brush.as_cell()
        if self.tool_name in ("pencil", "eraser"):
            new = tool.drag(layer, x, y, cell)
            self._apply_batch(new)
            return new
        if self.tool_name in ("line", "rectangle"):
            # Revert last preview, apply new preview.
            prev = getattr(self, "_preview_batch", [])
            self._revert_batch(prev)
            new = tool.drag(layer, x, y, cell)
            self._apply_batch(new)
            self._preview_batch = new
            return new
        if self.tool_name == "selection":
            tool.drag(layer, x, y, cell)
        return []

    def tool_release(self) -> list[Edit]:
        """Mouse release. Finalize the stroke as an undo batch.

        Defensive: a mouse-up that fires without a preceding press (edge case
        when focus changes mid-drag) must not mutate state. We check the
        tool's internal pending list and commit an empty batch in that case."""
        tool = self._tool_instance
        batch = tool.commit()
        if self.tool_name in ("line", "rectangle"):
            # The preview is already applied — we still need to push the batch
            # onto the undo stack without re-applying.
            if batch:
                self._undo.append((self.frame_index, self.layer_index, batch))
                self._redo.clear()
                self.dirty = True
            self._preview_batch = []
            return batch
        # pencil / eraser — batch is already applied; push onto undo stack.
        if batch:
            self._undo.append((self.frame_index, self.layer_index, batch))
            self._redo.clear()
            self.dirty = True
        return batch

    # --- apply / revert helpers ----------------------------------------

    def _apply_batch(self, edits: list[Edit]) -> None:
        layer = self.current_layer
        for e in edits:
            layer.set(e.x, e.y, e.new)

    def _revert_batch(self, edits: list[Edit]) -> None:
        layer = self.current_layer
        for e in edits:
            layer.set(e.x, e.y, e.old)

    def _commit(self, batch: list[Edit]) -> list[Edit]:
        """Apply batch, push on undo stack, clear redo, mark dirty."""
        if not batch:
            return batch
        self._apply_batch(batch)
        self._undo.append((self.frame_index, self.layer_index, batch))
        self._redo.clear()
        self.dirty = True
        return batch

    # --- undo / redo ---------------------------------------------------

    def undo(self) -> bool:
        if not self._undo:
            return False
        frame_idx, layer_idx, batch = self._undo.pop()
        self.frame_index, self.layer_index = frame_idx, layer_idx
        layer = self.current_layer
        for e in batch:
            layer.set(e.x, e.y, e.old)
        self._redo.append((frame_idx, layer_idx, batch))
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        frame_idx, layer_idx, batch = self._redo.pop()
        self.frame_index, self.layer_index = frame_idx, layer_idx
        layer = self.current_layer
        for e in batch:
            layer.set(e.x, e.y, e.new)
        self._undo.append((frame_idx, layer_idx, batch))
        self.dirty = True
        return True

    # --- frame navigation / editing ------------------------------------

    def next_frame(self) -> None:
        self.frame_index = (self.frame_index + 1) % len(self.movie.frames)

    def prev_frame(self) -> None:
        self.frame_index = (self.frame_index - 1) % len(self.movie.frames)

    def add_frame(self, duplicate: bool = True) -> None:
        if duplicate:
            src = self.current_frame
            new_layers: list[Layer] = []
            for layer in src.layers:
                nl = Layer(layer.cols, layer.rows)
                for y in range(layer.rows):
                    for x in range(layer.cols):
                        nl.set(x, y, layer.get(x, y))
                nl.name = layer.name
                nl.visible = layer.visible
                new_layers.append(nl)
            frame = Frame(layers=new_layers, delay=src.delay)
        else:
            frame = self.movie.new_frame()
        self.movie.frames.insert(self.frame_index + 1, frame)
        self.frame_index += 1
        self.dirty = True

    def delete_frame(self) -> None:
        if len(self.movie.frames) <= 1:
            return
        del self.movie.frames[self.frame_index]
        self.frame_index = min(self.frame_index, len(self.movie.frames) - 1)
        self.dirty = True

    # --- layer management ----------------------------------------------

    def next_layer(self) -> None:
        self.layer_index = (self.layer_index + 1) % len(self.current_frame.layers)

    def prev_layer(self) -> None:
        n = len(self.current_frame.layers)
        self.layer_index = (self.layer_index - 1) % n

    def add_layer(self) -> None:
        new = Layer(self.movie.cols, self.movie.rows, transparent=True)
        new.name = f"layer{len(self.current_frame.layers) + 1}"
        self.current_frame.layers.append(new)
        self.layer_index = len(self.current_frame.layers) - 1
        self.dirty = True

    def delete_layer(self) -> None:
        if len(self.current_frame.layers) <= 1:
            return
        del self.current_frame.layers[self.layer_index]
        self.layer_index = max(0, self.layer_index - 1)
        self.dirty = True

    def toggle_layer_visible(self) -> None:
        lyr = self.current_layer
        lyr.visible = not lyr.visible
        self.dirty = True

    # --- picker / brush --------------------------------------------------

    def sample_at(self, x: int, y: int) -> None:
        """Set brush to the cell currently shown at (x,y) in the composited
        view — used by the color-picker tool."""
        c = self.current_frame.composite(x, y)
        if c.ch and c.ch != "\x00":
            self.brush.ch = c.ch
        self.brush.fg = c.fg
        self.brush.bg = c.bg
        self.brush.attr = c.attr

    def set_fg(self, idx: int) -> None:
        self.brush.fg = max(0, min(255, idx))

    def set_bg(self, idx: int) -> None:
        self.brush.bg = max(0, min(255, idx))

    def set_char(self, ch: str) -> None:
        if ch:
            self.brush.ch = ch[0]

    def toggle_attr(self, flag: int) -> None:
        self.brush.attr ^= flag
