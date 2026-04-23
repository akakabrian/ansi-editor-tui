# ansi-editor-tui — design decisions

## 1. Angle — Textual-native clean-room rewrite of Durdraw

[cmang/durdraw](https://github.com/cmang/durdraw) is the canonical open
source ANSI art editor (Python + curses, GPLv3). It already owns the
"terminal ANSI art editor" niche. We differentiate on:

* **Textual rendering pipeline** — Rich segments + ScrollView
  `render_line()` instead of ncurses, so the canvas scales beyond the
  terminal window and perf tricks (viewport crop, run-length segments)
  already exist.
* **Mouse-first UX** — pencil drag, rectangle select, color-picker
  clicks. Durdraw was built for keyboard + function-key workflows.
* **.dur v7 compatible save/load** — files written here open in
  Durdraw unchanged, and the reverse. Interop, not replacement.
* **Modern layering + frame timeline** pane, not menu-driven.
* **QA harness from day one** (Textual Pilot, scenario subset hotkey).

We clone Durdraw into `engine/durdraw/` for format reference only (file
parser, charset tables, sauce record format). No runtime dependency —
this is a vendor pattern like Julius / OpenTTD, not SWIG glue.

## 2. File format — Durdraw v7 (.dur) + classic ANSI (.ans)

`.dur` is a gzipped JSON with a `DurMovie` root. Fields:

```
formatVersion = 7
colorFormat   = "16" | "256"
encoding      = "utf-8" | "cp437"
columns, lines, framerate, name, artist
frames[] = { frameNumber, delay, contents[line_str], colorMap[col][row] = [fg, bg] }
```

Note: the doc text claims `colorMap[y][x]` but the reference example
and `durdraw_file.py:299` both use `colorMap[x][y]` (column-major).
We match the real file layout so files round-trip with Durdraw.

`.ans` is classic ANSI — CP437 byte stream with SGR escape sequences
(`\x1b[...m`). Fg colors 30-37 / bright 90-97, bg 40-47 / 100-107.

## 3. Canvas model — flat numpy-free arrays

Each frame holds three parallel grids (chars, fg, bg) sized
`lines × columns`. Attribute byte (bold/blink/reverse) packed as a
bitmask into a fourth grid. No numpy dependency — the canvases are
small (default 80×25 = 2000 cells) and pure-Python lists are fine
for the target size. If a user makes a huge canvas (1000×1000) we'd
revisit; until then simplicity wins.

## 4. Tool dispatch — one Tool class per verb

Tools are plain classes with `begin(x,y)`, `drag(x,y)`, `commit()`
methods returning a list of `Edit` objects. The editor applies each
`Edit` to the canvas and appends the reverse-edit batch to the undo
stack. This keeps tool logic decoupled from canvas mutation and
makes undo/redo a trivial stack-of-batches.

## 5. Undo/redo — batched reverse-ops

Every tool commit produces one batch of `Edit(x, y, old_cell,
new_cell)` tuples. Applying `new_cell` is "redo"; applying `old_cell`
is "undo". The stack holds batches, the redo stack holds the batches
we've undone. A new edit clears the redo stack, same as every sane
editor.

## 6. Color palette — 16 first, 256 swapable

Default mode is 16-color (durdraw interoperates) but the color picker
and renderer support 256-color. Mode is per-canvas. We pre-parse the
`rich.style.Style` for every (fg, bg, attr) combo that actually
appears on screen into an LRU cache — parsing per cell dominates TUI
perf, just like in simcity-tui.

## 7. Layers — separate frame[] stacks

Per the spec, minimum 2 layers. Each layer is its own `Canvas` with
transparency (chars `\x00` = "see through" to layer below). Durdraw
doesn't have layers natively; we store them under `DurMovie.extra`
as `{"layers": [...]}` so the files still round-trip through Durdraw
(which ignores `extra`).

## 8. Animation frames

Native to Durdraw format. Each frame has its own canvas stack +
delay. The timeline pane lets the user duplicate / insert / delete /
navigate frames.

## 9. QA scenarios (MVP set)

1. App mounts, canvas widget exists
2. Cursor starts at (0, 0)
3. Arrow keys move cursor, clamped at bounds
4. Pencil tool writes a char with selected fg/bg
5. Undo reverses the write
6. Redo re-applies it
7. Fill tool fills a contiguous region
8. Rectangle tool outlines a box
9. Tool palette click selects a tool
10. Save to `.dur` → reload → canvas matches
11. Save to `.ans` is valid CP437 + SGR
12. Color picker updates selected fg

## 10. Layout — 3-pane editor

```
 +------------------------+------------+
 |        canvas          |  tools     |
 |   (ScrollView)         |  palette   |
 |                        |  colors    |
 |                        |  layers    |
 |                        |  frames    |
 +------------------------+------------+
 | flash bar (status line)             |
 +-------------------------------------+
```

Keyboard-first with mouse support. Priority bindings on arrow keys so
they're not eaten by ScrollView.

## 11. Publishing notes

Engine/ is gitignored — `make bootstrap` clones Durdraw fresh. The
project code is MIT (wrapper has no linkage to GPL Durdraw source,
only format compat). LICENSE TBD on first push.
