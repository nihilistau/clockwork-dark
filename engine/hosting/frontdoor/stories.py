"""
The Front Door: the Story Table and the Picker
==============================================

ROUTING BY A CHOICE IN THE COOKIE (spec §14.5). ``POST /stories/<slug>``
(CSRF-checked with the stateless logged-in form token, ``auth.form_token``)
writes ``story`` into the signed Flask session, so the browser's next request
reaches that story's worker. ``GET /`` without a choice goes to ``/stories``,
unless exactly one story is ready, which is then chosen. ``GET /stories``
lists the stories that are ready, with their titles from the registry's
listing (``registry.get``: a manifest read, nothing activated).

ONE STORY PER BROWSER. The choice is one cookie, so a browser plays one
story at a time: a switch in one tab moves every tab's HTTP to the new
story, while a WebSocket already open stays on the old story's worker, and
the client's resume key (``clockwork_save_id``, one ``localStorage`` entry
per origin, ``ui/src/core/socket.js``) keeps only the story played last. Two
stories in two tabs of one browser is NOT WIRED (docs/GOVERNANCE.md, spec
§14.13 row 3); a per-story Socket.IO path is v0.21.0's way out.

THE STORY TABLE (``StoryTable``) is the front door's own copy of the
supervisor's: read once with ``stories.list`` when the front door connects,
then replaced by every ``stories.changed`` notification (spec §14.3), so a
request finds its worker (state, port) without a bus round trip. Each
notification carries a ``seq``; an older one than the table holds is
dropped (the bus pool may run two at once). One lock, a LEAF.

A story is ROUTABLE while its worker is ``ready``, ``degraded`` (its HTTP
health check failing, the process fine) or ``draining`` (finishing the turns
in flight before a stop), with a port. Otherwise a request for it is
answered 503 by the proxy: a small page for ``GET /`` ("<title> is
restarting", "<title> was stopped by the operator", or, held down after a
crash loop, "<title> is not running"), JSON ``{"error": "story
unavailable"}`` everywhere else.

THE PAGES (``stories.html``, ``unavailable.html``) are plain HTML with no
JavaScript, rendered from ``frontdoor/templates/`` through this module's own
Jinja environment (as ``auth.render_page`` does), styled by
``/static/hosting/hosting.css``.

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from flask import Blueprint, abort, redirect, request, session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from engine.hosting.auth import current_account, form_token, form_token_ok
from engine.hosting.frontdoor.gate import STORY, admission

logger = logging.getLogger(__name__)

#: The blueprint's name; its endpoints are ``frontdoor_stories.<view>``.
BLUEPRINT_NAME = "frontdoor_stories"

#: Worker states a request is routed in (with a port).
ROUTABLE_STATES = frozenset({"ready", "degraded", "draining"})

#: Worker states the picker offers.
READY_STATES = frozenset({"ready", "degraded"})

#: What a page for a story that is not routable says, by state.
UNAVAILABLE_TEXT = {
    "stopped": "{title} was stopped by the operator.",
    "held_down": "{title} is not running. The operator has been told.",
}
RESTARTING_TEXT = "{title} is restarting. Try again in a moment."

#: The front door's own templates (``frontdoor/templates/``): its own loader,
#: so no story or scene template of the same name can stand in.
_PAGES = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


def render_page(name: str, **context: Any) -> str:
    """Render one of the front door's pages."""
    return _PAGES.get_template(name).render(**context)


class StoryTable:
    """
    The front door's copy of the supervisor's story table (see the module
    docstring). Thread-safe: one lock, a LEAF (engine/locks.py).
    """

    def __init__(self, slugs: Iterable[str], titles: Optional[dict[str, str]] = None) -> None:
        #: ``hosting.stories``, in order: the stories this instance serves.
        self.slugs = [str(s) for s in slugs]
        self.titles = dict(titles or {})
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}
        self._seq = -1

    def replace(self, rows: Iterable[dict[str, Any]], seq: int) -> bool:
        """Take ``rows`` (each ``slug``, ``state``, ``port``) at ``seq``; False when older than the table."""
        fresh: dict[str, dict[str, Any]] = {}
        for row in rows:
            slug = str(row.get("slug") or "")
            if slug in self.slugs:
                fresh[slug] = {"slug": slug, "state": str(row.get("state") or ""), "port": int(row.get("port") or 0)}
        with self._lock:
            if int(seq) < self._seq:
                return False
            self._seq = int(seq)
            self._rows = fresh
        return True

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def get(self, slug: str) -> Optional[dict[str, Any]]:
        """The routing row of ``slug``, or None (not one of this instance's stories)."""
        with self._lock:
            row = self._rows.get(str(slug))
            return dict(row) if row is not None else None

    def rows(self) -> list[dict[str, Any]]:
        """Every row, in ``hosting.stories`` order."""
        with self._lock:
            return [dict(self._rows[s]) for s in self.slugs if s in self._rows]

    @staticmethod
    def routable(row: Optional[dict[str, Any]]) -> bool:
        return bool(row) and row["state"] in ROUTABLE_STATES and int(row["port"]) > 0  # type: ignore[index]

    def ready(self) -> list[dict[str, Any]]:
        """The rows the picker offers."""
        return [r for r in self.rows() if r["state"] in READY_STATES and int(r["port"]) > 0]

    def title(self, slug: str) -> str:
        return self.titles.get(slug) or slug


def titles_for(slugs: Iterable[str]) -> dict[str, str]:
    """Each story's title from its manifest, read without activating anything."""
    from engine.games import registry

    found: dict[str, str] = {}
    for slug in slugs:
        manifest = registry.get(slug)
        found[str(slug)] = str(getattr(manifest, "title", "") or slug)
    return found


def unavailable_page(table: StoryTable, row: Optional[dict[str, Any]], slug: str) -> Any:
    """The 503 page for ``GET /`` when the chosen story is not routable."""
    state = str((row or {}).get("state") or "")
    text = UNAVAILABLE_TEXT.get(state, RESTARTING_TEXT).format(title=table.title(slug))
    return render_page("unavailable.html", message=text), 503


def stories_blueprint(table: StoryTable, forward: Any) -> Blueprint:
    """
    ``GET /stories``, ``POST /stories/<slug>`` and ``GET /`` (factory).
    ``forward(slug, row)`` is the proxy's: ``GET /`` with a routable choice
    is the chosen story's own page.
    """
    blueprint = Blueprint(BLUEPRINT_NAME, __name__)

    @blueprint.get("/stories")
    def picker() -> Any:
        account = current_account()
        if account is None:  # the gate has answered already; never reached
            abort(401)
        offered = [{"slug": r["slug"], "title": table.title(r["slug"])} for r in table.ready()]
        return render_page(
            "stories.html",
            stories=offered,
            chosen=str(session.get(STORY) or ""),
            csrf=form_token(account),
            account=account,
        )

    @blueprint.post("/stories/<slug>")
    def choose(slug: str) -> Any:
        account = current_account()
        if account is None:
            abort(401)
        if not form_token_ok(account, request.form.get("csrf")):
            offered = [{"slug": r["slug"], "title": table.title(r["slug"])} for r in table.ready()]
            return (
                render_page(
                    "stories.html",
                    stories=offered,
                    chosen=str(session.get(STORY) or ""),
                    csrf=form_token(account),
                    account=account,
                    message="This form has expired. Reload the page and try again.",
                ),
                403,
            )
        if slug not in table.slugs:
            abort(404)
        session[STORY] = slug
        logger.info("[frontdoor] Story chosen (operation=choose, account=%s, story=%s)", account.id, slug)
        return redirect("/", code=303)

    @blueprint.route("/", methods=["GET", "HEAD"])
    def index() -> Any:
        found = admission()
        if found.story:
            if not table.routable(found.row):
                return unavailable_page(table, found.row, found.story)
            return forward(found.story, found.row)
        ready = table.ready()
        if len(ready) == 1:
            # Exactly one story ready: chosen, and this request goes there.
            only = ready[0]
            session[STORY] = only["slug"]
            return forward(only["slug"], only)
        return redirect("/stories", code=303)

    return blueprint


__all__ = [
    "BLUEPRINT_NAME",
    "READY_STATES",
    "ROUTABLE_STATES",
    "StoryTable",
    "render_page",
    "stories_blueprint",
    "titles_for",
    "unavailable_page",
]
