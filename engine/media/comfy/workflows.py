"""
ComfyUI Workflows
=================

A workflow is a ComfyUI graph in its API format -- exported from ComfyUI
unmodified ("Save (API Format)") -- and its BINDINGS: each value the engine
fills (``positive``, ``seed``, ``width`` ...) mapped to ``[node id, input
name]`` in that graph (v0.22.0 spec §13.4). The engine never builds a graph in
code: an operator swaps the checkpoint loader for an IP-Adapter chain, or adds
a LoRA stack, by pointing ``comfyui.workflows.<name>.template`` at their own
export and re-mapping the bindings.

A binding naming a node or an input the template does not have is a LOAD-TIME
error (:class:`BindingError`, a ``ValueError`` naming the config key), never a
graph posted to ComfyUI that silently ignores the value.

The prompt is bound as the caller wrote it: there is no negative prompt slot,
filter, classifier or rewriting step here (AGENTS.md rule 12).

Which provider makes a story's phone media is :func:`phone_media_provider`,
read from ``phone_media.provider`` alone. The art pipeline's own ComfyUI
switch is a different key and is never read here (spec §13.4, I2): turning
the art pipeline on must not make any story's turn post workflows.

Version: v0.1.0 [2026-10-12]
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.config import get_config

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]

#: What ``phone_media.provider`` may name (spec §13.4-13.5); ``procedural`` is off.
PHONE_MEDIA_PROVIDERS = ("comfyui", "stub", "procedural")

#: Unknown ``phone_media.provider`` values already warned about: one WARNING
#: per value per process, not one per job (a race costs a duplicate line).
_WARNED_PROVIDERS: set[str] = set()

#: What a workflow's ``output.kind`` may name.
OUTPUT_KINDS = ("image", "video", "audio")


class BindingError(ValueError):
    """A workflow that cannot load: its template, bindings or output, by config key."""


@dataclass(frozen=True)
class Workflow:
    """One loaded, checked workflow (``comfyui.workflows.<name>``)."""

    name: str
    graph: dict[str, Any]
    bindings: dict[str, tuple[str, str]]
    output_node: str
    output_kind: str
    size: dict[str, int] = field(default_factory=dict)
    #: A video's poster: the node whose first ``images`` file is its first
    #: frame (``output.poster_node``); "" when the workflow declares none.
    poster_node: str = ""


def _template_path(raw: str) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else _ROOT / candidate


def load_workflow(name: str) -> Workflow:
    """
    ``comfyui.workflows.<name>``, loaded and checked: the template parses as an
    API-format graph, every binding's node and input exist in it, the output
    node (and a video's optional ``poster_node``) exists and its kind is known. Raises :class:`BindingError` naming the
    key otherwise. Read fresh on every call (a template is a few KB), so an
    operator's edit is seen at the next job.
    """
    key = f"comfyui.workflows.{name}"
    spec = get_config().get(key)
    if not isinstance(spec, dict):
        raise BindingError(f"{key}: no such workflow is declared")

    raw_template = str(spec.get("template") or "").strip()
    if not raw_template:
        raise BindingError(f"{key}.template: missing")
    path = _template_path(raw_template)
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BindingError(f"{key}.template: cannot read {raw_template} ({exc})") from None
    except ValueError as exc:
        raise BindingError(f"{key}.template: {raw_template} is not JSON ({exc})") from None
    if not isinstance(graph, dict) or not graph:
        raise BindingError(f"{key}.template: {raw_template} is not an API-format graph (an object of nodes)")
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise BindingError(f"{key}.template: {raw_template} node {node_id} has no inputs object")

    raw_bindings = spec.get("bindings") or {}
    if not isinstance(raw_bindings, dict):
        raise BindingError(f"{key}.bindings: must be a mapping of name -> [node, input]")
    bindings: dict[str, tuple[str, str]] = {}
    for value_name, target in raw_bindings.items():
        where = f"{key}.bindings.{value_name}"
        if not isinstance(target, (list, tuple)) or len(target) != 2:
            raise BindingError(f"{where}: must be [node, input], got {target!r}")
        node_id, input_name = str(target[0]), str(target[1])
        if node_id not in graph:
            raise BindingError(f"{where}: node {node_id} is not in {raw_template}")
        if input_name not in graph[node_id]["inputs"]:
            raise BindingError(f"{where}: node {node_id} of {raw_template} has no input {input_name!r}")
        bindings[str(value_name)] = (node_id, input_name)

    output = spec.get("output") or {}
    if not isinstance(output, dict):
        raise BindingError(f"{key}.output: must be {{node, kind}}")
    output_node = str(output.get("node") or "")
    if output_node not in graph:
        raise BindingError(f"{key}.output.node: node {output_node or '(none)'} is not in {raw_template}")
    output_kind = str(output.get("kind") or "image")
    if output_kind not in OUTPUT_KINDS:
        raise BindingError(f"{key}.output.kind: {output_kind!r} is not one of {', '.join(OUTPUT_KINDS)}")
    poster_node = str(output.get("poster_node") or "")
    if poster_node and poster_node not in graph:
        raise BindingError(f"{key}.output.poster_node: node {poster_node} is not in {raw_template}")

    raw_size = spec.get("size") or {}
    if not isinstance(raw_size, dict):
        raise BindingError(f"{key}.size: must be a mapping of name -> integer")
    try:
        size = {str(k): int(v) for k, v in raw_size.items()}
    except (TypeError, ValueError):
        raise BindingError(f"{key}.size: every value must be an integer, got {raw_size!r}") from None

    return Workflow(
        name=name,
        graph=graph,
        bindings=bindings,
        output_node=output_node,
        output_kind=output_kind,
        size=size,
        poster_node=poster_node,
    )


def bind(workflow: Workflow, values: dict[str, Any]) -> dict[str, Any]:
    """
    A deep copy of the workflow's graph with each bound input set from
    ``values``. A value the workflow does not bind (``reference_image`` for a
    graph with no reference input) is ignored; a value it binds is always set.
    A binding given no value keeps the template's own.
    """
    graph = copy.deepcopy(workflow.graph)
    for value_name, value in values.items():
        target = workflow.bindings.get(value_name)
        if target is None:
            continue
        node_id, input_name = target
        graph[node_id]["inputs"][input_name] = value
    return graph


def phone_media_provider() -> str:
    """
    Which provider makes a story's phone media: ``comfyui``, ``stub`` or
    ``procedural`` (off), from ``phone_media.provider`` ONLY (spec §13.4, I2).
    An unknown name is ``procedural``, logged once per value.
    """
    raw = str(get_config().get("phone_media.provider", "procedural") or "procedural").strip().lower()
    if raw in PHONE_MEDIA_PROVIDERS:
        return raw
    if raw in _WARNED_PROVIDERS:
        return "procedural"
    _WARNED_PROVIDERS.add(raw)
    logger.warning(
        "[media] Unknown phone media provider, using procedural "
        "(operation=phone_media_provider, provider=%s, legal=%s)",
        raw,
        "|".join(PHONE_MEDIA_PROVIDERS),
    )
    return "procedural"
