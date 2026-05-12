"""`yt-catalog subscriptions` — dump the API's subscription list (avatar + name +
metadata) to vault/subscriptions.md, OUTSIDE the run folders, for manual review.

Purpose: let you eyeball whether the set the API returns matches the channels
where your notification bell is ON (vs. all your subscriptions).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from ..utils import get_data_dir


def _fetch_all_subscriptions() -> list[dict]:
    from ..oauth import get_access_token
    tok = get_access_token()
    items: list[dict] = []
    page_token = None
    while True:
        params = {"part": "snippet,contentDetails", "mine": "true",
                  "maxResults": 50, "order": "alphabetical"}
        if page_token:
            params["pageToken"] = page_token
        req = urllib.request.Request(
            "https://www.googleapis.com/youtube/v3/subscriptions?" + urllib.parse.urlencode(params))
        req.add_header("Authorization", f"Bearer {tok}")
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def handle_subscriptions(args: argparse.Namespace) -> None:
    os.chdir(get_data_dir())
    from ..oauth import is_authenticated
    if not is_authenticated():
        print("Not authenticated. Run `yt-catalog setup` first.", file=sys.stderr)
        return

    print("Fetching subscriptions via the YouTube Data API...")
    items = _fetch_all_subscriptions()
    rows = []
    for it in items:
        sn = it.get("snippet", {})
        cd = it.get("contentDetails", {})
        rows.append({
            "title": sn.get("title", ""),
            "cid": sn.get("resourceId", {}).get("channelId", ""),
            "avatar": sn.get("thumbnails", {}).get("default", {}).get("url", ""),
            "activity": cd.get("activityType", ""),
            "subscribed": (sn.get("publishedAt", "") or "")[:10],
            "total": cd.get("totalItemCount", ""),
        })
    rows.sort(key=lambda r: r["title"].lower())

    lines = [
        "---", "tags: [youtube-catalog, subscriptions]", "---",
        "# Subscriptions returned by the YouTube Data API\n",
        f"**{len(rows)} channels** via `subscriptions.list?mine=true`.\n",
        "> Check: if these are exactly the channels where your **notification bell is ON**, "
        "the API is handing us your bell-enabled set (problem solved). If you spot channels "
        "here with the bell **OFF**, it's just a (capped) subset of all your subscriptions.\n",
        "| # | Avatar | Channel | Subscribed | Feed type | Channel videos | Channel ID |",
        "|--:|---|---|---|---|--:|---|",
    ]
    for i, r in enumerate(rows, 1):
        avatar = f"![\\|40]({r['avatar']})" if r["avatar"] else ""
        link = f"[{r['title']}](https://www.youtube.com/channel/{r['cid']})" if r["cid"] else r["title"]
        lines.append(f"| {i} | {avatar} | {link} | {r['subscribed']} | "
                     f"{r['activity']} | {r['total']} | `{r['cid']}` |")

    out = Path("vault") / "subscriptions.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"Wrote {len(rows)} subscriptions to {out}")
    print("Open it in Obsidian and compare against your bell-on channels.")
