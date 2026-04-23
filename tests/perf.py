"""Hot-path benchmarks. Run via `python -m tests.perf`.

Targets:
 - render_line() for a full-row repaint
 - apply_tool_at_cursor() latency
 - composite() across every cell
 - Save/load .dur round-trip
 - Style cache hit vs miss
"""

from __future__ import annotations

import time
import tempfile
from pathlib import Path

from ansi_editor.canvas import Movie
from ansi_editor.editor import Editor
from ansi_editor.fileio import load_dur, save_dur


def bench(label: str, fn, iters: int = 1000) -> None:
    # Warm-up
    for _ in range(3):
        fn()
    start = time.perf_counter()
    for _ in range(iters):
        fn()
    elapsed = time.perf_counter() - start
    per = elapsed / iters * 1000
    print(f"  {label:<45}  {per:>9.4f} ms/iter  ({iters} iters, {elapsed:.3f}s total)")


def main() -> None:
    print("\n=== render_line (80x25 canvas, default blank frame) ===")
    from ansi_editor.app import AnsiEditorApp
    # Textual's Strip + Segment want style_for, we can call render_line
    # directly on an unmounted CanvasView.
    from ansi_editor.app import CanvasView
    editor = Editor()
    view = CanvasView(editor)
    # Pre-fill a few cells so the renderer has varied styles (not all blank).
    editor.brush.ch = "█"
    for (x, y, fg, bg) in [
        (2, 1, 12, 0), (3, 1, 14, 2), (5, 3, 10, 1), (0, 0, 15, 4),
    ]:
        editor.brush.fg, editor.brush.bg = fg, bg
        editor.set_cursor(x, y)
        editor.apply_tool_at_cursor()
    # render_line needs size to be non-zero; override the read-only `size`
    # property by stuffing a fake onto the instance via type-level override.
    class FakeSize:
        width = 80
        height = 25
    CanvasView.size = property(lambda self: FakeSize())  # type: ignore[assignment]

    bench("render_line(y=0) — row with painted cells",
          lambda: view.render_line(0), iters=2000)
    bench("render_line(y=10) — blank row",
          lambda: view.render_line(10), iters=2000)

    print("\n=== apply_tool_at_cursor (pencil) ===")
    e = Editor()
    e.brush.ch = "x"
    i = [0]
    def paint_once():
        e.set_cursor(i[0] % e.movie.cols, (i[0] // e.movie.cols) % e.movie.rows)
        e.apply_tool_at_cursor()
        i[0] += 1
    bench("apply_tool_at_cursor — pencil", paint_once, iters=5000)

    print("\n=== composite() over full canvas ===")
    e = Editor(Movie.blank(80, 25))
    for y in range(e.movie.rows):
        for x in range(e.movie.cols):
            if (x + y) % 3 == 0:
                e.brush.ch = "#"
                e.brush.fg = (x + y) % 16
                e.brush.bg = (x * 2) % 16
                e.set_cursor(x, y)
                e.apply_tool_at_cursor()
    frame = e.current_frame
    def composite_all():
        for y in range(e.movie.rows):
            for x in range(e.movie.cols):
                frame.composite(x, y)
    bench("composite 80x25 grid (2000 cells)", composite_all, iters=200)

    print("\n=== fileio round-trip ===")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "b.dur"
        def save_once():
            save_dur(e.movie, path)
        bench("save_dur 80x25 with 2 layers", save_once, iters=100)
        def load_once():
            load_dur(path)
        bench("load_dur 80x25 with 2 layers", load_once, iters=100)

    print("\n=== style_for cache ===")
    view2 = CanvasView(Editor())
    # Populate cache with a few styles.
    for fg in range(16):
        for bg in range(16):
            view2.style_for(fg, bg, 0)
    def cached():
        view2.style_for(7, 0, 0)  # should be a hit
    bench("style_for (cache hit)", cached, iters=20000)
    def uncached():
        view2._style_cache.clear()
        view2.style_for(7, 0, 0)
    bench("style_for (cache miss + parse)", uncached, iters=2000)


if __name__ == "__main__":
    main()
