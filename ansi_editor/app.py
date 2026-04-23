"""Textual app for the ANSI/ASCII art editor.

Layout:
 - CanvasView (ScrollView) on the left, renders composited frame via render_line
 - Side column (Tools / Brush / Layers / Frames)
 - Flash bar below the canvas

Bindings: priority arrow keys for cursor move, pencil/fill/line/rect/eraser/
picker/select on letter keys, undo/redo on ctrl+z/ctrl+y, save/load on s/L.
"""

from __future__ import annotations

from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, Static

from . import charset, palette
from .canvas import ATTR_BLINK, ATTR_BOLD, ATTR_REVERSE, Cell
from .editor import Editor
from .fileio import load_dur, save_ans, save_dur
from .tools import TOOLS_BY_NAME


# Tool list — order matters, it drives both the panel and the 1–7 hotkeys.
TOOL_ORDER = [
    ("1", "pencil",    "✎ Pencil"),
    ("2", "eraser",    "⌫ Eraser"),
    ("3", "fill",      "▣ Fill"),
    ("4", "line",      "╱ Line"),
    ("5", "rectangle", "▭ Rectangle"),
    ("6", "picker",    "◉ Picker"),
    ("7", "selection", "⎚ Select"),
]


class CanvasView(ScrollView):
    """Renders the current frame's composited cells, with a cursor highlight.

    Uses ScrollView's `render_line(y)` so Textual only calls back for visible
    rows. The cell-to-Style cache + per-run segment accumulation keeps paints
    fast even for larger canvases (>200×100)."""

    class ToolPress(Message):
        def __init__(self, x: int, y: int, button: int) -> None:
            self.x, self.y, self.button = x, y, button
            super().__init__()

    class ToolDrag(Message):
        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y
            super().__init__()

    class ToolRelease(Message):
        pass

    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)

    def __init__(self, editor: Editor) -> None:
        super().__init__()
        self.editor = editor
        self.virtual_size = Size(editor.movie.cols, editor.movie.rows)
        # Style cache keyed by (fg, bg, attr, mode). Parsing rich.Style per
        # cell dominates TUI perf; cache aggressively.
        self._style_cache: dict[tuple[int, int, int, str], Style] = {}
        self._cursor_style = Style.parse(
            "bold black on rgb(255,220,80)"
        )
        self._unknown_style = Style.parse("bold rgb(255,0,255) on black")
        self._dragging: bool = False

    # --- style resolution -----------------------------------------------

    def style_for(self, fg: int, bg: int, attr: int) -> Style:
        mode = self.editor.movie.color_format
        key = (fg, bg, attr, mode)
        cached = self._style_cache.get(key)
        if cached is not None:
            return cached
        fg_rgb = palette.rgb(fg, mode)
        bg_rgb = palette.rgb(bg, mode)
        parts = [f"rgb({fg_rgb[0]},{fg_rgb[1]},{fg_rgb[2]})",
                 "on", f"rgb({bg_rgb[0]},{bg_rgb[1]},{bg_rgb[2]})"]
        if attr & 1:  # bold
            parts.insert(0, "bold")
        if attr & 2:  # blink
            parts.insert(0, "blink")
        if attr & 4:  # reverse
            parts.insert(0, "reverse")
        if attr & 8:  # underline
            parts.insert(0, "underline")
        try:
            style = Style.parse(" ".join(parts))
        except Exception:
            style = self._unknown_style
        self._style_cache[key] = style
        return style

    # --- rendering -------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        row_y = y + int(scroll_y)
        width = self.size.width
        movie = self.editor.movie
        if row_y < 0 or row_y >= movie.rows:
            return Strip.blank(width)
        start_x = max(0, int(scroll_x))
        end_x = min(movie.cols, start_x + width)
        frame = self.editor.current_frame
        # Overlay markers for selection rectangle.
        sel_rect: tuple[int, int, int, int] | None = None
        sel_tool = self.editor.selection
        if sel_tool is not None and self.editor.tool_name == "selection":
            sel_rect = sel_tool.rect()

        cursor_x, cursor_y = self.cursor_x, self.cursor_y
        cursor_style = self._cursor_style
        selection_style = Style.parse("on rgb(80,80,0)")

        segments: list[Segment] = []
        run_chars: list[str] = []
        run_style: Style | None = None

        for x in range(start_x, end_x):
            c = frame.composite(x, row_y)
            glyph = c.ch if c.ch and c.ch != "\x00" else " "
            if x == cursor_x and row_y == cursor_y:
                style = cursor_style
            else:
                style = self.style_for(c.fg, c.bg, c.attr)
                if sel_rect is not None:
                    lx, ly, hx, hy = sel_rect
                    if lx <= x <= hx and ly <= row_y <= hy:
                        style = style + selection_style
            if style is run_style:
                run_chars.append(glyph)
            else:
                if run_chars:
                    segments.append(Segment("".join(run_chars), run_style))
                run_chars = [glyph]
                run_style = style

        if run_chars:
            segments.append(Segment("".join(run_chars), run_style))

        visible = end_x - start_x
        if visible < width:
            segments.append(Segment(" " * (width - visible)))
        return Strip(segments, width)

    # --- invalidation helpers -------------------------------------------

    def refresh_all(self) -> None:
        self.refresh()

    def refresh_row(self, row_y: int) -> None:
        self.refresh(Region(0, row_y, self.editor.movie.cols, 1))

    def watch_cursor_x(self, old: int, new: int) -> None:
        if not self.is_mounted:
            return
        self.refresh_row(self.cursor_y)
        self._scroll_to_cursor()

    def watch_cursor_y(self, old: int, new: int) -> None:
        if not self.is_mounted:
            return
        self.refresh_row(old)
        self.refresh_row(new)
        self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        self.scroll_to_region(
            Region(self.cursor_x - 2, self.cursor_y - 2, 5, 5),
            animate=False, force=True,
        )

    # --- mouse ----------------------------------------------------------

    def _event_to_cell(self, event: events.MouseEvent) -> tuple[int, int] | None:
        cx = event.x + int(self.scroll_offset.x)
        cy = event.y + int(self.scroll_offset.y)
        if 0 <= cx < self.editor.movie.cols and 0 <= cy < self.editor.movie.rows:
            return (cx, cy)
        return None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        spot = self._event_to_cell(event)
        if spot is None:
            return
        self._dragging = True
        self.capture_mouse()
        self.cursor_x, self.cursor_y = spot
        self.post_message(self.ToolPress(spot[0], spot[1], event.button))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        spot = self._event_to_cell(event)
        if spot is None:
            return
        if (self.cursor_x, self.cursor_y) == spot:
            return
        self.cursor_x, self.cursor_y = spot
        self.post_message(self.ToolDrag(spot[0], spot[1]))

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.release_mouse()
            self.post_message(self.ToolRelease())


# --- side panels -----------------------------------------------------------

class ToolsPanel(Static):
    class Selected(Message):
        def __init__(self, name: str) -> None:
            self.name = name
            super().__init__()

    def __init__(self) -> None:
        super().__init__("")
        self.border_title = "TOOLS"
        self.selected: str = "pencil"

    def refresh_panel(self) -> None:
        t = Text()
        for key, name, label in TOOL_ORDER:
            prefix = "▶ " if name == self.selected else "  "
            style = "bold reverse" if name == self.selected else ""
            t.append(f"{prefix}{key} {label}\n", style=style)
        self.update(t)

    def on_click(self, event: events.Click) -> None:
        idx = event.y
        if 0 <= idx < len(TOOL_ORDER):
            self.post_message(self.Selected(TOOL_ORDER[idx][1]))


class BrushPanel(Static):
    def __init__(self, editor: Editor) -> None:
        super().__init__("")
        self.editor = editor
        self.border_title = "BRUSH"

    def refresh_panel(self) -> None:
        b = self.editor.brush
        fg_name = palette.color_name(b.fg)
        bg_name = palette.color_name(b.bg)
        # Color swatches rendered as solid blocks in the palette RGB.
        mode = self.editor.movie.color_format
        fg_rgb = palette.rgb(b.fg, mode)
        bg_rgb = palette.rgb(b.bg, mode)
        t = Text()
        t.append("Char   ", style="dim")
        t.append(f" {b.ch} ", style=f"bold white on rgb({bg_rgb[0]},{bg_rgb[1]},{bg_rgb[2]})")
        t.append("\n")
        t.append("Fg     ", style="dim")
        t.append("   ", style=f"on rgb({fg_rgb[0]},{fg_rgb[1]},{fg_rgb[2]})")
        t.append(f"  {b.fg:>3d} {fg_name}\n")
        t.append("Bg     ", style="dim")
        t.append("   ", style=f"on rgb({bg_rgb[0]},{bg_rgb[1]},{bg_rgb[2]})")
        t.append(f"  {b.bg:>3d} {bg_name}\n")
        attrs = []
        if b.attr & ATTR_BOLD:    attrs.append("bold")
        if b.attr & ATTR_BLINK:   attrs.append("blink")
        if b.attr & ATTR_REVERSE: attrs.append("reverse")
        t.append(f"Attr    {','.join(attrs) or '-'}\n", style="dim")
        t.append(f"Mode    {self.editor.movie.color_format}\n", style="dim")
        t.append(f"Charset {self.editor.movie.encoding}\n", style="dim")
        t.append("\n[dim]f/F fg-/+  b/B bg-/+  c chars  x mode[/]", style="dim")
        self.update(t)


class LayersPanel(Static):
    def __init__(self, editor: Editor) -> None:
        super().__init__("")
        self.editor = editor
        self.border_title = "LAYERS"

    def refresh_panel(self) -> None:
        t = Text()
        frame = self.editor.current_frame
        for i, layer in enumerate(reversed(frame.layers)):
            true_idx = len(frame.layers) - 1 - i
            prefix = "▶ " if true_idx == self.editor.layer_index else "  "
            vis = "●" if layer.visible else "○"
            style = "bold reverse" if true_idx == self.editor.layer_index else ""
            t.append(f"{prefix}{vis} {layer.name}\n", style=style)
        t.append("\n[dim][ ] prev/next  n new  D del  V visible[/]", style="dim")
        self.update(t)


class FramesPanel(Static):
    def __init__(self, editor: Editor) -> None:
        super().__init__("")
        self.editor = editor
        self.border_title = "FRAMES"

    def refresh_panel(self) -> None:
        t = Text()
        total = self.editor.movie.frame_count
        cur = self.editor.frame_index + 1
        t.append(f"Frame {cur} / {total}\n")
        t.append(f"Delay {self.editor.current_frame.delay:.2f}s\n", style="dim")
        t.append(f"Rate  {self.editor.movie.framerate:.1f} fps\n", style="dim")
        t.append("\n[dim], / . prev/next  + insert  - del  P play[/]", style="dim")
        self.update(t)


# --- app ------------------------------------------------------------------

class AnsiEditorApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "ansi-editor-tui"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        # Tools
        *[Binding(k, f"select_tool('{n}')", show=False) for k, n, _ in TOOL_ORDER],
        # Cursor — priority so ScrollView doesn't eat them.
        Binding("up",    "move_cursor(0,-1)", "↑", show=False, priority=True),
        Binding("down",  "move_cursor(0,1)",  "↓", show=False, priority=True),
        Binding("left",  "move_cursor(-1,0)", "←", show=False, priority=True),
        Binding("right", "move_cursor(1,0)",  "→", show=False, priority=True),
        Binding("enter", "apply_tool",        "Apply", priority=True),
        Binding("space", "apply_tool",        show=False, priority=True),
        # Brush controls
        Binding("f", "shift_fg(-1)", show=False),
        Binding("F", "shift_fg(1)",  show=False),
        Binding("b", "shift_bg(-1)", show=False),
        Binding("B", "shift_bg(1)",  show=False),
        Binding("x", "toggle_color_mode", "Mode"),
        Binding("X", "toggle_charset",    "Charset"),
        # Undo / redo
        Binding("ctrl+z", "undo", "Undo"),
        Binding("ctrl+y", "redo", "Redo"),
        Binding("u",      "undo", show=False),
        Binding("r",      "redo", show=False),
        # Layers
        Binding("[", "prev_layer",   show=False),
        Binding("]", "next_layer",   show=False),
        Binding("n", "add_layer",    "Add layer"),
        Binding("D", "delete_layer", "Del layer"),
        Binding("V", "toggle_layer_visible", "Toggle vis"),
        # Frames
        Binding("comma",  "prev_frame", show=False),
        Binding("period", "next_frame", show=False),
        Binding("plus",   "add_frame",  "+Frame"),
        Binding("minus",  "delete_frame", "-Frame"),
        Binding("P",      "play_pause", "Play"),
        # File
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+o", "load", "Load"),
        # Char cycle
        Binding("c", "cycle_char(1)",  show=False),
        Binding("C", "cycle_char(-1)", show=False),
    ]

    playing: reactive[bool] = reactive(False)

    def __init__(self, movie_path: str | None = None) -> None:
        super().__init__()
        if movie_path and Path(movie_path).exists():
            from .fileio import load_dur
            self.editor = Editor(load_dur(movie_path))
            self._path = Path(movie_path)
        else:
            self.editor = Editor()
            self._path = Path(movie_path) if movie_path else Path("untitled.dur")
        self.canvas_view = CanvasView(self.editor)
        self.tools_panel = ToolsPanel()
        self.brush_panel = BrushPanel(self.editor)
        self.layers_panel = LayersPanel(self.editor)
        self.frames_panel = FramesPanel(self.editor)
        self.flash_bar = Static(" ", id="flash-bar")
        self._flash_timer = None
        self._play_timer = None
        # Cycling through the brush charset by pressing 'c' uses this index.
        self._char_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="canvas-col"):
                yield self.canvas_view
                yield self.flash_bar
            with Vertical(id="side"):
                yield self.tools_panel
                yield self.brush_panel
                yield self.layers_panel
                yield self.frames_panel
        yield Footer()

    async def on_mount(self) -> None:
        self.canvas_view.border_title = (
            f"{self._path.name}  ·  {self.editor.movie.cols}×{self.editor.movie.rows}"
        )
        self._refresh_side_panels()
        self.flash("Welcome. Press 1-7 to pick a tool, enter/space to draw.")
        self._update_char_idx_from_brush()

    def _refresh_side_panels(self) -> None:
        self.tools_panel.selected = self.editor.tool_name
        self.tools_panel.refresh_panel()
        self.brush_panel.refresh_panel()
        self.layers_panel.refresh_panel()
        self.frames_panel.refresh_panel()

    # --- flash bar ------------------------------------------------------

    def flash(self, msg: str, seconds: float = 2.0) -> None:
        self.flash_bar.update(Text.from_markup(msg))
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(seconds, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash_timer = None
        e = self.editor
        cell = e.current_frame.composite(e.cursor_x, e.cursor_y)
        ch = cell.ch if cell.ch and cell.ch != "\x00" else " "
        msg = (
            f"[dim]({e.cursor_x},{e.cursor_y})[/] "
            f"[bold]{e.tool_name}[/]  "
            f"fg {e.brush.fg} / bg {e.brush.bg}  "
            f"char '[yellow]{ch}[/]'  "
            f"frame {e.frame_index + 1}/{e.movie.frame_count}  "
            f"layer {e.layer_index + 1}/{len(e.current_frame.layers)}"
        )
        self.flash_bar.update(Text.from_markup(msg))

    # --- tool actions ---------------------------------------------------

    def action_select_tool(self, name: str) -> None:
        self.editor.select_tool(name)
        self._refresh_side_panels()
        self.flash(f"Tool: [bold]{name}[/]")

    def action_move_cursor(self, dx: str, dy: str) -> None:
        self.editor.move_cursor(int(dx), int(dy))
        self.canvas_view.cursor_x = self.editor.cursor_x
        self.canvas_view.cursor_y = self.editor.cursor_y
        self._clear_flash()  # refresh the hover info immediately

    def action_apply_tool(self) -> None:
        before = self.editor.cursor_x, self.editor.cursor_y
        batch = self.editor.apply_tool_at_cursor()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()
        if self.editor.tool_name == "picker":
            # Picker samples the cell where the cursor is.
            self.editor.sample_at(*before)
            self._update_char_idx_from_brush()
            self._refresh_side_panels()
            self.flash("[cyan]◉ sampled[/]")
            return
        if batch:
            self.flash(f"[green]✓ {self.editor.tool_name}[/] ×{len(batch)}")
        else:
            self.flash(f"[dim]{self.editor.tool_name}: no-op[/]")

    # --- mouse routing --------------------------------------------------

    def on_canvas_view_tool_press(self, msg: CanvasView.ToolPress) -> None:
        if msg.button == 3:
            # Right-click = sample at that cell (convenience).
            self.editor.sample_at(msg.x, msg.y)
            self._update_char_idx_from_brush()
            self._refresh_side_panels()
            self.flash("[cyan]◉ sampled[/]")
            return
        if self.editor.tool_name == "picker":
            self.editor.sample_at(msg.x, msg.y)
            self._update_char_idx_from_brush()
            self._refresh_side_panels()
            self.flash("[cyan]◉ sampled[/]")
            return
        self.editor.tool_press(msg.x, msg.y)
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    def on_canvas_view_tool_drag(self, msg: CanvasView.ToolDrag) -> None:
        self.editor.tool_drag(msg.x, msg.y)
        self.canvas_view.refresh_all()

    def on_canvas_view_tool_release(self, msg: CanvasView.ToolRelease) -> None:
        batch = self.editor.tool_release()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()
        if batch:
            self.flash(f"[green]✓ {self.editor.tool_name}[/] {len(batch)} cell(s)")

    def on_tools_panel_selected(self, msg: ToolsPanel.Selected) -> None:
        self.action_select_tool(msg.name)

    # --- brush actions --------------------------------------------------

    def action_shift_fg(self, delta: str) -> None:
        lim = 16 if self.editor.movie.color_format == "16" else 256
        self.editor.brush.fg = (self.editor.brush.fg + int(delta)) % lim
        self._refresh_side_panels()
        self.flash(f"fg = [bold]{self.editor.brush.fg}[/] ({palette.color_name(self.editor.brush.fg)})")

    def action_shift_bg(self, delta: str) -> None:
        lim = 16 if self.editor.movie.color_format == "16" else 256
        self.editor.brush.bg = (self.editor.brush.bg + int(delta)) % lim
        self._refresh_side_panels()
        self.flash(f"bg = [bold]{self.editor.brush.bg}[/]")

    def action_toggle_color_mode(self) -> None:
        cur = self.editor.movie.color_format
        self.editor.movie.color_format = "256" if cur == "16" else "16"
        # Invalidate style cache — mode change means different RGB resolution.
        self.canvas_view._style_cache.clear()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()
        self.flash(f"Color mode: [bold]{self.editor.movie.color_format}[/]")

    def action_toggle_charset(self) -> None:
        cur = self.editor.movie.encoding
        self.editor.movie.encoding = "cp437" if cur == "utf-8" else "utf-8"
        self._char_idx = 0
        self._refresh_side_panels()
        self.flash(f"Charset: [bold]{self.editor.movie.encoding}[/]")

    def action_cycle_char(self, delta: str) -> None:
        glyphs = charset.glyphs_for(
            "cp437" if self.editor.movie.encoding == "cp437" else "unicode"
        )
        if not glyphs:
            return
        self._char_idx = (self._char_idx + int(delta)) % len(glyphs)
        self.editor.brush.ch = glyphs[self._char_idx]
        self._refresh_side_panels()
        self.flash(f"Char: [yellow]{self.editor.brush.ch}[/]")

    def _update_char_idx_from_brush(self) -> None:
        glyphs = charset.glyphs_for(
            "cp437" if self.editor.movie.encoding == "cp437" else "unicode"
        )
        try:
            self._char_idx = glyphs.index(self.editor.brush.ch)
        except ValueError:
            self._char_idx = 0

    # --- undo / redo ----------------------------------------------------

    def action_undo(self) -> None:
        if self.editor.undo():
            self.canvas_view.refresh_all()
            self._refresh_side_panels()
            self.flash("[green]↶ undo[/]")
        else:
            self.flash("[dim]nothing to undo[/]")

    def action_redo(self) -> None:
        if self.editor.redo():
            self.canvas_view.refresh_all()
            self._refresh_side_panels()
            self.flash("[green]↷ redo[/]")
        else:
            self.flash("[dim]nothing to redo[/]")

    # --- layers ---------------------------------------------------------

    def action_prev_layer(self) -> None:
        self.editor.prev_layer()
        self._refresh_side_panels()

    def action_next_layer(self) -> None:
        self.editor.next_layer()
        self._refresh_side_panels()

    def action_add_layer(self) -> None:
        self.editor.add_layer()
        self._refresh_side_panels()
        self.flash("[green]+ layer[/]")

    def action_delete_layer(self) -> None:
        self.editor.delete_layer()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    def action_toggle_layer_visible(self) -> None:
        self.editor.toggle_layer_visible()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    # --- frames ---------------------------------------------------------

    def action_prev_frame(self) -> None:
        self.editor.prev_frame()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    def action_next_frame(self) -> None:
        self.editor.next_frame()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    def action_add_frame(self) -> None:
        self.editor.add_frame(duplicate=True)
        self.canvas_view.refresh_all()
        self._refresh_side_panels()
        self.flash("[green]+ frame[/]")

    def action_delete_frame(self) -> None:
        self.editor.delete_frame()
        self.canvas_view.refresh_all()
        self._refresh_side_panels()

    def action_play_pause(self) -> None:
        self.playing = not self.playing
        if self.playing:
            self._play_timer = self.set_interval(
                1.0 / max(self.editor.movie.framerate, 1.0),
                self._play_tick,
            )
            self.flash("[yellow]▶ play[/]")
        else:
            if self._play_timer is not None:
                self._play_timer.stop()
                self._play_timer = None
            self.flash("[dim]⏸ pause[/]")

    def _play_tick(self) -> None:
        self.editor.next_frame()
        self.canvas_view.refresh_all()
        self.frames_panel.refresh_panel()

    # --- file actions ---------------------------------------------------

    def action_save(self) -> None:
        path = self._path
        try:
            if path.suffix == ".ans":
                save_ans(self.editor.movie, path, frame_index=self.editor.frame_index)
            else:
                if path.suffix != ".dur":
                    path = path.with_suffix(".dur")
                save_dur(self.editor.movie, path)
            self.editor.dirty = False
            self.flash(f"[green]✓ saved[/] {path.name}")
        except Exception as e:
            self.flash(f"[red]✗ save failed: {e}[/]")

    def action_load(self) -> None:
        # No modal yet; load the path we were launched with (if it exists).
        path = self._path
        if not path.exists():
            self.flash(f"[red]✗ not found: {path.name}[/]")
            return
        try:
            movie = load_dur(path)
            self.editor = Editor(movie)
            self.canvas_view.editor = self.editor
            self.canvas_view.virtual_size = Size(movie.cols, movie.rows)
            self.canvas_view._style_cache.clear()
            self.canvas_view.refresh_all()
            self._refresh_side_panels()
            self.flash(f"[green]✓ loaded[/] {path.name}")
        except Exception as e:
            self.flash(f"[red]✗ load failed: {e}[/]")


def run(path: str | None = None) -> None:
    app = AnsiEditorApp(path)
    try:
        app.run()
    finally:
        import sys
        # Always reset mouse tracking on exit to avoid leaked escape sequences.
        sys.stdout.write(
            "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l\033[?25h"
        )
        sys.stdout.flush()
