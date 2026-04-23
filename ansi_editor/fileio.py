"""File I/O — Durdraw .dur (gzipped JSON) + classic .ans (SGR escapes).

Round-trip guarantee: a movie saved to .dur and loaded back must equal the
original (byte-for-byte on the canvas grids). Tested in qa.s_save_load_round_trip.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from .canvas import Cell, Frame, Layer, Movie
from .palette import sgr_fg, sgr_bg

DUR_FORMAT_VERSION = 7


# ---- .dur -----------------------------------------------------------------

def save_dur(movie: Movie, path: str | Path) -> Path:
    """Write `movie` to `path` as a gzipped Durdraw v7 JSON file."""
    path = Path(path)
    frames_json: list[dict] = []
    for i, frame in enumerate(movie.frames, start=1):
        composited = _composite_frame(frame, movie.cols, movie.rows)
        contents: list[str] = []
        # colorMap in real Durdraw is [col][row] (column-major).
        # Build columns first.
        color_map: list[list[list[int]]] = [
            [[7, 0] for _ in range(movie.rows)] for _ in range(movie.cols)
        ]
        for y in range(movie.rows):
            row_chars: list[str] = []
            for x in range(movie.cols):
                c = composited[y][x]
                row_chars.append(c.ch if c.ch else " ")
                color_map[x][y] = [c.fg, c.bg]
            contents.append("".join(row_chars))
        frame_dict = {
            "frameNumber": i,
            "delay": frame.delay,
            "contents": contents,
            "colorMap": color_map,
        }
        # Persist layers under "extra" so Durdraw ignores it but we round-trip.
        extra_layers = []
        for layer in frame.layers:
            extra_layers.append({
                "name": layer.name,
                "visible": layer.visible,
                # Serialize as a flat string per row — char + (fg, bg) zipped.
                "rows": [
                    [[cell.ch, cell.fg, cell.bg, cell.attr]
                     for cell in layer._grid[y]]
                    for y in range(layer.rows)
                ],
            })
        frame_dict["extra"] = {"layers": extra_layers}
        frames_json.append(frame_dict)

    movie_json = {
        "DurMovie": {
            "formatVersion": DUR_FORMAT_VERSION,
            "colorFormat": movie.color_format,
            "preferredFont": "fixed",
            "encoding": movie.encoding,
            "name": movie.name,
            "artist": movie.artist,
            "framerate": movie.framerate,
            "columns": movie.cols,
            "lines": movie.rows,
            "sizeX": movie.cols,  # legacy key Durdraw also reads
            "sizeY": movie.rows,
            "extra": None,
            "frames": frames_json,
        }
    }

    payload = json.dumps(movie_json, ensure_ascii=False).encode("utf-8")
    # Gzip-compress so real Durdraw can open the file.
    with gzip.open(path, "wb") as f:
        f.write(payload)
    return path


def load_dur(path: str | Path) -> Movie:
    """Read a .dur file (gzipped JSON) into a Movie."""
    path = Path(path)
    raw = path.read_bytes()
    # Durdraw files are gzipped. But the doc example shows a plain-JSON
    # option too, so we try both.
    try:
        data = gzip.decompress(raw)
    except (OSError, gzip.BadGzipFile):
        data = raw
    obj = json.loads(data.decode("utf-8"))
    dm = obj["DurMovie"]
    cols = dm.get("columns", dm.get("sizeX", 80))
    rows = dm.get("lines", dm.get("sizeY", 25))
    movie = Movie(
        cols=cols, rows=rows,
        framerate=dm.get("framerate", 6.0),
        color_format=str(dm.get("colorFormat", "16")),
        encoding=dm.get("encoding", "utf-8"),
        name=dm.get("name", ""),
        artist=dm.get("artist", ""),
    )
    for fj in dm.get("frames", []):
        # Prefer our layered `extra.layers` data when present — full fidelity.
        extra = fj.get("extra") or {}
        layers_json = extra.get("layers") if isinstance(extra, dict) else None
        if layers_json:
            frame = Frame(layers=[], delay=fj.get("delay", 0.1))
            for lj in layers_json:
                layer = Layer(cols, rows, transparent=False)
                layer.name = lj.get("name", "layer")
                layer.visible = lj.get("visible", True)
                for y, row in enumerate(lj.get("rows", [])):
                    for x, cj in enumerate(row):
                        if y < rows and x < cols:
                            layer.set(x, y, Cell(cj[0], cj[1], cj[2], cj[3]))
                frame.layers.append(layer)
            movie.frames.append(frame)
            continue
        # Fallback: flat Durdraw file — rebuild as a single-layer frame.
        frame = movie.new_frame()
        # Replace layers with a single non-transparent base layer.
        base = Layer(cols, rows, transparent=False)
        base.name = "bg"
        contents = fj.get("contents", [])
        color_map = fj.get("colorMap", [])
        for y, line in enumerate(contents):
            for x, ch in enumerate(line):
                if y >= rows or x >= cols:
                    continue
                # color_map[x][y] per Durdraw convention.
                try:
                    pair = color_map[x][y]
                except (IndexError, TypeError):
                    pair = [7, 0]
                fg = pair[0] if len(pair) > 0 else 7
                bg = pair[1] if len(pair) > 1 else 0
                base.set(x, y, Cell(ch, fg, bg, 0))
        frame.layers = [base]
        frame.delay = fj.get("delay", 0.1)
        movie.frames.append(frame)
    if not movie.frames:
        movie.frames.append(movie.new_frame())
    return movie


# ---- .ans (classic ANSI SGR) ---------------------------------------------

def save_ans(movie: Movie, path: str | Path, frame_index: int = 0) -> Path:
    """Export a single frame as a .ans file. Multi-frame movies lose the
    other frames — .ans isn't an animation format. Use .dur for animation."""
    path = Path(path)
    frame = movie.frames[frame_index]
    composited = _composite_frame(frame, movie.cols, movie.rows)
    out: list[str] = []
    prev_fg: int | None = None
    prev_bg: int | None = None
    prev_attr: int = 0
    mode = movie.color_format
    for y in range(movie.rows):
        for x in range(movie.cols):
            c = composited[y][x]
            # Emit SGR sequence only when colors/attrs change.
            if c.fg != prev_fg or c.bg != prev_bg or c.attr != prev_attr:
                parts: list[str] = ["0"]  # reset first so we don't inherit stale attr
                if c.attr & 1:
                    parts.append("1")   # bold
                if c.attr & 2:
                    parts.append("5")   # blink
                if c.attr & 4:
                    parts.append("7")   # reverse
                parts.append(sgr_fg(c.fg, mode))
                parts.append(sgr_bg(c.bg, mode))
                out.append(f"\x1b[{';'.join(parts)}m")
                prev_fg, prev_bg, prev_attr = c.fg, c.bg, c.attr
            out.append(c.ch if c.ch else " ")
        out.append("\r\n")
    out.append("\x1b[0m")
    text = "".join(out)
    # CP437 round-trip for classic BBS/DOS compatibility.
    if movie.encoding == "cp437":
        data = text.encode("cp437", errors="replace")
    else:
        data = text.encode("utf-8", errors="replace")
    path.write_bytes(data)
    return path


def _composite_frame(frame: Frame, cols: int, rows: int) -> list[list[Cell]]:
    """Flatten a frame's visible layers into a single grid."""
    out: list[list[Cell]] = []
    for y in range(rows):
        row: list[Cell] = []
        for x in range(cols):
            row.append(frame.composite(x, y))
        out.append(row)
    return out
