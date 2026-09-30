"""
LM Studio Routes
================

Where the two LM Studio APIs live, derived once so nothing hand-concatenates a
third variant.

LM Studio serves two families on one port, and they are SIBLINGS:

    /v1/*        the OpenAI-compatible API. Real, and the only route that takes
                 ``tools`` and ``response_format`` -- so chat completions stay
                 here (``POST /v1/chat/completions``).
    /api/v1/*    LM Studio's own REST API. ``POST /api/v1/chat`` (the only route
                 where ``reasoning: "off"`` is honoured) and
                 ``GET /api/v1/models`` (the model list, with capabilities and
                 the loaded context length).

``llm.base_url`` means the OpenAI-compat base and keeps that meaning. The
REST root is derived from it by dropping the trailing ``/v1``, which is what
``lmstudio_native.py`` has always done for ``/api/v1/chat``; this module is that
derivation, in one place, for every caller.

WHAT THIS FIXES. ``GET /v1/models`` is not an endpoint LM Studio owns. It
answers -- with an OpenAI-shaped list -- and logs, verbatim:

    [ERROR] Unexpected endpoint or method. (GET /v1/models). Returning 200 anyway

Every doctor run and every ``launcher.py --check`` put that line in the user's
server log. Worse, the "returning 200 anyway" is general: measured on the live
server, ``GET /v1/nonsense`` and ``GET /api/v9/models`` BOTH answer 200 with an
error body. A health check that reads the status code and stops cannot fail, so
it is not a health check. The model list is now asked for once, from
``/api/v1/models``, and the answer is validated by its SHAPE.

Version: v0.1.0 [2026-08-14]
"""

from __future__ import annotations

from typing import Optional

from engine.config import get_config

#: The one route that answers "what models does this server have".
MODELS_PATH = "/api/v1/models"

#: The native chat route. Named here so the two ``/api/v1`` users agree.
CHAT_PATH = "/api/v1/chat"

#: The OpenAI-compatible completions route. Deliberately NOT on /api/v1 -- it is
#: genuinely served, logs no error, and is the only one that accepts tools and
#: structured output.
COMPAT_CHAT_PATH = "/chat/completions"

# -- the other model servers (v0.19.0) -----------------------------------------
#
# Two bases, and ``route_url`` picks between them:
#
#   * the OpenAI list hangs off ``llm.base_url`` itself (``compat_base``), the
#     same base compat chat is sent to -- so a generic server whose base does
#     not end in ``/v1`` (``.../v1beta/openai``, a proxy prefix) is asked for
#     its models where it serves them. For every ``/v1`` base that is the root
#     plus ``/v1/models``, byte for byte;
#   * every other path hangs off the SERVER ROOT (``rest_root``): the base with
#     its trailing ``/v1`` taken off. llama-server's ``/props`` and ``/health``
#     live there, and Ollama's base has no ``/v1`` (``http://localhost:11434``),
#     so its native ``/api/*`` is the root's own.
#
# LM Studio's two paths above are unchanged, and so are ``compat_base`` and
# ``rest_root``.

#: The OpenAI-compatible model list (``{"object": "list", "data": [...]}``):
#: vLLM, llama-server and any generic server, under ``llm.base_url``. NOT LM
#: Studio's -- it answers this route for a path it does not own (the module
#: docstring).
OPENAI_MODELS_PATH = "/models"
#: Paths that hang off ``llm.base_url`` rather than the server root.
COMPAT_PATHS: frozenset[str] = frozenset({OPENAI_MODELS_PATH, COMPAT_CHAT_PATH})
#: llama-server's own properties: ``default_generation_settings.n_ctx`` is the
#: context each slot was started with (``-c``).
LLAMACPP_PROPS_PATH = "/props"
#: vLLM's and llama-server's liveness route (llama-server answers 503 while a
#: model loads).
HEALTH_PATH = "/health"
#: Ollama's installed models.
OLLAMA_TAGS_PATH = "/api/tags"
#: Ollama's per-model facts (POST, ``{"model": <name>}``): ``capabilities`` and
#: ``model_info["<arch>.context_length"]``.
OLLAMA_SHOW_PATH = "/api/show"
#: Ollama's resident models: what is loaded, right now.
OLLAMA_PS_PATH = "/api/ps"
#: Ollama's liveness route.
OLLAMA_VERSION_PATH = "/api/version"
#: Ollama's native chat route: grammar (``format``), ``think``, ``num_ctx`` and
#: tools in one request.
OLLAMA_CHAT_PATH = "/api/chat"


def compat_base(base_url: Optional[str] = None) -> str:
    """The configured base URL, e.g. ``http://localhost:1234/v1`` (LM Studio's OpenAI-compatible base)."""
    cfg_value = get_config().get("llm.base_url", "http://localhost:1234/v1")
    return str(base_url or cfg_value).rstrip("/")


def rest_root(base_url: Optional[str] = None) -> str:
    """
    The server root that ``/api/v1/*`` hangs off.

    ``/api/v1`` is a sibling of ``/v1``, not a child, so the compat suffix comes
    off rather than being appended to.
    """
    compat = compat_base(base_url)
    return compat[: -len("/v1")] if compat.endswith("/v1") else compat


def models_url(base_url: Optional[str] = None) -> str:
    """Absolute URL of the model list."""
    return f"{rest_root(base_url)}{MODELS_PATH}"


#: The port a URL with none names, by scheme.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin(url: str) -> tuple[str, str, int]:
    """
    ``url``'s scheme, host and port, lower-cased, the port made explicit.

    ``("", "", 0)`` for a URL that names no host, which is the origin of
    nothing: it matches no other URL, itself included (``same_origin``).
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(str(url or ""))
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port or _DEFAULT_PORTS.get(scheme, 0)
    except ValueError:
        return ("", "", 0)
    if not host:
        return ("", "", 0)
    return (scheme, host, int(port))


def same_origin(url: str, base_url: Optional[str] = None) -> bool:
    """
    Whether ``url`` is served by the configured model server (v0.19.0,
    finding 3): the same scheme, host and port as ``llm.base_url`` (or
    ``base_url``). The bearer key goes only where this holds, so a key is
    never handed to another service that happens to be health-checked.
    Exact: ``localhost`` and ``127.0.0.1`` are different origins here, as
    they are to a browser.
    """
    mine = origin(url)
    return bool(mine[1]) and mine == origin(compat_base(base_url))


def route_url(path: str, base_url: Optional[str] = None) -> str:
    """
    Absolute URL of one route: under ``llm.base_url`` for ``COMPAT_PATHS``,
    under the server root for every other path (the block comment above).
    """
    base = compat_base(base_url) if path in COMPAT_PATHS else rest_root(base_url)
    return f"{base}{path}"
