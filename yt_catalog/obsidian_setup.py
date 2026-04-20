"""Install the yt-catalog Obsidian assets into a vault.

Single source of truth for:
  - the "YT Catalog Skip Checkbox" plugin (shift-click -> [-], + a refresh button)
  - the checkbox-state CSS snippet
and the config toggles that enable them. `yt-catalog setup` calls
``install_obsidian_assets`` so a fresh machine gets these without hand-copying.
"""
from __future__ import annotations
import json
from pathlib import Path

PLUGIN_ID = "yt-skip-checkbox"
SNIPPET_ID = "yt-catalog-checkboxes"

MANIFEST = {
    "id": PLUGIN_ID,
    "name": "YT Catalog Skip Checkbox",
    "version": "1.3.0",
    "minAppVersion": "1.4.0",
    "description": "Shift-click a watchlist checkbox to toggle [-] skipped, plus a button to run `yt-catalog refresh` for the open run.",
    "author": "yt-catalog",
    "isDesktopOnly": True,
}

PLUGIN_MAIN_JS = r'''"use strict";
/*
 * YT Catalog Skip Checkbox + Refresh  (installed by `yt-catalog setup`)
 *   - shift-click a task checkbox -> toggle [-] skipped ([ ] <-> [-]);
 *     normal click stays [ ] <-> [x].
 *   - a "Refresh this run" button (ribbon, command, and an inline button via a
 *     ```yt-refresh``` code block) runs `yt-catalog refresh <run-dir>` headlessly.
 * Desktop only (spawns the CLI via Node child_process).
 */
const { Plugin, Notice, MarkdownView } = require("obsidian");

const MARK_RE = /^(\s*[-*]\s*\[)[ xX\-~/](\])/;
const VID_RE = /watch\?v=([\w-]+)/;

module.exports = class YtSkipCheckbox extends Plugin {
  async onload() {
    console.log("[yt-skip] loaded");
    new Notice("YT Skip Checkbox active (shift-click = skip)");

    this.registerDomEvent(document, "click", (evt) => this.onClick(evt), { capture: true });

    this.addRibbonIcon("refresh-cw", "YT Catalog: refresh this run", () => this.runCli("refresh"));
    this.addCommand({
      id: "yt-catalog-refresh-run",
      name: "Refresh this run (apply watchlist marks + regenerate)",
      callback: () => this.runCli("refresh"),
    });
    this.addCommand({
      id: "yt-catalog-insights-run",
      name: "Build insights for this run",
      callback: () => this.runCli("insights"),
    });

    // Inline buttons from fenced blocks: ```yt-refresh``` and ```yt-insights```.
    this.registerMarkdownCodeBlockProcessor("yt-refresh", (_src, el) => {
      const btn = el.createEl("button", { text: "🔄  Refresh this run (apply watchlist marks)" });
      btn.addClass("yt-refresh-btn");
      btn.onclick = () => this.runCli("refresh", btn);
    });
    this.registerMarkdownCodeBlockProcessor("yt-insights", (_src, el) => {
      const btn = el.createEl("button", { text: "📊  Rebuild insights for this run" });
      btn.addClass("yt-refresh-btn");
      btn.onclick = () => this.runCli("insights", btn);
    });
  }

  onClick(evt) {
    if (!evt.shiftKey) return;
    const cb = evt.target;
    if (!(cb instanceof HTMLInputElement) || !cb.classList.contains("task-list-item-checkbox")) return;

    const mv = this.app.workspace.getActiveViewOfType(MarkdownView);
    const editor = mv && mv.editor;
    const cm = editor && editor.cm;
    if (cm && typeof cm.posAtDOM === "function") {
      try {
        const pos = cm.posAtDOM(cb);
        const line = cm.state.doc.lineAt(pos);
        if (MARK_RE.test(line.text)) {
          evt.preventDefault();
          evt.stopImmediatePropagation();
          const isSkipped = /^\s*[-*]\s*\[-\]/.test(line.text);
          const ns = isSkipped ? " " : "-";
          const newText = line.text.replace(MARK_RE, (_m, a, b) => a + ns + b);
          // Dispatch a minimal change that KEEPS the current selection, so the
          // editor doesn't scroll/jump to the top after the edit.
          cm.dispatch({
            changes: { from: line.from, to: line.to, insert: newText },
            selection: cm.state.selection,
            scrollIntoView: false,
          });
          console.log("[yt-skip] (editor) line", line.number, "->", ns === "-" ? "skipped" : "unmarked");
          return;
        }
      } catch (e) {
        console.log("[yt-skip] editor path failed, trying reading-view", e);
      }
    }

    const scope = cb.closest("li, .task-list-item") || cb.parentElement;
    const link = scope && scope.querySelector('a[href*="watch?v="]');
    const m = link && (link.getAttribute("href") || "").match(VID_RE);
    if (!m) {
      console.log("[yt-skip] could not locate the task line for this checkbox");
      return;
    }
    evt.preventDefault();
    evt.stopImmediatePropagation();
    this.toggleSkipByVid(m[1]);
  }

  async toggleSkipByVid(vid) {
    const file = this.app.workspace.getActiveFile();
    if (!file) return;
    const token = "watch?v=" + vid;
    let ns = "?";
    const rewrite = (data) => {
      const lines = data.split("\n");
      for (let i = 0; i < lines.length; i++) {
        if (lines[i].includes(token) && MARK_RE.test(lines[i])) {
          const isSkipped = /^\s*[-*]\s*\[-\]/.test(lines[i]);
          ns = isSkipped ? " " : "-";
          lines[i] = lines[i].replace(MARK_RE, (_m, a, b) => a + ns + b);
          break;
        }
      }
      return lines.join("\n");
    };
    if (this.app.vault.process) await this.app.vault.process(file, rewrite);
    else await this.app.vault.modify(file, rewrite(await this.app.vault.read(file)));
    console.log("[yt-skip] (reading) toggle", vid, "->", ns === "-" ? "skipped" : "unmarked");
  }

  runCli(sub, btn) {
    const file = this.app.workspace.getActiveFile();
    if (!file) { new Notice("YT: open a file inside the run first"); return; }
    const m = file.path.match(/(^|.*\/)(runs\/[^/]+)\//);
    if (!m) { new Notice("YT: not inside a runs/<date>/ folder"); return; }
    const base = this.app.vault.adapter.basePath;
    const runAbs = `${base}/${m[2]}`;

    let spawn;
    try { spawn = require("child_process").spawn; }
    catch (e) { new Notice("YT: child_process unavailable (desktop only)"); return; }

    // Immediate, visible loading state on the button + a persistent Notice.
    let restore = null;
    if (btn) {
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "⏳  Running yt-catalog " + sub + " …";
      btn.style.opacity = "0.7";
      restore = () => { btn.disabled = false; btn.textContent = orig; btn.style.opacity = ""; };
    }
    const loading = new Notice("YT Catalog: running " + sub + " on " + m[2] + " …", 0);

    const cmd = `yt-catalog ${sub} ${JSON.stringify(runAbs)}`;
    const child = spawn(process.env.SHELL || "/bin/zsh", ["-lc", cmd], { cwd: base });
    let err = "";
    child.stderr.on("data", (d) => (err += d.toString()));
    const done = (msg) => { loading.hide(); if (restore) restore(); new Notice(msg); };
    child.on("error", (e) => done("YT " + sub + " failed to start: " + e.message));
    child.on("close", (code) => {
      if (code === 0) done("YT Catalog: " + sub + " ✓ (reopen the run's notes)");
      else { console.log("[yt-skip] " + sub + " stderr:", err); done("YT " + sub + " exited " + code + " — see console"); }
    });
  }
};
'''

CHECKBOX_CSS = r'''/* yt-catalog — distinguish watchlist checkbox states (installed by setup).
 *   [x] watched -> solid green | [-] skipped -> amber dashed + struck | [ ] keep
 * Enable: Settings -> Appearance -> CSS snippets -> reload -> toggle on.
 */
input.task-list-item-checkbox[data-task="x"],
input.task-list-item-checkbox[data-task="X"],
li[data-task="x"] > input.task-list-item-checkbox,
li[data-task="X"] > input.task-list-item-checkbox {
  --checkbox-color: #22c55e;
  --checkbox-color-hover: #22c55e;
  border-color: #22c55e !important;
  background-color: #22c55e !important;
}

input.task-list-item-checkbox[data-task="-"],
li[data-task="-"] > input.task-list-item-checkbox,
li[data-task="-"] > p > input.task-list-item-checkbox,
.task-list-item[data-task="-"] > .task-list-item-checkbox {
  --checkbox-marker-color: transparent;
  background-color: transparent !important;
  background-image: none !important;
  border: 2px dashed #f59e0b !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
}

li[data-task="-"].task-list-item,
.task-list-item[data-task="-"] {
  text-decoration: line-through;
  text-decoration-color: rgba(245, 158, 11, 0.6);
  color: var(--text-faint);
}

/* inline "Refresh this run" button (from the ```yt-refresh``` block) */
button.yt-refresh-btn {
  background: var(--interactive-accent);
  color: var(--text-on-accent);
  border: none;
  border-radius: 6px;
  padding: 8px 14px;
  font-weight: 600;
  cursor: pointer;
}
button.yt-refresh-btn:hover { filter: brightness(1.1); }
'''


def _merge_json_list(path: Path, value: str) -> None:
    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = []
    if not isinstance(data, list):
        data = []
    if value not in data:
        data.append(value)
    path.write_text(json.dumps(data, indent=2))


def install_obsidian_assets(vault_root: Path) -> dict:
    """Write the plugin + CSS snippet into ``vault_root/.obsidian`` and enable them.

    Returns a small summary dict. Safe to re-run (overwrites the asset files,
    de-dupes the enable lists).
    """
    obs = vault_root / ".obsidian"
    plug = obs / "plugins" / PLUGIN_ID
    snips = obs / "snippets"
    plug.mkdir(parents=True, exist_ok=True)
    snips.mkdir(parents=True, exist_ok=True)

    (plug / "manifest.json").write_text(json.dumps(MANIFEST, indent=2))
    (plug / "main.js").write_text(PLUGIN_MAIN_JS)
    (snips / f"{SNIPPET_ID}.css").write_text(CHECKBOX_CSS)

    _merge_json_list(obs / "community-plugins.json", PLUGIN_ID)

    # appearance.json holds enabledCssSnippets as a list under a key.
    ap = obs / "appearance.json"
    appearance = {}
    if ap.exists():
        try:
            appearance = json.loads(ap.read_text())
        except Exception:
            appearance = {}
    snippets = appearance.get("enabledCssSnippets", [])
    if SNIPPET_ID not in snippets:
        snippets.append(SNIPPET_ID)
    appearance["enabledCssSnippets"] = snippets
    ap.write_text(json.dumps(appearance, indent=2))

    return {"plugin": str(plug), "snippet": str(snips / f"{SNIPPET_ID}.css")}
