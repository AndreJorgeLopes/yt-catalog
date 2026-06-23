"""Install the yt-catalog Obsidian assets into a vault.

Single source of truth for:
  - the "YT Catalog Skip Checkbox" plugin (shift-click -> [-], channel-parent
    cascade, live "mixed" indeterminate state, + refresh/insights buttons)
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
    "version": "1.4.0",
    "minAppVersion": "1.4.0",
    "description": "Watchlist checkboxes: shift-click = skip [-], channel parent cascades to all its videos with a live mixed state, plus refresh/insights buttons.",
    "author": "yt-catalog",
    "isDesktopOnly": True,
}

PLUGIN_MAIN_JS = r'''"use strict";
/*
 * YT Catalog Skip Checkbox + Refresh  (installed by `yt-catalog setup`)
 *
 * Checkboxes (watchlist + insights):
 *   - leaf video task: normal click [ ]<->[x] (Obsidian default); shift-click
 *     toggles [-] skipped.
 *   - channel PARENT task (a task that has indented child tasks under it):
 *     normal click cascades [x] to every child; shift-click cascades [-]; click
 *     again to clear. The parent shows a LIVE "mixed" state when its children
 *     differ (computed by the plugin — Obsidian has no native indeterminate).
 *   Cascade is instant (edits the file); applying marks to the catalog still
 *   runs through the Refresh button.
 *
 * Buttons: ribbon + command + ```yt-refresh``` / ```yt-insights``` code blocks
 * run `yt-catalog refresh|insights <run-dir>` headlessly. Desktop only.
 */
const { Plugin, Notice, MarkdownView } = require("obsidian");

const TASK_RE = /^(\s*)[-*]\s*\[([ xX\-~/])\]/;   // [1]=indent [2]=mark
const VID_RE = /watch\?v=([\w-]+)/;

const mark = (t) => { const m = t.match(TASK_RE); return m ? m[2] : null; };
const indent = (t) => { const m = t.match(TASK_RE); return m ? m[1].length : null; };
const setBox = (t, nb) => { const c = mark(t); return c == null ? t : t.replace("[" + c + "]", "[" + nb + "]"); };

module.exports = class YtSkipCheckbox extends Plugin {
  async onload() {
    console.log("[yt-skip] loaded");
    new Notice("YT Skip Checkbox active (shift-click = skip)");

    this.registerDomEvent(document, "click", (e) => this.onClick(e), { capture: true });

    this.addRibbonIcon("refresh-cw", "YT Catalog: refresh this run", () => this.runCli("refresh"));
    this.addCommand({ id: "yt-catalog-refresh-run", name: "Refresh this run (apply watchlist marks + regenerate)", callback: () => this.runCli("refresh") });
    this.addCommand({ id: "yt-catalog-insights-run", name: "Build insights for this run", callback: () => this.runCli("insights") });
    this.registerMarkdownCodeBlockProcessor("yt-refresh", (_s, el) => { const b = el.createEl("button", { text: "🔄  Refresh this run (apply watchlist marks)" }); b.addClass("yt-refresh-btn"); b.onclick = () => this.runCli("refresh", b); });
    this.registerMarkdownCodeBlockProcessor("yt-insights", (_s, el) => { const b = el.createEl("button", { text: "📊  Rebuild insights for this run" }); b.addClass("yt-refresh-btn"); b.onclick = () => this.runCli("insights", b); });

    // Live "mixed" parent state — recompute on render + on any checkbox change.
    this.repaint = this.repaint.bind(this);
    this.registerEvent(this.app.workspace.on("layout-change", () => this.scheduleRepaint()));
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.scheduleRepaint()));
    this._mo = new MutationObserver(() => this.scheduleRepaint());
    this._mo.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-task"] });
    this.register(() => this._mo.disconnect());
    this.scheduleRepaint();
  }

  scheduleRepaint() { clearTimeout(this._rt); this._rt = setTimeout(this.repaint, 120); }

  // ── click handling ───────────────────────────────────────────────
  onClick(evt) {
    const cb = evt.target;
    if (!(cb instanceof HTMLInputElement) || !cb.classList.contains("task-list-item-checkbox")) return;
    const shift = evt.shiftKey;

    // Live Preview: locate the source line via the editor.
    const mv = this.app.workspace.getActiveViewOfType(MarkdownView);
    const editor = mv && mv.editor, cm = editor && editor.cm;
    if (cm && typeof cm.posAtDOM === "function") {
      try {
        const line = cm.state.doc.lineAt(cm.posAtDOM(cb));
        if (TASK_RE.test(line.text)) {
          const kids = this.childTaskLines(cm, line);
          if (kids.length) {                       // PARENT -> cascade
            evt.preventDefault(); evt.stopImmediatePropagation();
            const target = shift ? "-" : "x";
            const allTarget = kids.every((l) => mark(l.text) === target);
            const nb = allTarget ? " " : target;
            const changes = [{ from: line.from, to: line.to, insert: setBox(line.text, nb) }];
            for (const l of kids) changes.push({ from: l.from, to: l.to, insert: setBox(l.text, nb) });
            cm.dispatch({ changes, selection: cm.state.selection, scrollIntoView: false });
            this.scheduleRepaint();
            return;
          }
          if (shift) {                             // LEAF -> toggle skip
            evt.preventDefault(); evt.stopImmediatePropagation();
            const nb = mark(line.text) === "-" ? " " : "-";
            cm.dispatch({ changes: { from: line.from, to: line.to, insert: setBox(line.text, nb) }, selection: cm.state.selection, scrollIntoView: false });
            this.scheduleRepaint();
          }
          return;                                  // leaf normal click -> Obsidian default
        }
      } catch (e) { console.log("[yt-skip] editor path failed", e); }
    }

    // Reading view fallback (URLs are real hrefs here).
    const li = cb.closest("li.task-list-item") || cb.closest("li");
    if (!li) return;
    const kidCbs = li.querySelectorAll("ul .task-list-item-checkbox, ol .task-list-item-checkbox");
    if (kidCbs.length) {                            // PARENT -> cascade by vid
      evt.preventDefault(); evt.stopImmediatePropagation();
      const vids = Array.from(li.querySelectorAll('ul a[href*="watch?v="], ol a[href*="watch?v="]'))
        .map((a) => (a.getAttribute("href") || "").match(VID_RE)).filter(Boolean).map((m) => m[1]);
      this.cascadeFile(vids, shift ? "-" : "x").then(() => this.scheduleRepaint());
      return;
    }
    if (shift) {                                    // LEAF -> skip
      const a = li.querySelector('a[href*="watch?v="]');
      const m = a && (a.getAttribute("href") || "").match(VID_RE);
      if (m) { evt.preventDefault(); evt.stopImmediatePropagation(); this.toggleByVid(m[1], "-").then(() => this.scheduleRepaint()); }
    }
  }

  childTaskLines(cm, parentLine) {
    const pIndent = indent(parentLine.text), out = [], doc = cm.state.doc;
    for (let n = parentLine.number + 1; n <= doc.lines; n++) {
      const ln = doc.line(n);
      if (ln.text.trim() === "") continue;
      const ind = ln.text.match(/^(\s*)/)[1].length;
      if (ind <= pIndent) break;                    // dedent -> block ends
      if (TASK_RE.test(ln.text)) out.push(ln);
    }
    return out;
  }

  async editFile(file, fn) {
    if (this.app.vault.process) await this.app.vault.process(file, fn);
    else await this.app.vault.modify(file, fn(await this.app.vault.read(file)));
  }

  async toggleByVid(vid, target) {
    const file = this.app.workspace.getActiveFile(); if (!file) return;
    await this.editFile(file, (data) => data.split("\n").map((ln) => {
      const m = ln.match(VID_RE);
      if (m && m[1] === vid && TASK_RE.test(ln)) return setBox(ln, mark(ln) === target ? " " : target);
      return ln;
    }).join("\n"));
  }

  async cascadeFile(vids, target) {
    const file = this.app.workspace.getActiveFile(); if (!file || !vids.length) return;
    const set = new Set(vids);
    await this.editFile(file, (data) => {
      const lines = data.split("\n");
      let all = true;
      for (const ln of lines) { const m = ln.match(VID_RE); if (m && set.has(m[1]) && TASK_RE.test(ln) && mark(ln) !== target) { all = false; break; } }
      const nb = all ? " " : target;
      return lines.map((ln) => { const m = ln.match(VID_RE); return (m && set.has(m[1]) && TASK_RE.test(ln)) ? setBox(ln, nb) : ln; }).join("\n");
    });
  }

  // ── live "mixed" parent state ────────────────────────────────────
  repaint() {
    try {
      document.querySelectorAll("li.task-list-item").forEach((li) => {
        const own = li.querySelector(":scope > input.task-list-item-checkbox, :scope > p > input.task-list-item-checkbox");
        if (!own) return;
        const kids = li.querySelectorAll("ul input.task-list-item-checkbox, ol input.task-list-item-checkbox");
        if (!kids.length) { own.indeterminate = false; own.classList.remove("yt-parent-mixed"); return; }
        const states = new Set(Array.from(kids).map((k) => {
          const host = k.closest("li") || k;
          const dt = (host.getAttribute("data-task") || k.getAttribute("data-task") || "").trim().toLowerCase();
          if (dt === "" || dt === " ") return "n";
          if (dt === "x") return "w";
          if (dt === "-" || dt === "~") return "s";
          return "o";
        }));
        if (states.size > 1) { own.indeterminate = true; own.classList.add("yt-parent-mixed"); }
        else { own.indeterminate = false; own.classList.remove("yt-parent-mixed"); }
      });
    } catch (e) { /* best-effort cosmetic */ }
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

    let restore = null;
    if (btn) {
      const orig = btn.textContent;
      btn.disabled = true; btn.textContent = "⏳  Running yt-catalog " + sub + " …"; btn.style.opacity = "0.7";
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
 *   parent "mixed" (some children marked) -> blue (set live by the plugin)
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

/* parent with mixed children — blue with a dash bar */
input.task-list-item-checkbox.yt-parent-mixed {
  background-color: #0a84ff !important;
  border-color: #0a84ff !important;
  background-image: linear-gradient(#fff, #fff) !important;
  background-size: 60% 2px !important;
  background-position: center !important;
  background-repeat: no-repeat !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
}

/* inline "Refresh / insights" buttons (from the code blocks) */
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
