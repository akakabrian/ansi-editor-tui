"""Modal screens — help, char picker, palette picker, open/save dialogs."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from . import charset, palette


HELP_TEXT = """\
[bold yellow]ansi-editor-tui — quick reference[/]

[bold cyan]Tools[/]
1 pencil   2 eraser   3 fill   4 line
5 rectangle   6 picker   7 select

[bold cyan]Cursor[/]
arrows move   enter / space apply   click drag

[bold cyan]Brush[/]
f / F   fg -/+
b / B   bg -/+
c / C   char -/+
x       toggle 16 / 256 color mode
X       toggle utf-8 / cp437 charset

[bold cyan]Layers[/]
LBR prev  RBR next   n new   D delete   V toggle visibility

[bold cyan]Frames[/]
, prev   . next   + add   - delete   P play / pause

[bold cyan]Undo[/]
ctrl+z undo   ctrl+y redo

[bold cyan]Files[/]
ctrl+s save   s save-as   ctrl+o load

[bold cyan]Pickers[/]
ctrl+p palette   ctrl+g char grid

[bold cyan]Other[/]
? help   q quit
"""


class HelpScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("q",      "close", show=False),
        Binding("?",      "close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(Text.from_markup(HELP_TEXT), id="help-content")
            yield Static(
                "[dim]esc to close[/]", id="help-footer",
            )

    def action_close(self) -> None:
        self.app.pop_screen()


class PalettePickerScreen(ModalScreen):
    """Grid of color swatches — click/press number to pick fg or bg.
    Opened via `C` for fg or `B` for bg (hypothetical; currently adjusted
    via shift keys)."""

    BINDINGS = [
        Binding("escape", "close", show=False),
    ]

    def __init__(self, which: str = "fg", mode: str = "16") -> None:
        super().__init__()
        self.which = which  # "fg" or "bg"
        self.mode = mode

    def compose(self) -> ComposeResult:
        # Build a 16×(1 or 16) grid of swatches.
        t = Text()
        count = 16 if self.mode == "16" else 256
        for i in range(count):
            r, g, b = palette.rgb(i, self.mode)
            t.append(f" {i:>3} ", style=f"white on rgb({r},{g},{b})")
            if (i + 1) % 16 == 0:
                t.append("\n")
        with Vertical(id="palette-box"):
            yield Static(
                Text.from_markup(f"[bold]{self.which.upper()}[/] "
                                 f"color — click a swatch, esc to close"),
                id="palette-header",
            )
            yield Static(t, id="palette-grid")

    def action_close(self) -> None:
        self.app.pop_screen()


class CharPickerScreen(ModalScreen):
    """Pick a glyph from the active charset. Click the glyph, press esc."""

    BINDINGS = [
        Binding("escape", "close", show=False),
    ]

    def __init__(self, encoding: str) -> None:
        super().__init__()
        self.encoding = encoding

    def compose(self) -> ComposeResult:
        glyphs = charset.glyphs_for(
            "cp437" if self.encoding == "cp437" else "unicode"
        )
        t = Text()
        # Render 16 glyphs per row for cp437; simpler run for unicode picker.
        per_row = 16
        for i, ch in enumerate(glyphs):
            # CP437 control chars (0-31) don't print — render a placeholder.
            disp = ch if (ch and ord(ch) >= 32 and ord(ch) != 127) else "·"
            t.append(f" {disp} ", style="white on rgb(30,30,30)")
            if (i + 1) % per_row == 0:
                t.append("\n")
        with Vertical(id="char-box"):
            yield Static(
                Text.from_markup(f"[bold]charset[/] — {self.encoding}"),
                id="char-header",
            )
            yield Static(t, id="char-grid")
            yield Static("[dim]esc to close[/]", id="char-footer")

    def action_close(self) -> None:
        self.app.pop_screen()


class SaveScreen(ModalScreen):
    """Prompt for a path, save the movie, return the path via callback."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

    def __init__(self, default_path: str) -> None:
        super().__init__()
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="save-box"):
            yield Label("Save As (.dur or .ans):", id="save-label")
            yield Input(value=self.default_path, id="save-input")
            with Horizontal(id="save-buttons"):
                yield Button("Save", id="save-ok", variant="primary")
                yield Button("Cancel", id="save-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-ok":
            path = self.query_one("#save-input", Input).value
            self.dismiss(path)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
