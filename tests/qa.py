"""Headless QA driver. Run via `python -m tests.qa [pattern]`.

Each scenario gets a fresh AnsiEditorApp via `App.run_test()`, drives it
with Pilot, and asserts on the live editor state. SVG screenshot per
scenario for visual diffing.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from ansi_editor.app import AnsiEditorApp, TOOL_ORDER
from ansi_editor.canvas import Cell, TRANSPARENT
from ansi_editor.editor import Editor
from ansi_editor.fileio import load_dur, save_ans, save_dur
from ansi_editor.tools import (
    EraserTool, FillTool, LineTool, PencilTool, RectangleTool,
)


OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


@dataclass
class Scenario:
    name: str
    fn: Callable[[AnsiEditorApp, "object"], Awaitable[None]]


# ---- scenarios -----------------------------------------------------------

async def s_mount_clean(app, pilot):
    assert app.canvas_view is not None
    assert app.tools_panel is not None
    assert app.editor is not None
    assert app.editor.movie.frame_count == 1


async def s_cursor_starts_at_origin(app, pilot):
    assert app.editor.cursor_x == 0
    assert app.editor.cursor_y == 0


async def s_cursor_moves(app, pilot):
    await pilot.press("right", "right", "right")
    await pilot.press("down", "down")
    assert app.editor.cursor_x == 3, app.editor.cursor_x
    assert app.editor.cursor_y == 2, app.editor.cursor_y


async def s_cursor_clamps(app, pilot):
    # Clamp top-left
    for _ in range(50):
        await pilot.press("left")
    for _ in range(50):
        await pilot.press("up")
    assert app.editor.cursor_x == 0
    assert app.editor.cursor_y == 0


async def s_pencil_writes_cell(app, pilot):
    await pilot.press("1")  # pencil
    app.editor.brush.ch = "X"
    app.editor.brush.fg = 12
    app.editor.brush.bg = 4
    app.editor.set_cursor(5, 5)
    await pilot.press("enter")
    await pilot.pause()
    cell = app.editor.current_layer.get(5, 5)
    assert cell.ch == "X", cell
    assert cell.fg == 12, cell
    assert cell.bg == 4, cell


async def s_undo_redo_round_trip(app, pilot):
    await pilot.press("1")
    app.editor.brush.ch = "@"
    app.editor.set_cursor(2, 2)
    await pilot.press("enter")
    await pilot.pause()
    assert app.editor.current_layer.get(2, 2).ch == "@"
    # Undo
    await pilot.press("ctrl+z")
    await pilot.pause()
    assert app.editor.current_layer.get(2, 2).ch == TRANSPARENT, (
        app.editor.current_layer.get(2, 2)
    )
    # Redo
    await pilot.press("ctrl+y")
    await pilot.pause()
    assert app.editor.current_layer.get(2, 2).ch == "@"


async def s_fill_tool(app, pilot):
    # On the transparent top layer, fill starting from (0,0) should
    # cover every cell since they're all initially transparent.
    await pilot.press("3")  # fill
    app.editor.brush.ch = "#"
    app.editor.brush.fg = 10
    app.editor.brush.bg = 0
    app.editor.set_cursor(0, 0)
    # Apply via the editor directly — fill is a one-shot.
    batch = app.editor.apply_tool_at_cursor()
    app.canvas_view.refresh_all()
    await pilot.pause()
    assert len(batch) == app.editor.movie.cols * app.editor.movie.rows, (
        f"expected full-canvas fill, got {len(batch)} edits"
    )
    # Spot-check a few cells.
    assert app.editor.current_layer.get(10, 10).ch == "#"


async def s_rectangle_tool(app, pilot):
    """Outline a rectangle from (2,2) to (6,5) via tool_press + drag + release.
    Check corners + edges are set, interior is NOT (filled=False)."""
    await pilot.press("5")  # rectangle
    app.editor.brush.ch = "*"
    app.editor.brush.fg = 14
    app.editor.brush.bg = 0
    app.editor.tool_press(2, 2)
    app.editor.tool_drag(6, 5)
    app.editor.tool_release()
    layer = app.editor.current_layer
    assert layer.get(2, 2).ch == "*"
    assert layer.get(6, 2).ch == "*"
    assert layer.get(2, 5).ch == "*"
    assert layer.get(6, 5).ch == "*"
    # Edge
    assert layer.get(4, 2).ch == "*"
    assert layer.get(2, 3).ch == "*"
    # Interior should still be transparent
    assert layer.get(4, 4).ch == TRANSPARENT, layer.get(4, 4)


async def s_line_tool(app, pilot):
    """Diagonal line from (0,0) to (5,5) — Bresenham ticks every step."""
    await pilot.press("4")
    app.editor.brush.ch = "/"
    app.editor.tool_press(0, 0)
    app.editor.tool_drag(5, 5)
    app.editor.tool_release()
    layer = app.editor.current_layer
    for i in range(6):
        assert layer.get(i, i).ch == "/", (i, layer.get(i, i))


async def s_eraser_tool(app, pilot):
    """Paint a cell with pencil, then erase it."""
    app.editor.brush.ch = "Z"
    app.editor.set_cursor(10, 3)
    app.editor.select_tool("pencil")
    app.editor.apply_tool_at_cursor()
    assert app.editor.current_layer.get(10, 3).ch == "Z"
    await pilot.press("2")  # eraser
    app.editor.apply_tool_at_cursor()
    # Eraser writes a default Cell() — space, fg 7, bg 0.
    c = app.editor.current_layer.get(10, 3)
    assert c.ch == " ", c


async def s_picker_tool(app, pilot):
    """Draw a red-on-black @ at (3,3), then pick it. Brush must become @/red/blk."""
    app.editor.brush.ch = "@"
    app.editor.brush.fg = 12
    app.editor.brush.bg = 0
    app.editor.set_cursor(3, 3)
    app.editor.select_tool("pencil")
    app.editor.apply_tool_at_cursor()
    # Change brush to something different.
    app.editor.brush.ch = "?"
    app.editor.brush.fg = 2
    app.editor.brush.bg = 5
    # Now sample via picker.
    app.editor.sample_at(3, 3)
    assert app.editor.brush.ch == "@", app.editor.brush
    assert app.editor.brush.fg == 12
    assert app.editor.brush.bg == 0


async def s_save_load_dur_round_trip(app, pilot):
    """Paint a few cells, save to .dur, reload, verify cells survive."""
    app.editor.select_tool("pencil")
    app.editor.brush.ch = "P"
    app.editor.brush.fg = 11
    app.editor.brush.bg = 4
    for x, y in [(2, 2), (3, 2), (4, 2)]:
        app.editor.set_cursor(x, y)
        app.editor.apply_tool_at_cursor()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "qa.dur"
        save_dur(app.editor.movie, path)
        assert path.exists()
        assert path.stat().st_size > 100, path.stat().st_size
        m2 = load_dur(path)
        layer = m2.frames[0].layers[-1]
        for x, y in [(2, 2), (3, 2), (4, 2)]:
            c = layer.get(x, y)
            assert c.ch == "P", (x, y, c)
            assert c.fg == 11
            assert c.bg == 4


async def s_save_ans_contains_sgr(app, pilot):
    """Export a frame as .ans; byte output must contain at least one SGR."""
    app.editor.select_tool("pencil")
    app.editor.brush.ch = "Y"
    app.editor.brush.fg = 14
    app.editor.brush.bg = 1
    app.editor.set_cursor(0, 0)
    app.editor.apply_tool_at_cursor()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.ans"
        save_ans(app.editor.movie, path)
        data = path.read_bytes()
        assert b"\x1b[" in data, "missing SGR escape"
        # Our glyph "Y" should appear somewhere in the output.
        assert b"Y" in data


async def s_tool_panel_click(app, pilot):
    """Click on the tools panel to select fill (row 2 — 0-indexed)."""
    await pilot.click("ToolsPanel", offset=(1, 2))
    await pilot.pause()
    assert app.editor.tool_name == "fill", app.editor.tool_name


async def s_color_mode_toggle(app, pilot):
    assert app.editor.movie.color_format == "16"
    await pilot.press("x")
    await pilot.pause()
    assert app.editor.movie.color_format == "256"
    await pilot.press("x")
    await pilot.pause()
    assert app.editor.movie.color_format == "16"


async def s_charset_toggle(app, pilot):
    assert app.editor.movie.encoding == "utf-8"
    await pilot.press("X")
    await pilot.pause()
    assert app.editor.movie.encoding == "cp437"


async def s_layer_add_delete(app, pilot):
    assert len(app.editor.current_frame.layers) == 2
    await pilot.press("n")
    await pilot.pause()
    assert len(app.editor.current_frame.layers) == 3
    await pilot.press("D")
    await pilot.pause()
    assert len(app.editor.current_frame.layers) == 2


async def s_layer_visibility_toggle(app, pilot):
    """Toggling a layer's visibility changes the composite."""
    app.editor.select_tool("pencil")
    app.editor.brush.ch = "V"
    app.editor.set_cursor(1, 1)
    app.editor.apply_tool_at_cursor()
    # Hide the top layer — (1,1) should now be the underlying bg (space).
    app.editor.toggle_layer_visible()
    c = app.editor.current_frame.composite(1, 1)
    assert c.ch != "V", f"layer hidden, but composite still V: {c}"
    # Unhide — V is back.
    app.editor.toggle_layer_visible()
    c = app.editor.current_frame.composite(1, 1)
    assert c.ch == "V", c


async def s_frame_add_delete(app, pilot):
    assert app.editor.movie.frame_count == 1
    await pilot.press("plus")
    await pilot.pause()
    assert app.editor.movie.frame_count == 2
    assert app.editor.frame_index == 1  # we advance to new frame
    await pilot.press("minus")
    await pilot.pause()
    assert app.editor.movie.frame_count == 1


async def s_frame_navigate(app, pilot):
    """Add a frame, navigate back and forward."""
    app.editor.add_frame(duplicate=False)
    assert app.editor.frame_index == 1
    await pilot.press("comma")
    await pilot.pause()
    assert app.editor.frame_index == 0
    await pilot.press("period")
    await pilot.pause()
    assert app.editor.frame_index == 1


async def s_canvas_renders_with_colors(app, pilot):
    """Every painted row must carry fg+bg in the rendered strip."""
    app.editor.select_tool("pencil")
    app.editor.brush.ch = "Q"
    app.editor.brush.fg = 11
    app.editor.brush.bg = 3
    app.editor.set_cursor(0, 0)
    app.editor.apply_tool_at_cursor()
    app.canvas_view.refresh_all()
    await pilot.pause()
    strip = app.canvas_view.render_line(0)
    has_fg = has_bg = False
    for seg in list(strip):
        if seg.style is None:
            continue
        if seg.style.color is not None:
            has_fg = True
        if seg.style.bgcolor is not None:
            has_bg = True
    assert has_fg and has_bg, f"missing fg/bg: fg={has_fg} bg={has_bg}"


async def s_cursor_renders_highlighted(app, pilot):
    """Exactly one cell in the cursor's row should carry the cursor style."""
    from rich.style import Style
    expected = Style.parse("bold black on rgb(255,220,80)")
    cy = app.editor.cursor_y
    strip = app.canvas_view.render_line(cy)
    hl = sum(len(seg.text) for seg in list(strip) if seg.style == expected)
    assert hl == 1, f"expected 1 highlighted cell, got {hl}"


async def s_unknown_cell_does_not_crash(app, pilot):
    """Poison the style cache with an out-of-range index — render must not
    crash. style_for() should fall back via the exception path."""
    # Just call style_for with weird values; must not raise.
    style = app.canvas_view.style_for(999, 999, 99)
    assert style is not None


async def s_mouse_press_applies(app, pilot):
    """Click on the canvas at visible offset (3, 3) with pencil selected —
    cursor moves, and tool_press posts the edit."""
    app.editor.select_tool("pencil")
    app.editor.brush.ch = "M"
    # Make sure the canvas is in view (scroll 0).
    await pilot.pause()
    await pilot.click("CanvasView", offset=(3, 3))
    await pilot.pause()
    # After click, cursor is at (3-border, 3-border) depending on padding.
    # The exact screen offset varies with border/padding; just check a cell
    # near (3,3) got the brush char.
    found = any(
        app.editor.current_layer.get(x, y).ch == "M"
        for x in range(6) for y in range(6)
    )
    assert found, "no 'M' cell found after click"


async def s_selection_tracks_rect(app, pilot):
    """Selection tool press+drag stores a rectangle we can read back."""
    await pilot.press("7")  # selection
    app.editor.tool_press(2, 2)
    app.editor.tool_drag(7, 5)
    sel = app.editor.selection
    assert sel is not None
    rect = sel.rect()
    assert rect == (2, 2, 7, 5), rect


async def s_brush_fg_shift(app, pilot):
    """Pressing F advances fg index; f retreats."""
    app.editor.brush.fg = 5
    await pilot.press("F")
    await pilot.pause()
    assert app.editor.brush.fg == 6, app.editor.brush.fg
    await pilot.press("f")
    await pilot.pause()
    assert app.editor.brush.fg == 5


async def s_save_with_layers_preserves_content(app, pilot):
    """Put a cell on layer 0, a different cell on layer 1, save + load,
    both layers survive exactly."""
    app.editor.layer_index = 0
    app.editor.brush.ch = "B"
    app.editor.brush.fg = 10
    app.editor.set_cursor(3, 3)
    app.editor.select_tool("pencil")
    app.editor.apply_tool_at_cursor()
    app.editor.layer_index = 1
    app.editor.brush.ch = "T"
    app.editor.brush.fg = 14
    app.editor.set_cursor(5, 5)
    app.editor.apply_tool_at_cursor()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "layers.dur"
        save_dur(app.editor.movie, path)
        m2 = load_dur(path)
        l0 = m2.frames[0].layers[0]
        l1 = m2.frames[0].layers[1]
        assert l0.get(3, 3).ch == "B", l0.get(3, 3)
        assert l1.get(5, 5).ch == "T", l1.get(5, 5)
        # Layer 1 cell at (3,3) should be transparent — top layer is sparse.
        assert l1.get(3, 3).ch == TRANSPARENT


async def s_animation_two_frames(app, pilot):
    """Add a second frame, paint a distinct cell, navigate — composite must
    change between frames."""
    app.editor.brush.ch = "1"
    app.editor.set_cursor(1, 1)
    app.editor.select_tool("pencil")
    app.editor.apply_tool_at_cursor()
    app.editor.add_frame(duplicate=False)
    app.editor.brush.ch = "2"
    app.editor.apply_tool_at_cursor()
    # Frame 2 shows "2", frame 1 shows "1".
    assert app.editor.current_frame.composite(1, 1).ch == "2"
    app.editor.prev_frame()
    assert app.editor.current_frame.composite(1, 1).ch == "1"


async def s_tool_press_drag_line_preview_replaces(app, pilot):
    """Line tool press + drag1 + drag2 — only the final-drag line should
    remain on the layer, not the union of all previews."""
    await pilot.press("4")  # line
    app.editor.brush.ch = "L"
    app.editor.tool_press(0, 0)
    # First drag preview: line to (2,0) — 3 cells horizontal.
    app.editor.tool_drag(2, 0)
    # Second drag preview: line to (0,4) — 5 cells vertical.
    app.editor.tool_drag(0, 4)
    app.editor.tool_release()
    layer = app.editor.current_layer
    # Cells (1,0) and (2,0) should be TRANSPARENT — preview was reverted.
    assert layer.get(2, 0).ch == TRANSPARENT, layer.get(2, 0)
    # Cells (0,0)..(0,4) should be "L".
    for y in range(5):
        assert layer.get(0, y).ch == "L", (y, layer.get(0, y))


async def s_mouse_release_without_press_is_safe(app, pilot):
    """Dropping a mouse-up on an editor that wasn't dragging must be a no-op."""
    before_undo = len(app.editor._undo)
    app.editor.tool_release()  # no press/drag preceded
    assert len(app.editor._undo) == before_undo


async def s_undo_past_empty_stack_is_safe(app, pilot):
    """Spamming undo with nothing to undo must not raise."""
    for _ in range(5):
        assert app.editor.undo() is False


async def s_delete_last_layer_is_clamped(app, pilot):
    """A frame must always keep at least one layer — delete_layer on a
    single-layer frame is a no-op."""
    # Reduce to one layer, then try to delete again.
    app.editor.delete_layer()
    assert len(app.editor.current_frame.layers) == 1
    app.editor.delete_layer()
    assert len(app.editor.current_frame.layers) == 1


async def s_delete_last_frame_is_clamped(app, pilot):
    """Must always have at least one frame."""
    assert app.editor.movie.frame_count == 1
    app.editor.delete_frame()
    assert app.editor.movie.frame_count == 1


async def s_layer_index_clamps_after_delete(app, pilot):
    """If we delete a layer while on the top index, current_layer must still
    resolve (no IndexError)."""
    app.editor.add_layer()
    app.editor.layer_index = len(app.editor.current_frame.layers) - 1
    app.editor.delete_layer()
    # current_layer must still return a valid Layer.
    _ = app.editor.current_layer


async def s_resize_preserves_old_cells(app, pilot):
    """Growing a layer keeps old cells intact; shrinking drops them."""
    app.editor.brush.ch = "K"
    app.editor.set_cursor(5, 5)
    app.editor.select_tool("pencil")
    app.editor.apply_tool_at_cursor()
    layer = app.editor.current_layer
    layer.resize(120, 40)
    assert layer.get(5, 5).ch == "K"
    layer.resize(4, 4)
    # (5,5) is now out of bounds — get() returns a default.
    assert layer.get(5, 5).ch == " "


async def s_save_dur_is_gzip(app, pilot):
    """The .dur file must be gzipped (magic bytes 1f 8b) so it opens in
    real Durdraw."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.dur"
        save_dur(app.editor.movie, path)
        head = path.read_bytes()[:2]
        assert head == b"\x1f\x8b", f"not gzipped: {head!r}"


SCENARIOS: list[Scenario] = [
    Scenario("mount_clean", s_mount_clean),
    Scenario("cursor_starts_at_origin", s_cursor_starts_at_origin),
    Scenario("cursor_moves", s_cursor_moves),
    Scenario("cursor_clamps", s_cursor_clamps),
    Scenario("pencil_writes_cell", s_pencil_writes_cell),
    Scenario("undo_redo_round_trip", s_undo_redo_round_trip),
    Scenario("fill_tool_covers_transparent_canvas", s_fill_tool),
    Scenario("rectangle_tool_outline_only", s_rectangle_tool),
    Scenario("line_tool_bresenham", s_line_tool),
    Scenario("eraser_tool_clears", s_eraser_tool),
    Scenario("picker_tool_samples_cell", s_picker_tool),
    Scenario("save_load_dur_round_trip", s_save_load_dur_round_trip),
    Scenario("save_ans_contains_sgr_escapes", s_save_ans_contains_sgr),
    Scenario("tool_panel_click_selects", s_tool_panel_click),
    Scenario("color_mode_toggle", s_color_mode_toggle),
    Scenario("charset_toggle", s_charset_toggle),
    Scenario("layer_add_delete", s_layer_add_delete),
    Scenario("layer_visibility_toggle", s_layer_visibility_toggle),
    Scenario("frame_add_delete", s_frame_add_delete),
    Scenario("frame_navigate_prev_next", s_frame_navigate),
    Scenario("canvas_renders_with_colors", s_canvas_renders_with_colors),
    Scenario("cursor_renders_highlighted", s_cursor_renders_highlighted),
    Scenario("unknown_color_does_not_crash", s_unknown_cell_does_not_crash),
    Scenario("mouse_press_applies_tool", s_mouse_press_applies),
    Scenario("selection_tracks_rectangle", s_selection_tracks_rect),
    Scenario("brush_fg_shift_cycles", s_brush_fg_shift),
    Scenario("save_preserves_layers", s_save_with_layers_preserves_content),
    Scenario("animation_two_frames", s_animation_two_frames),
    Scenario("line_preview_revert_on_drag", s_tool_press_drag_line_preview_replaces),
    Scenario("dur_file_is_gzip", s_save_dur_is_gzip),
    Scenario("mouse_release_without_press_is_safe", s_mouse_release_without_press_is_safe),
    Scenario("undo_empty_stack_is_safe", s_undo_past_empty_stack_is_safe),
    Scenario("delete_last_layer_is_clamped", s_delete_last_layer_is_clamped),
    Scenario("delete_last_frame_is_clamped", s_delete_last_frame_is_clamped),
    Scenario("layer_index_clamps_after_delete", s_layer_index_clamps_after_delete),
    Scenario("resize_preserves_old_cells", s_resize_preserves_old_cells),
]


# ---- driver -------------------------------------------------------------

async def run_one(scn: Scenario) -> tuple[str, bool, str]:
    app = AnsiEditorApp()
    try:
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            try:
                await scn.fn(app, pilot)
            except AssertionError as e:
                app.save_screenshot(str(OUT / f"{scn.name}.FAIL.svg"))
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                app.save_screenshot(str(OUT / f"{scn.name}.ERROR.svg"))
                return (scn.name, False,
                        f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            app.save_screenshot(str(OUT / f"{scn.name}.PASS.svg"))
            return (scn.name, True, "")
    except Exception as e:
        return (scn.name, False,
                f"harness: {type(e).__name__}: {e}\n{traceback.format_exc()}")


async def main(pattern: str | None = None) -> int:
    scenarios = [s for s in SCENARIOS if not pattern or pattern in s.name]
    if not scenarios:
        print(f"no scenarios match {pattern!r}")
        return 2
    results = []
    for scn in scenarios:
        name, ok, msg = await run_one(scn)
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        print(f"  {mark} {name}")
        if not ok:
            for line in msg.splitlines():
                print(f"      {line}")
        results.append((name, ok, msg))
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{passed}/{len(results)} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(main(pattern)))
