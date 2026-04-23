# ansi-editor-tui

A terminal-native ANSI / ASCII art editor built with
[Textual](https://textual.textualize.io/). Durdraw-compatible `.dur` file
format (read/write, round-trips through the reference), plus classic `.ans`
export. Mouse-first but fully keyboard-drivable.

## Features

- Canvas widget — per-cell glyph + fg + bg + attr (bold / blink / reverse /
  underline). 80×25 by default, any size supported.
- Tool palette — pencil, fill, line, rectangle, eraser, color picker,
  selection. Bresenham-line drag for pencil. Preview-and-revert for line /
  rectangle so the user can reposition mid-drag.
- Color picker — 16-color mode (durdraw standard) + 256-color mode
  (toggle with `x`). Unicode / CP437 charset toggle (`X`).
- Layers — at least 2 per frame; transparent top-layer convention.
- Animation frames — native to the `.dur` format, timeline pane, playback.
- File format — `.dur` (gzipped JSON, Durdraw v7) for native I/O + `.ans`
  (classic CP437 + SGR escapes) for export.
- Undo / redo stack over every tool stroke.
- Mouse + keyboard — press `?` in-app for the full quick reference.

## Quick start

```bash
make all           # create venv, install package
make run           # launch editor
make test          # 38 Pilot scenarios + perf suite
make test-only PAT=tool   # subset by name pattern
```

Launch with an existing file:

```bash
.venv/bin/python ansi_edit.py path/to/art.dur
```

## Layout

```
+----------------------------+----------+
|       canvas (scroll)      |  TOOLS   |
|                            |  BRUSH   |
|                            |  PALETTE |
|                            |  LAYERS  |
|                            |  FRAMES  |
+----------------------------+----------+
|  flash bar — coords, tool, brush preview |
+------------------------------------------+
```

## Key bindings (summary)

| Group      | Keys                                                 |
|------------|------------------------------------------------------|
| Tools      | `1`–`7` (pencil, eraser, fill, line, rect, picker, sel) |
| Cursor     | arrows move · `enter` / `space` apply                |
| Brush      | `f`/`F` fg −/+ · `b`/`B` bg −/+ · `c`/`C` char −/+   |
| Mode       | `x` 16/256 · `X` utf-8/cp437                         |
| Layers     | `[`/`]` nav · `n` new · `D` del · `V` toggle vis     |
| Frames     | `,`/`.` nav · `+` add · `-` del · `P` play           |
| Undo       | `ctrl+z` undo · `ctrl+y` redo                        |
| Files      | `ctrl+s` save · `s` save-as · `ctrl+o` load          |
| Pickers    | `ctrl+p` palette · `ctrl+g` char grid                |
| Other      | `?` help · `q` quit                                  |

## Design

See [`DECISIONS.md`](DECISIONS.md) for the file format, layer model, tool
dispatch, undo implementation, and publishing notes. The clean-room build
was guided by the `tui-game-build` skill: research → scaffold → QA harness
first → perf → robustness → polish.

Durdraw itself is cloned into `engine/durdraw/` by `make bootstrap` for
format reference only; we don't depend on it at runtime.

## License

MIT. (Durdraw is GPLv3 but lives in `engine/` for reference — we don't
link against it.)
