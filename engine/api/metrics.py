"""
Metrics HTTP API
================

    GET /api/metrics    what the agents are actually doing, as numbers

Process-wide and unpersisted; these are numbers about this run of the server,
not about a save. The telemetry oracle is engine machinery every story shares.

Wire it into a scene with one line in its ``register()``::

    from engine.api.metrics import metrics_blueprint
    app.register_blueprint(metrics_blueprint())

Version: v0.1.0 [2026-08-08]
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

BLUEPRINT_NAME = "metrics"


def metrics_blueprint(name: str = BLUEPRINT_NAME) -> Blueprint:
    """Build the metrics blueprint. Factory, not a singleton -- see games/api.py."""
    blueprint = Blueprint(name, __name__)

    @blueprint.get("/api/metrics")
    def api_metrics() -> Any:
        """
        What the agents are actually doing, as numbers.

        Exists so the Assistant and the prompts can be tuned against data
        instead of vibes. The most useful series is `unearned_claims`: the
        governance chain records every stat delta the model asserted with no
        tool receipt behind it, and a stat that keeps appearing there is a
        prompt defect that is otherwise completely invisible -- the engine
        drops the claim silently and correctly, and nobody ever finds out
        the model kept trying.
        """
        from engine.telemetry import get_oracle

        oracle = get_oracle()
        return jsonify({"metrics": oracle.metrics(), "recent": oracle.recent(20)})

    return blueprint


__all__ = ["BLUEPRINT_NAME", "metrics_blueprint"]
