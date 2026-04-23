"""Entry point — `python ansi_edit.py [path.dur]`."""

from __future__ import annotations

import argparse

from ansi_editor.app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="ansi-editor-tui")
    p.add_argument("path", nargs="?", default=None,
                   help="path to a .dur file (load if exists, save target otherwise)")
    args = p.parse_args()
    run(args.path)


if __name__ == "__main__":
    main()
