"""Tiny ANSI styling helpers for a polished CLI look.

TTY- and NO_COLOR-guarded: when stdout isn't a terminal (pipes, CI, the test
suite) every helper degrades to plain ASCII text, so captured output stays clean
and assertions keep matching on the words.
"""
from __future__ import annotations

import itertools
import os
import re
import sys
import threading
import time

_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_WIDTH = 60


def _wrap(code: str):
    if not _TTY:
        return lambda s: str(s)
    return lambda s: f"\033[{code}m{s}\033[0m"


bold = _wrap("1")
dim = _wrap("2")
red = _wrap("31")
green = _wrap("32")
yellow = _wrap("33")
blue = _wrap("34")
magenta = _wrap("35")
cyan = _wrap("36")


def _glyph(fancy: str, plain: str) -> str:
    return fancy if _TTY else plain


# Strip CSI color codes and OSC-8 hyperlink wrappers to measure visible width.
_ANSI_RE = re.compile(r"\033\[[0-9;]*m|\033\]8;;[^\033\a]*(?:\033\\|\a)")


def _visible(s: str) -> str:
    return _ANSI_RE.sub("", s)


def link(text: str, url: str) -> str:
    """Make ``text`` a clickable OSC-8 hyperlink to ``url`` (e.g. a file:// path).

    Supported by Ghostty, iTerm2, kitty, WezTerm, modern VTE terminals; others
    just render ``text`` (the escapes are ignored). Plain ``text`` off-TTY.
    """
    if not _TTY:
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def header(title: str, subtitle: str | None = None) -> None:
    """Top banner for the whole run."""
    inner = _WIDTH - 2
    top = "╭" + "─" * inner + "╮"
    bot = "╰" + "─" * inner + "╯"
    bar = "│"
    print()
    print(cyan(top))
    print(cyan(bar) + bold(title.center(inner)) + cyan(bar))
    if subtitle:
        print(cyan(bar) + dim(subtitle.center(inner)) + cyan(bar))
    print(cyan(bot))


def phase(n: int, total: int, title: str) -> None:
    """Section banner for one pipeline phase."""
    tag = cyan(f"[{n}/{total}]")
    print()
    print(f"{cyan(_glyph('▸', '>'))} {tag} {bold(title)}")


def step(msg: str) -> None:
    print(f"  {dim(_glyph('·', '-'))} {msg}")


def ok(msg: str) -> None:
    print(f"  {green(_glyph('✓', 'OK'))} {msg}")


def info(msg: str) -> None:
    print(f"  {blue(_glyph('ℹ', 'i'))} {msg}")


def warn(msg: str) -> None:
    print(f"  {yellow(_glyph('⚠', '!'))} {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"  {red(_glyph('✗', 'x'))} {msg}", file=sys.stderr)


def detail(msg: str) -> None:
    print(f"      {dim(msg)}")


def kv(label: str, value: str) -> None:
    print(f"  {dim(label + ':'):<22} {bold(value)}")


def section(title: str) -> None:
    """Lightweight sub-header for a group of steps (e.g. the prep stage)."""
    print()
    print(f"{dim('┄')} {bold(title)}")


# --------------------------------------------------------------------------- #
# Interactive arrow-key select
# --------------------------------------------------------------------------- #
def select(prompt: str, options: list[str], default: int = 0) -> int:
    """Arrow-key single-select. Returns the chosen index.

    Up/Down (or k/j) to move, Enter to pick, Esc/q to take the default. Falls
    back to a numbered text prompt on a TTY without raw-mode (e.g. Windows), and
    returns ``default`` SILENTLY when there's no interactive stdin (CI, pipes,
    tests) — never blocks on input there. Never raises.
    """
    if not sys.stdin.isatty():
        return default  # non-interactive: silent default, no prompt
    try:
        import termios
        import tty
    except Exception:
        termios = tty = None  # type: ignore
    if termios is None or not sys.stdout.isatty():
        return _select_numbered(prompt, options, default)

    idx = max(0, min(default, len(options) - 1))
    print()
    print(f"  {bold(prompt)}")
    print(dim("  ↑/↓ to move · Enter to select"))

    def _render(first: bool):
        if not first:
            sys.stdout.write(f"\033[{len(options)}A")  # cursor up N lines
        for i, opt in enumerate(options):
            sys.stdout.write("\033[2K")  # clear line
            if i == idx:
                sys.stdout.write(f"  {cyan('❯')} {bold(opt)}\n")
            else:
                sys.stdout.write(f"    {dim(opt)}\n")
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        _render(first=True)
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                break
            if ch in ("\x1b",):  # escape sequence (arrows) or bare esc
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % len(options)
                elif seq == "[B":
                    idx = (idx + 1) % len(options)
                elif seq == "":
                    idx = default  # bare Esc -> default
                    break
            elif ch in ("k", "K"):
                idx = (idx - 1) % len(options)
            elif ch in ("j", "J"):
                idx = (idx + 1) % len(options)
            elif ch in ("q", "\x03"):  # q / Ctrl-C -> default
                idx = default
                break
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            _render(first=False)
            tty.setraw(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()
    return idx


def confirm(prompt: str, default: bool = True) -> bool:
    """Yes/No as an arrow-select. Returns True for Yes.

    Non-interactive contexts return ``default`` (via select()'s fallback)."""
    return select(prompt, ["Yes", "No"], default=0 if default else 1) == 0


def _select_numbered(prompt: str, options: list[str], default: int) -> int:
    """Non-TTY fallback for select(): numbered input (default on empty/EOF)."""
    print()
    print(f"  {prompt}")
    for i, opt in enumerate(options):
        mark = "*" if i == default else " "
        print(f"   {mark}[{i + 1}] {opt}")
    try:
        raw = input(f"  Choose [1-{len(options)}] (default {default + 1}): ").strip()
    except (EOFError, OSError):
        return default
    if not raw:
        return default
    try:
        n = int(raw) - 1
        if 0 <= n < len(options):
            return n
    except ValueError:
        pass
    return default


# --------------------------------------------------------------------------- #
# Spinner (indeterminate work)
# --------------------------------------------------------------------------- #
class spinner:
    """Context manager: animated spinner for indeterminate work.

    No-op (just prints the label once) when stdout isn't a TTY, so logs stay
    clean. Use ``with ui.spinner("Fetching ..."): work()``.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not _TTY:
            print(f"  {self.label} ...")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r  {cyan(frame)} {self.label}")
            sys.stdout.flush()
            time.sleep(0.08)

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stdout.write("\r\033[2K")  # clear the spinner line
            sys.stdout.flush()
        return False


class loading_bar:
    """Context manager: an INDETERMINATE animated loading bar.

    For opaque blocking work with no measurable progress (the bell fetch is one
    GET, or one `claude --print` subprocess — no per-item signal). A filled
    segment sweeps back and forth so it reads as a real loading bar without
    faking a percentage. No-op (prints the label once) when stdout isn't a TTY.
    """

    def __init__(self, label: str, width: int = 26, seg: int = 6):
        self.label = label
        self.width = width
        self.seg = seg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not _TTY:
            print(f"  {self.label} ...")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        span = max(1, self.width - self.seg)
        # triangle wave: 0..span..0
        cycle = list(range(span + 1)) + list(range(span - 1, 0, -1))
        for pos in itertools.cycle(cycle):
            if self._stop.is_set():
                break
            track = " " * pos + "█" * self.seg + " " * (self.width - self.seg - pos)
            sys.stdout.write(f"\r  {self.label}  {dim('[')}{cyan(track)}{dim(']')}")
            sys.stdout.flush()
            time.sleep(0.05)

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()
        return False


class live_progress:
    """Determinate progress bar with an ALWAYS-MOVING spinner char.

    For phases that advance in chunks with long gaps between updates (the AI
    categorize phase: a batch can take a while). The bar fills as ``advance()``
    is called, but the spinner keeps animating every tick so the user sees the
    app is alive, not frozen. Optional one-time ``note`` printed above the bar.

    Usage::

        with ui.live_progress(total, "Categorizing", note="uses AI ...") as p:
            ... p.advance(n) ...

    No-op-friendly off-TTY: prints the label/note once, no animation, a final
    line on exit.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, total: int, label: str, note: str | None = None,
                 width: int = 30):
        self.total = max(0, total)
        self.label = label
        self.note = note
        self.width = width
        self._done = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if self.note:
            print(f"  {dim(self.note)}")
        if not _TTY:
            print(f"  {self.label} … 0/{self.total}")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self._done += n

    def _bar(self, glyph: str) -> str:
        """``glyph`` is already styled by the caller."""
        done = min(self._done, self.total)
        frac = (done / self.total) if self.total else 1.0
        filled = int(self.width * frac)
        bar = "█" * filled + dim("░" * (self.width - filled))
        pct = int(frac * 100)
        return (f"\r  {glyph} {self.label} {dim('[')}{bar}{dim(']')} "
                f"{pct:3d}%  {dim(f'{done}/{self.total}')}")

    def _run(self):
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(self._bar(cyan(frame)))
            sys.stdout.flush()
            time.sleep(0.1)

    def __exit__(self, *exc):
        if self._thread:
            self._stop.set()
            self._thread.join()
            sys.stdout.write(self._bar(green(_glyph("✓", "v"))) + "\n")
            sys.stdout.flush()
        elif not _TTY:
            print(f"  {self.label} … {min(self._done, self.total)}/{self.total} done")
        return False


def summary(title: str, pairs: list[tuple]) -> None:
    """Closing box with key/value results.

    Each pair is ``(label, value)`` or ``(label, value, url)``; when a url is
    given the value is rendered as a clickable OSC-8 link. Padding is computed on
    the VISIBLE width (escape bytes excluded) so the box border stays aligned.
    """
    inner = _WIDTH - 2
    top = "╭" + "─" * inner + "╮"
    bot = "╰" + "─" * inner + "╯"
    bar = "│"
    print()
    print(green(top))
    print(green(bar) + bold(title.center(inner)) + green(bar))
    print(green(bar) + " " * inner + green(bar))
    for pair in pairs:
        label, value = pair[0], pair[1]
        url = pair[2] if len(pair) > 2 else None
        plain = f"  {label:<22} {value}"
        if len(_visible(plain)) > inner:                 # truncate on visible text
            plain = plain[:inner]
        pad = " " * (inner - len(_visible(plain)))
        body = plain
        if url:
            body = plain.replace(value, link(value, url), 1)
        print(green(bar) + body + pad + green(bar))
    print(green(bot))
