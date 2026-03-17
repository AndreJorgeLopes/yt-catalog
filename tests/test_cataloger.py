from yt_catalog.cli import main
import pytest


def test_parse_run_defaults(capsys):
    """yt-catalog run with no extra args parses defaults."""
    # We can't run the full pipeline, but we can test that --help works
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--source" in captured.out
    assert "--max-days" in captured.out
    assert "--from-checkpoint" in captured.out


def test_parse_setup_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["setup", "--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--api-key-only" in captured.out


def test_parse_discover_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["discover", "--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "checkpoint" in captured.out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "0.1.0" in captured.out


def test_no_command_fails():
    """Calling with no subcommand should fail."""
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code != 0
