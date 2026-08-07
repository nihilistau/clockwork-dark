"""
FlaskScene Base
===============

Minimal Flask + Socket.IO scene host (CosySim pattern).

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify
from flask_socketio import SocketIO


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
        self.register()

    def _register_health(self) -> None:
        @self.app.get("/api/health")
        def health() -> Any:
            return jsonify({"status": "ok", "scene": self.name})

    def register(self) -> None:
        """Override to add scene routes and socket handlers."""

    def run(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 5573,
        debug: bool = False,
    ) -> None:
        """Start the scene server."""
        self.socketio.run(
            self.app,
            host=host,
            port=port,
            debug=debug,
            allow_unsafe_werkzeug=True,
        )