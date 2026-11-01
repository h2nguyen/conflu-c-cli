"""`--out FILE` of the commands that print a body: the file is written by the program, as UTF-8, and not by the shell's `>`.

Windows PowerShell 5.1 re-encodes what `>` saves (the UTF-8 that the program prints is decoded with the code page of the console and stored as
UTF-16), so a body with an umlaut or a euro sign is damaged on its way into the file, and `update --file` writes the damage back.
"""
from __future__ import annotations

import argparse

from .....domain.errors import UsageError
from ..render import printable
from ..runtime import Context
from ..spec import WRITES_FILE, Arg


def out_option(what: str = "body") -> Arg:
    return Arg(
        ("--out",),
        f"Write the {what} to this file as UTF-8 instead of printing it (Windows PowerShell 5.1 damages what `>` saves). "
        "One line says what was written. Changes nothing in Confluence.",
        metavar="FILE",
        path=WRITES_FILE,
    )


FORCE = Arg(("--force",), "Replace the file --out names if it exists (never the settings of the CLI).", kind="flag", overwrites=True)


def prepare_out(ctx: Context, args: argparse.Namespace, *, body_only: bool | None = None, example: str = "") -> None:
    """The usage errors of `--out` and `--force`, and what the file may not be, judged before anything is asked of Confluence. `body_only` is
    whether the command was asked for the body alone, which `--out` needs (None for a command without that option)."""
    if args.out is None:
        if args.force:
            raise UsageError("--force replaces the file that --out names.", hint="Give --out FILE, or leave out --force.")
        return
    if body_only is False:
        raise UsageError("--out writes the body alone, so it needs --body-only.", hint=f"Example: {example}" if example else "Add --body-only.")
    ctx.app.out_file.check(args.out, force=args.force)


def deliver(ctx: Context, args: argparse.Namespace, text: str) -> None:
    """Prints the text, or with `--out` writes into that file exactly the text that would have been printed (the same line ends and the same
    characters left out) and says so in one line: `{"file", "bytes"}` in JSON mode."""
    if args.out is None:
        ctx.print(text)
        return
    written = ctx.app.out_file.write(args.out, printable(text) + "\n", force=args.force)
    if ctx.json_mode:
        ctx.print_json({"file": written.path, "bytes": written.size})
    else:
        ctx.print(f"Wrote {written.size} bytes to {written.path}")
