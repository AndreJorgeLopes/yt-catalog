"""Tests for the Obsidian asset installer."""
import json
from pathlib import Path

from yt_catalog.obsidian_setup import install_obsidian_assets, PLUGIN_ID, SNIPPET_ID


def test_install_writes_and_enables(tmp_path):
    vault = tmp_path / "vault"
    out = install_obsidian_assets(vault)
    obs = vault / ".obsidian"
    # files written
    assert (obs / "plugins" / PLUGIN_ID / "main.js").exists()
    assert (obs / "plugins" / PLUGIN_ID / "manifest.json").exists()
    assert (obs / "snippets" / f"{SNIPPET_ID}.css").exists()
    # plugin + snippet enabled
    assert PLUGIN_ID in json.loads((obs / "community-plugins.json").read_text())
    assert SNIPPET_ID in json.loads((obs / "appearance.json").read_text())["enabledCssSnippets"]
    # main.js carries the key behaviours
    js = (obs / "plugins" / PLUGIN_ID / "main.js").read_text()
    assert "registerMarkdownCodeBlockProcessor" in js
    assert "yt-catalog refresh" in js
    assert out["plugin"].endswith(PLUGIN_ID)


def test_install_idempotent(tmp_path):
    vault = tmp_path / "vault"
    install_obsidian_assets(vault)
    install_obsidian_assets(vault)   # re-run
    obs = vault / ".obsidian"
    # no duplicate entries
    assert json.loads((obs / "community-plugins.json").read_text()).count(PLUGIN_ID) == 1
    snips = json.loads((obs / "appearance.json").read_text())["enabledCssSnippets"]
    assert snips.count(SNIPPET_ID) == 1


def test_install_preserves_existing_config(tmp_path):
    vault = tmp_path / "vault"
    obs = vault / ".obsidian"
    obs.mkdir(parents=True)
    (obs / "community-plugins.json").write_text(json.dumps(["media-extended"]))
    (obs / "appearance.json").write_text(json.dumps({"theme": "obsidian", "enabledCssSnippets": ["other"]}))
    install_obsidian_assets(vault)
    plugins = json.loads((obs / "community-plugins.json").read_text())
    assert "media-extended" in plugins and PLUGIN_ID in plugins
    appearance = json.loads((obs / "appearance.json").read_text())
    assert appearance["theme"] == "obsidian"
    assert "other" in appearance["enabledCssSnippets"] and SNIPPET_ID in appearance["enabledCssSnippets"]
