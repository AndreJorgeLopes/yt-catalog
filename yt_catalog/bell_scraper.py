"""Notification-bell (subscriptions) scraper — headless, cookie-based.

``youtube.com/feed/channels`` lists every subscription together with its
notification-bell setting (All / Personalized / None). That setting exists ONLY
in the page's ``ytInitialData`` — the Data API's
``subscriptions.contentDetails.activityType`` is hardwired to ``"all"`` and
carries NO bell signal (verified empirically: 995/995 subs returned ``"all"``).
So this page parse is the only headless source of bell state.

The bell value comes from, per channel::

    channelRenderer
      .subscribeButton.subscribeButtonRenderer
        .notificationPreferenceButton
          .subscriptionNotificationToggleButtonRenderer.currentStateId

``currentStateId``: 2 = All, 3 = Personalized, 0 = None.

The whole subscription list is server-rendered into ``ytInitialData`` in one
GET — no scrolling or continuation tokens needed.
"""
from __future__ import annotations

from . import web_session

# subscriptionNotificationToggleButtonRenderer.currentStateId -> label
BELL_STATE = {2: "all", 3: "personalized", 0: "none"}
# "on" = anything that can notify you.
NOTIFY_ON = {"all", "personalized"}


def _text(node) -> str | None:
    if not node:
        return None
    if "simpleText" in node:
        return node["simpleText"]
    if "runs" in node:
        return "".join(r.get("text", "") for r in node["runs"])
    return None


def _harvest(node, out: list[dict]) -> None:
    if isinstance(node, list):
        for x in node:
            _harvest(x, out)
    elif isinstance(node, dict):
        cr = node.get("channelRenderer")
        if cr:
            tb = (
                cr.get("subscribeButton", {})
                .get("subscribeButtonRenderer", {})
                .get("notificationPreferenceButton", {})
                .get("subscriptionNotificationToggleButtonRenderer")
            )
            state = tb.get("currentStateId") if tb else None
            out.append(
                {
                    "id": cr.get("channelId"),
                    "title": _text(cr.get("title")),
                    "bell": BELL_STATE.get(state),
                }
            )
        for v in node.values():
            _harvest(v, out)


def parse_subscriptions(initial_data: dict) -> list[dict]:
    """Extract ``[{id, title, bell}]`` from a /feed/channels ``ytInitialData``.

    Pure function — easy to unit-test against a saved fixture. De-dupes by id.
    """
    rows: list[dict] = []
    _harvest(initial_data, rows)
    seen: set[str] = set()
    uniq: list[dict] = []
    for r in rows:
        cid = r.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            uniq.append(r)
    return uniq


def get_subscriptions(**kw) -> list[dict]:
    """All subscriptions with bell state: ``[{id, title, bell}]``.

    Keyword args pass through to ``web_session.get_initial_data`` (``browser``,
    ``cookie_file``, ``reextract``, ``timeout``).
    """
    data = web_session.get_initial_data("/feed/channels", **kw)
    return parse_subscriptions(data)


def get_bell_all(**kw) -> list[dict]:
    """Subscriptions with the bell set to ALL (notify on every upload)."""
    return [r for r in get_subscriptions(**kw) if r["bell"] == "all"]


def get_bell_on(**kw) -> list[dict]:
    """Subscriptions that can notify you at all (All OR Personalized)."""
    return [r for r in get_subscriptions(**kw) if r["bell"] in NOTIFY_ON]


def get_bell_all_ids(**kw) -> list[str]:
    """Just the ``UC...`` ids of the bell=All subscriptions."""
    return [r["id"] for r in get_bell_all(**kw)]
