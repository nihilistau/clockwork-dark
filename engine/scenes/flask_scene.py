"""
FlaskScene Base
===============

Minimal Flask + Socket.IO scene host (CosySim pattern).

Subclasses supply two things:

    blueprints()   route sets to mount -- the engine's shared API, plus
                   whatever Blueprint the active story declares
    register()     the scene's own routes and socket handlers

Blueprints are mounted BEFORE ``register()`` runs, so a subclass can still
claim a rule a blueprint left free, and a story blueprint that fails to import
costs its own screens rather than the whole scene.

Version: v0.2.0 [2026-08-08]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, Flask, jsonify
from flask_socketio import SocketIO

from engine.scenes.spec import scene_port


class FlaskScene:
    """
    Base scene server wiring Flask app and Socket.IO.

    Subclasses register routes and socket handlers in ``register``.
    """

    def __init__(
        self,
        *,
        name: str,
        static_folder: Path,
        template_folder: Path,
        testing: bool = False,
    ) -> None:
        self.name = name
        self.testing = testing
        self.app = Flask(
            name,
            static_folder=str(static_folder),
            static_url_path="/static",
            template_folder=str(template_folder),
        )
        self.app.config["TESTING"] = testing
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins="*",
            async_mode="threading",
        )
        self._register_health()
        for blueprint in self.blueprints():
            if blueprint is not None:
                self.app.register_blueprint(blueprint)
        self.register()

    def _register_health(self) -> None:
        @self.app.get("/api/health")
        def health() -> Any:
            return jsonify({"status": "ok", "scene": self.name})

    def blueprints(self) -> list[Blueprint]:
        """Override to declare route sets mounted before ``register()``."""
        return []

    def register(self) -> None:
        """Override to add scene routes and socket handlers."""

    def run(
        self,
        *,
        host: str = "0.0.0.0",
        port: Optional[int] = None,
        debug: bool = False,
    ) -> None:
        """
        Start the scene server.

        ``port`` defaults from ``scene.<name>.port`` rather than a literal.
        The number had four homes and config was only one of them.
        """
        self.socketio.run(
            self.app,
            host=host,
            port=port if port is not None else scene_port(self.name),
            debug=debug,
            allow_unsafe_werkzeug=True,
        )
