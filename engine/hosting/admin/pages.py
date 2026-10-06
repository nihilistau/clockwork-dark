"""
The Admin Panel: its Pages
==========================

Server-rendered (spec §14.7), from ``engine/hosting/admin/templates/``
through this module's OWN Jinja environment, autoescaped, so no scene's or
story's template of the same name can stand in for an admin page (the
login pages' reason, ``engine/hosting/auth.py``). Every page works with
JavaScript off: each change is a ``POST`` form carrying the admin's CSRF
token, and the one script (``static/admin.js``) only refreshes the
read-only views.

Version: v0.1.0 [2026-10-05]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

#: The admin pages' own template environment (only ``admin/templates/``).
_PAGES = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


def render(name: str, **context: Any) -> str:
    """Render one admin page; ``admin`` and ``csrf`` are the signed-in admin's, when given."""
    return _PAGES.get_template(name).render(**context)


__all__ = ["render"]
