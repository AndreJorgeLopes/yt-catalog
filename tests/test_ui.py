"""UI helpers: link escapes + summary box alignment (non-TTY = plain)."""
import io
from contextlib import redirect_stdout

import yt_catalog.ui as ui


def test_link_plain_off_tty():
    # conftest/CI: stdout not a tty -> _TTY False -> plain text, no escapes
    assert ui.link("vault/", "file:///x") == "vault/"


def test_link_osc8_when_tty(monkeypatch):
    monkeypatch.setattr(ui, "_TTY", True)
    out = ui.link("vault/", "file:///abs/path")
    assert out == "\033]8;;file:///abs/path\033\\vault/\033]8;;\033\\"
    assert ui._visible(out) == "vault/"          # measures to the visible text


def test_select_non_interactive_returns_default_silently(monkeypatch, capsys):
    # stdin not a tty -> default, NO input() call, NO prompt printed
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert ui.select("pick", ["a", "b", "c"], default=2) == 2
    assert capsys.readouterr().out == ""        # nothing printed


def test_confirm_non_interactive_uses_default():
    assert ui.confirm("ok?", default=True) is True
    assert ui.confirm("ok?", default=False) is False


def test_summary_box_aligned_with_link(monkeypatch):
    monkeypatch.setattr(ui, "_TTY", True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        ui.summary("Done", [
            ("Vault", "vault/runs/2026-06-16/", "file:///abs/very/long/path/here"),
            ("Videos", "32 total · 24 new"),
        ])
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    widths = {len(ui._visible(ln)) for ln in lines}
    assert len(widths) == 1                       # every border line same visible width
