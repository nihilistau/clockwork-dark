"""
Record LLM Fixtures
===================

Re-record one model server's fixtures under ``tests/fixtures/llm/<provider>/``
from the LIVE server the config names, and rewrite their rows in
``tests/fixtures/llm/PROVENANCE.yaml`` as ``origin: recorded`` with the
server's own version, the model that answered and the date (spec §9.3).

    .\\.venv\\Scripts\\python.exe scripts\\record_llm_fixtures.py --provider llamacpp
    .\\.venv\\Scripts\\python.exe scripts\\record_llm_fixtures.py --provider llamacpp ^
        --config C:\\somewhere\\llamacpp.yaml --only chat_patch_ignored

    .venv/bin/python scripts/record_llm_fixtures.py --provider llamacpp \\
        --config ~/somewhere/llamacpp.yaml --only chat_patch_ignored   # Linux

WHY A SCRIPT AND NOT A TEST. It needs a model server on this machine, a model
loaded in it, and -- for some shapes -- a particular KIND of model: a
reasoning model whose template honours ``enable_thinking`` for
``chat_reasoning_off``, one whose template ignores it for
``chat_patch_ignored``. Which is loaded is the operator's choice, so a recipe
that needs a kind CHECKS the answer and refuses to write a fixture that would
be mislabelled. ``tests/test_llm_live.py`` is the live test; this only makes
the bytes the mocked tests replay.

WHAT A FIXTURE HOLDS. A discovery or health body is written as the body
itself (the tests load it as one). A chat answer is written as a canned answer
for ``tests/llm_wire.py`` -- ``{"status", "json"}`` or ``{"status", "sse"}`` --
with the request that produced it under ``request``, so the fixture says what
was asked. Nothing machine-specific is kept: ``/props``' ``model_path`` is
reduced to the model's file name, and no key is ever written: ``error_401``
sends the dummy ``Bearer not-the-key`` on purpose, never the operator's real
``--api-key`` (``llm.api_key``), and ``_write`` replaces any copy of that real
key a server might echo with ``<redacted>`` before a byte reaches a fixture.

CONFIG. ``--config`` names a YAML file read as the ``config/local.yaml`` layer
for this run only (the repo's own ``config/local.yaml`` is never read then,
and never written). Without it the real layers are read.

``--provider ollama`` needs a model whose /api/show lists ``thinking`` and a
chat model that does not (``qwen3:4b`` and an imported GGUF, in v0.19.0);
its multi-model discovery fixtures (``models_tags.json``, ``models_ps.json``,
``models_show_*.json`` for qwen3:8b, llama3.1:8b and an embedding model) are
the documentation's, kept, and the live list is recorded beside them as
``*_live.json``.

``--provider vllm`` (v0.20.0 T19) shares llama-server's chat recipes and adds
its own around them (``_vllm_recipes``); the split recipes need a server
started with ``--reasoning-parser``, the ``*_inline_think_live`` ones a
server started without it, and ``error_401`` one started with ``--api-key``,
so a full set takes two runs, each with ``--only``.

LM Studio's golden is never re-recorded, and a generic server has no fixtures
of its own to re-record.

Version: v0.2.1 [2026-10-06]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import yaml  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "llm"
PROVENANCE = FIXTURES / "PROVENANCE.yaml"

#: A short user turn every chat recipe asks, so the answers stay small.
QUESTION = [{"role": "user", "content": "What is 2+2? Answer with one number only."}]
#: A cap that lets a reasoning model finish thinking on QUESTION.
ROOMY = 3000
from engine.llm.providers import PROVIDERS  # noqa: E402

#: The reasoning-off patch the llamacpp row sends, read from the row itself so
#: a change to it cannot silently diverge from what is recorded. vLLM's row
#: sends the same body (its recipes read their own row's).
THINKING_OFF: dict[str, Any] = dict(PROVIDERS["llamacpp"].reasoning_off.value)


class Refused(Exception):
    """A recipe's answer is not the shape its fixture claims; nothing is written."""


def _use_config(path: Optional[str]) -> None:
    """Read ``path`` as the local layer, from a temp config directory."""
    if not path:
        return
    import engine.config as config

    directory = Path(tempfile.mkdtemp(prefix="record-llm-config-"))
    shutil.copyfile(path, directory / "local.yaml")
    config._CONFIG_DIR = directory
    config._DEFAULT_PATH = ROOT / "config" / "default.yaml"
    config.reset_config()


class Server:
    """The configured server, asked raw: what it sends is what is recorded."""

    def __init__(self) -> None:
        from engine.config import get_config
        from engine.llm.providers import get_provider
        from engine.llm.routes import compat_base, rest_root

        cfg = get_config()
        self.provider = get_provider()
        self.base = compat_base()
        self.root = rest_root()
        key = str(cfg.get("llm.api_key", "") or "")
        #: The real key, kept only so ``_write`` can scrub it from a fixture.
        self.api_key = key
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.timeout = float(cfg.get("llm.timeout_seconds", 300) or 300)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", self.headers)
        return httpx.get(url, headers=headers, timeout=self.timeout, **kwargs)

    def chat(self, body: dict[str, Any], *, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """One completion, as a canned answer with its request."""
        url = f"{self.base}/chat/completions"
        sent = dict(body)
        if body.get("stream"):
            frames: list[dict[str, Any]] = []
            with httpx.stream(
                "POST", url, json=sent, headers=self.headers if headers is None else headers,
                timeout=self.timeout,
            ) as response:
                status = response.status_code
                if status >= 400:
                    response.read()
                    return {"request": sent, "status": status, "json": response.json()}
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    frames.append({"data": data if data == "[DONE]" else json.loads(data)})
            return {"request": sent, "status": status, "sse": frames}
        response = httpx.post(
            url, json=sent, headers=self.headers if headers is None else headers,
            timeout=self.timeout,
        )
        return {"request": sent, "status": response.status_code, "json": response.json()}


# -- llama-server ------------------------------------------------------------------


def _llamacpp_version(server: Server) -> tuple[str, str]:
    """``(server_version, model)`` from ``/props``."""
    props = server.get(f"{server.root}/props").json()
    build = str(props.get("build_info") or "unknown")
    model = Path(str(props.get("model_path") or "")).name or str(props.get("model_alias") or "")
    return f"llama.cpp server {build}", model


def _message(answer: dict[str, Any]) -> dict[str, Any]:
    return ((answer.get("json") or {}).get("choices") or [{}])[0].get("message") or {}


def _llamacpp_recipes(server: Server) -> dict[str, Callable[[], Any]]:
    """
    llama-server's recipes. Most of them are the OpenAI-compatible route's,
    and ``_vllm_recipes`` reuses those (``COMPAT_RECIPES``).
    """
    from engine.llm.backend import (
        CONSTRAINT_PROBE_PROMPT,
        CONSTRAINT_PROBE_SCHEMA,
        _response_format,
    )

    def models() -> Any:
        return server.get(f"{server.base}/models").json()

    def props() -> Any:
        body = server.get(f"{server.root}/props").json()
        if body.get("model_path"):
            body["model_path"] = Path(str(body["model_path"])).name
        return body

    def health() -> Any:
        response = server.get(f"{server.root}/health")
        if response.status_code != 200:
            raise Refused(f"/health answered {response.status_code}, not 200")
        return response.json()

    def not_a_route() -> Any:
        response = server.get(f"{server.root}/no-such-route")
        if response.status_code != 404:
            raise Refused(f"an unserved route answered {response.status_code}, not 404")
        return response.json()

    def chat() -> Any:
        answer = server.chat({"messages": QUESTION, "max_tokens": ROOMY})
        if not _message(answer).get("content"):
            raise Refused("no content: raise ROOMY or load a smaller reasoning model")
        return answer

    def chat_stream_thinking() -> Any:
        answer = server.chat({
            "messages": QUESTION, "max_tokens": ROOMY, "stream": True,
            "stream_options": {"include_usage": True},
        })
        deltas = [
            (f["data"].get("choices") or [{}])[0].get("delta") or {}
            for f in answer.get("sse", []) if isinstance(f["data"], dict)
        ]
        # llama-server names the channel reasoning_content; recent vLLM names
        # it reasoning (engine/llm/client.py::extract_reasoning reads both).
        if not any(d.get("reasoning_content") or d.get("reasoning") for d in deltas):
            raise Refused("the stream carried no reasoning channel: load a reasoning model")
        return answer

    def chat_json_schema() -> Any:
        # The `constraint_won` probe, as backend._probe_constraint_won sends it.
        answer = server.chat({
            "messages": [{"role": "user", "content": CONSTRAINT_PROBE_PROMPT}],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": _response_format(dict(CONSTRAINT_PROBE_SCHEMA)),
        })
        return answer

    def chat_reasoning_off() -> Any:
        answer = server.chat({"messages": QUESTION, "max_tokens": ROOMY, **THINKING_OFF})
        message = _message(answer)
        if message.get("reasoning_content") or "</think>" in str(message.get("content") or ""):
            raise Refused(
                "the model thought with enable_thinking false: this recipe needs a "
                "template that honours it (a hybrid Qwen3); try chat_patch_ignored"
            )
        return answer

    def chat_patch_ignored() -> Any:
        answer = server.chat({"messages": QUESTION, "max_tokens": ROOMY, **THINKING_OFF})
        if "</think>" not in str(_message(answer).get("content") or ""):
            raise Refused(
                "no </think> in the content: this recipe needs a template that "
                "ignores enable_thinking (Qwen3-4B-Thinking-2507's)"
            )
        return answer

    def chat_stream_patch_ignored() -> Any:
        answer = server.chat({
            "messages": QUESTION, "max_tokens": ROOMY, "stream": True,
            "stream_options": {"include_usage": True}, **THINKING_OFF,
        })
        content = "".join(
            str(((f["data"].get("choices") or [{}])[0].get("delta") or {}).get("content") or "")
            for f in answer.get("sse", []) if isinstance(f["data"], dict)
        )
        if "</think>" not in content:
            raise Refused(
                "no </think> in the streamed content: this recipe needs a template "
                "that ignores enable_thinking (Qwen3-4B-Thinking-2507's)"
            )
        return answer

    def chat_inline_think() -> Any:
        # Needs a server started with --reasoning-format none.
        answer = server.chat({"messages": QUESTION, "max_tokens": ROOMY})
        message = _message(answer)
        if message.get("reasoning_content") or "</think>" not in str(message.get("content") or ""):
            raise Refused(
                "the server split the reasoning out itself: start it with "
                "--reasoning-format none, and load a reasoning model"
            )
        return answer

    def chat_json_object() -> Any:
        # Rung 2, as backend._probe_json_object sends it.
        from engine.llm.backend import OBJECT_PROBE_PROMPT

        answer = server.chat({
            "messages": [{"role": "user", "content": OBJECT_PROBE_PROMPT}],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        })
        try:
            parsed = json.loads(str(_message(answer).get("content") or "").strip())
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            raise Refused("the json_object answer is not a JSON object")
        return answer

    def chat_tool_calls() -> Any:
        answer = server.chat({
            "messages": [{"role": "user", "content": "Use the add tool to add 2 and 2."}],
            "max_tokens": ROOMY,
            "tools": [{
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                        "required": ["a", "b"],
                    },
                },
            }],
            "tool_choice": "auto",
        })
        if not _message(answer).get("tool_calls"):
            raise Refused("no tool_calls: start the server with --jinja")
        return answer

    def error_400() -> Any:
        answer = server.chat({
            "messages": QUESTION, "max_tokens": 16,
            "response_format": {"type": "not_a_format"},
        })
        if answer["status"] != 400:
            raise Refused(f"an unknown response_format answered {answer['status']}, not 400")
        return answer

    def error_401() -> Any:
        answer = server.chat(
            {"messages": QUESTION, "max_tokens": 16},
            headers={"Authorization": "Bearer not-the-key"},
        )
        if answer["status"] != 401:
            raise Refused(
                f"a wrong key answered {answer['status']}, not 401: start the server "
                "with --api-key to record this"
            )
        answer["request_headers"] = {"Authorization": "Bearer not-the-key"}
        return answer

    return {
        "models.json": models,
        "models_props.json": props,
        "health.json": health,
        "models_error.json": not_a_route,
        "chat.json": chat,
        "chat_stream_thinking.json": chat_stream_thinking,
        "chat_json_schema.json": chat_json_schema,
        "chat_reasoning_off.json": chat_reasoning_off,
        "chat_patch_ignored.json": chat_patch_ignored,
        "chat_stream_patch_ignored.json": chat_stream_patch_ignored,
        "chat_inline_think.json": chat_inline_think,
        "chat_json_object.json": chat_json_object,
        "chat_tool_calls.json": chat_tool_calls,
        "error_400.json": error_400,
        "error_401.json": error_401,
    }


# -- vLLM --------------------------------------------------------------------------
#
# vLLM serves the same OpenAI-compatible chat route llama-server does, so its
# chat recipes are llama-server's (COMPAT_RECIPES), sent with vLLM's own row's
# patch (the same body). What differs is around the route: the version is
# GET /version, /health answers 200 with an EMPTY body (written as a canned
# answer, {"status", "text"}), there is no /props, and the thinking channel
# needs --reasoning-parser: a server started with it records the split
# recipes, one started without it the inline ones (``*_live``, beside the
# authored ``chat_stream_inline_think.json`` the tests' [IMAGE:] case needs).

#: llama-server's recipes vLLM shares: the OpenAI-compatible chat route.
COMPAT_RECIPES = (
    "models.json",
    "chat.json",
    "chat_stream_thinking.json",
    "chat_json_schema.json",
    "chat_reasoning_off.json",
    "chat_json_object.json",
    "chat_tool_calls.json",
    "error_400.json",
    "error_401.json",
)


def _vllm_version(server: Server) -> tuple[str, str]:
    """``(server_version, model)`` from ``/version`` and the model list."""
    version = server.get(f"{server.root}/version").json().get("version", "unknown")
    listed = server.get(f"{server.base}/models").json().get("data") or [{}]
    return f"vLLM {version}", str(listed[0].get("id") or "")


def _vllm_recipes(server: Server) -> dict[str, Callable[[], Any]]:
    if dict(PROVIDERS["vllm"].reasoning_off.value) != THINKING_OFF:
        raise SystemExit("vLLM's reasoning-off patch is not llama-server's: give it its own recipes")
    shared = _llamacpp_recipes(server)

    def version() -> Any:
        return server.get(f"{server.root}/version").json()

    def health() -> Any:
        response = server.get(f"{server.root}/health")
        if response.status_code != 200:
            raise Refused(f"/health answered {response.status_code}, not 200")
        return {"status": response.status_code, "text": response.text}

    def error_404() -> Any:
        # A model the server does not serve: vLLM's error body, as it sends one.
        answer = server.chat({"model": "no-such-model", "messages": QUESTION, "max_tokens": 16})
        if answer["status"] != 404:
            raise Refused(f"an unserved model answered {answer['status']}, not 404")
        return answer

    def chat_inline_think() -> Any:
        # Needs a server started WITHOUT --reasoning-parser.
        answer = server.chat({"messages": QUESTION, "max_tokens": ROOMY})
        message = _message(answer)
        if message.get("reasoning_content") or message.get("reasoning") or (
            "</think>" not in str(message.get("content") or "")
        ):
            raise Refused("the server split the reasoning out itself: start it without --reasoning-parser")
        return answer

    def chat_stream_inline_think() -> Any:
        answer = server.chat({
            "messages": QUESTION, "max_tokens": ROOMY, "stream": True,
            "stream_options": {"include_usage": True},
        })
        content = "".join(
            str(((f["data"].get("choices") or [{}])[0].get("delta") or {}).get("content") or "")
            for f in answer.get("sse", []) if isinstance(f["data"], dict)
        )
        if "</think>" not in content:
            raise Refused("no </think> in the streamed content: start it without --reasoning-parser")
        return answer

    from engine.llm.backend import (
        CONSTRAINT_PROBE_PROMPT,
        CONSTRAINT_PROBE_SCHEMA,
        OBJECT_PROBE_PROMPT,
        _response_format,
    )

    def probe(prompt: str, response_format: dict[str, Any], *, off: bool) -> dict[str, Any]:
        # The probes as backend._probe_request sends them: reasoning off
        # (v0.19.0 T8), so the patch rides with the grammar.
        return server.chat({
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": response_format,
            **(THINKING_OFF if off else {}),
        })

    def chat_json_schema() -> Any:
        answer = probe(CONSTRAINT_PROBE_PROMPT, _response_format(dict(CONSTRAINT_PROBE_SCHEMA)), off=True)
        if json.loads(str(_message(answer).get("content") or "null")) != {"answer": "yes"}:
            raise Refused("the grammar did not beat the prompt")
        return answer

    def chat_json_schema_thinking() -> Any:
        # The same grammar, thinking ON and room for it: vLLM lets the model
        # think first and binds the grammar to the answer after it.
        answer = server.chat({
            "messages": [{"role": "user", "content": CONSTRAINT_PROBE_PROMPT}],
            "temperature": 0.0,
            "max_tokens": ROOMY,
            "response_format": _response_format(dict(CONSTRAINT_PROBE_SCHEMA)),
        })
        message = _message(answer)
        if not (message.get("reasoning") or message.get("reasoning_content")):
            raise Refused("no reasoning: this recipe needs a reasoning model, thinking on")
        return answer

    def chat_json_object() -> Any:
        answer = probe(OBJECT_PROBE_PROMPT, {"type": "json_object"}, off=True)
        try:
            parsed = json.loads(str(_message(answer).get("content") or "").strip())
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            raise Refused("the json_object answer is not a JSON object")
        return answer

    def chat_json_object_starved() -> Any:
        # The json_object probe with thinking ON at the probe's 200 tokens:
        # the cap is spent thinking before the grammar is reached.
        answer = probe(OBJECT_PROBE_PROMPT, {"type": "json_object"}, off=False)
        choice = ((answer.get("json") or {}).get("choices") or [{}])[0]
        if choice.get("finish_reason") != "length" or _message(answer).get("content"):
            raise Refused("the probe was not starved by its thinking")
        return answer

    recipes: dict[str, Callable[[], Any]] = {name: shared[name] for name in COMPAT_RECIPES}
    recipes.update({
        "chat_json_schema.json": chat_json_schema,
        "chat_json_schema_thinking.json": chat_json_schema_thinking,
        "chat_json_object.json": chat_json_object,
        "chat_json_object_starved.json": chat_json_object_starved,
        "version.json": version,
        "health.json": health,
        "error_404.json": error_404,
        "chat_inline_think_live.json": chat_inline_think,
        "chat_stream_inline_think_live.json": chat_stream_inline_think,
    })
    return recipes


# -- Ollama ------------------------------------------------------------------------
#
# Ollama's discovery bodies are written as bodies, like llama-server's; its
# JSON chat answers as canned answers with their request; its STREAMS as the
# NDJSON bytes themselves (``.ndjson``, what ``tests/test_llm_ollama.py::ndjson``
# serves), their request named here, in the recipe. /api/show's ``license``
# and ``modelfile`` are dropped: the first is long and not ours, the second
# names the local blob's path.

#: A tool the chat_tool_calls recipe offers (tests/test_llm_ollama.py's).
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "The weather in a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
}
#: The context every recorded /api/chat request asks for (the engine always
#: sends one; ``llm.context_tokens``'s default).
NUM_CTX = 8192


def _ollama_version(server: Server) -> str:
    return f"Ollama {server.get(f'{server.root}/api/version').json().get('version', 'unknown')}"


def _ollama_models(server: Server) -> tuple[str, str]:
    """``(thinker, plain)``: a chat model /api/show lists ``thinking`` for, and one it does not."""
    thinker = plain = ""
    for entry in server.get(f"{server.root}/api/tags").json().get("models", []):
        name = str(entry.get("name") or entry.get("model") or "")
        caps = _show(server, name).get("capabilities") or []
        if "completion" not in caps:
            continue
        if "thinking" in caps and not thinker:
            thinker = name
        elif "thinking" not in caps and not plain:
            plain = name
    return thinker, plain


def _show(server: Server, name: str) -> dict[str, Any]:
    body = httpx.post(
        f"{server.root}/api/show", json={"model": name}, headers=server.headers,
        timeout=server.timeout,
    ).json()
    body.pop("license", None)
    body.pop("modelfile", None)
    return body


def _ollama_chat(server: Server, body: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{server.root}/api/chat", json=body, headers=server.headers, timeout=server.timeout
    )
    return {"request": body, "status": response.status_code, "json": response.json()}


def _ollama_stream(server: Server, body: dict[str, Any]) -> str:
    lines: list[str] = []
    with httpx.stream(
        "POST", f"{server.root}/api/chat", json=body, headers=server.headers,
        timeout=server.timeout,
    ) as response:
        if response.status_code >= 400:
            response.read()
            raise Refused(f"the stream answered {response.status_code}: {response.text[:200]}")
        for line in response.iter_lines():
            if line.strip():
                lines.append(line)
    return "\n".join(lines) + "\n"


def _ollama_recipes(server: Server) -> dict[str, Callable[[], Any]]:
    from engine.llm.backend import CONSTRAINT_PROBE_PROMPT, CONSTRAINT_PROBE_SCHEMA

    thinker, plain = _ollama_models(server)

    def need(model: str, kind: str) -> str:
        if not model:
            raise Refused(f"no {kind} model is installed")
        return model

    def ask(model: str, **extra: Any) -> dict[str, Any]:
        options = {"num_ctx": NUM_CTX, "temperature": 0.0}
        options.update(extra.pop("options", {}))
        return {"model": model, "messages": QUESTION, "stream": False, "options": options, **extra}

    def message(answer: dict[str, Any]) -> dict[str, Any]:
        return (answer.get("json") or {}).get("message") or {}

    def version() -> Any:
        return server.get(f"{server.root}/api/version").json()

    def tags() -> Any:
        return server.get(f"{server.root}/api/tags").json()

    def ps() -> Any:
        # Load the thinker at the engine's num_ctx first, so /api/ps shows what
        # that request loaded (the checklist: does it report num_ctx?).
        httpx.post(
            f"{server.root}/api/chat",
            json=ask(need(thinker, "thinking"), think=False, options={"num_predict": 4}),
            headers=server.headers,
            timeout=server.timeout,
        )
        return server.get(f"{server.root}/api/ps").json()

    def show_thinker() -> Any:
        return _show(server, need(thinker, "thinking"))

    def show_plain() -> Any:
        return _show(server, need(plain, "non-thinking"))

    def show_missing() -> Any:
        response = httpx.post(
            f"{server.root}/api/show", json={"model": "no-such-model:latest"},
            headers=server.headers, timeout=server.timeout,
        )
        if response.status_code != 404:
            raise Refused(f"an unknown model answered {response.status_code}, not 404")
        return response.json()

    def chat() -> Any:
        answer = _ollama_chat(server, ask(need(thinker, "thinking"), think=True,
                                          options={"num_predict": ROOMY}))
        if not message(answer).get("thinking") or not message(answer).get("content"):
            raise Refused("expected both thinking and content")
        return answer

    def chat_think_off() -> Any:
        answer = _ollama_chat(server, ask(need(thinker, "thinking"), think=False,
                                          options={"num_predict": ROOMY}))
        if message(answer).get("thinking") or "</think>" in str(message(answer).get("content")):
            raise Refused("think: false still thought")
        return answer

    def chat_think_ignored() -> Any:
        answer = _ollama_chat(server, ask(need(thinker, "thinking"), think=False,
                                          options={"num_predict": ROOMY}))
        if "</think>" not in str(message(answer).get("content")):
            raise Refused("think: false was honoured: this recipe needs a model that ignores it")
        return answer

    def stream_think_ignored() -> Any:
        text = _ollama_stream(server, {**ask(need(thinker, "thinking"), think=False,
                                             options={"num_predict": ROOMY}), "stream": True})
        content = "".join(
            str((json.loads(line).get("message") or {}).get("content") or "")
            for line in text.splitlines() if line.strip()
        )
        if "</think>" not in content:
            raise Refused("think: false was honoured: this recipe needs a model that ignores it")
        return text

    def chat_json_schema() -> Any:
        # The constraint_won probe, as the engine sends it on Ollama: the
        # schema as `format`, and `think` as the big profile's `on` -- the
        # checklist's think + format together.
        return _ollama_chat(server, {
            "model": need(thinker, "thinking"),
            "messages": [{"role": "user", "content": CONSTRAINT_PROBE_PROMPT}],
            "stream": False,
            "format": dict(CONSTRAINT_PROBE_SCHEMA),
            "think": True,
            "options": {"num_ctx": NUM_CTX, "temperature": 0.0, "num_predict": ROOMY},
        })

    def chat_starved() -> Any:
        answer = _ollama_chat(server, ask(need(thinker, "thinking"), think=True,
                                          options={"num_predict": 8}))
        if (answer.get("json") or {}).get("done_reason") != "length":
            raise Refused("did not stop at the cap")
        return answer

    def chat_error_think() -> Any:
        answer = _ollama_chat(server, ask(need(plain, "non-thinking"), think=True))
        if answer["status"] != 400:
            raise Refused(f"think on {plain} answered {answer['status']}, not 400")
        return answer

    def chat_tool_calls() -> Any:
        answer = _ollama_chat(server, {
            "model": need(thinker, "thinking"),
            "messages": [{"role": "user", "content": "What is the weather in Tallowmere? Use the tool."}],
            "stream": False,
            "tools": [WEATHER_TOOL],
            "think": False,
            "options": {"num_ctx": NUM_CTX, "temperature": 0.0},
        })
        if not message(answer).get("tool_calls"):
            raise Refused("no tool_calls")
        return answer

    def stream_thinking() -> Any:
        return _ollama_stream(server, {**ask(need(thinker, "thinking"), think=True,
                                              options={"num_predict": ROOMY}), "stream": True})

    def stream_starved() -> Any:
        return _ollama_stream(server, {**ask(need(thinker, "thinking"), think=True,
                                              options={"num_predict": 8}), "stream": True})

    return {
        "version.json": version,
        "models_tags_live.json": tags,
        "models_ps_live.json": ps,
        "models_show_thinker_live.json": show_thinker,
        "models_show_plain_live.json": show_plain,
        "models_error.json": show_missing,
        "chat.json": chat,
        "chat_think_off.json": chat_think_off,
        "chat_think_ignored.json": chat_think_ignored,
        "chat_stream_think_ignored.ndjson": stream_think_ignored,
        "chat_json_schema.json": chat_json_schema,
        "chat_starved.json": chat_starved,
        "chat_error_think.json": chat_error_think,
        "chat_tool_calls.json": chat_tool_calls,
        "chat_stream_thinking.ndjson": stream_thinking,
        "chat_stream_starved.ndjson": stream_starved,
    }


def _record_loading(server: Server, seconds: float) -> Optional[Any]:
    """Poll ``/health`` for a 503 while a model loads; its body, or None."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            response = server.get(f"{server.root}/health")
        except httpx.HTTPError:
            time.sleep(0.2)
            continue
        if response.status_code == 503:
            return response.json()
        if response.status_code == 200:
            return None
        time.sleep(0.2)
    return None


# -- provenance --------------------------------------------------------------------


#: What a scrubbed secret is written as.
REDACTED = "<redacted>"


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    """``text`` with every non-empty secret in ``secrets`` replaced by ``REDACTED``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _write(path: Path, value: Any, secrets: tuple[str, ...] = ()) -> None:
    """
    JSON, or -- for an NDJSON stream -- the text as the server sent it, with
    each of ``secrets`` (the operator's real API key) scrubbed out first: a
    fixture is committed, and a server that echoed the key back would
    otherwise put it in git.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(_scrub(text, secrets), encoding="utf-8", newline="\n")


#: What a recipe needed of the server beyond ``--jinja`` and a model, written
#: into its provenance row so the fixture says how to make it again.
NOTES: dict[str, str] = {
    "health_loading.json": "polled while the server loaded its model (--wait-for-load)",
    "chat_reasoning_off.json": "a template that honours enable_thinking",
    "chat_patch_ignored.json": "a template that opens <think> whatever enable_thinking says",
    "chat_stream_patch_ignored.json": "a template that opens <think> whatever enable_thinking says",
    "chat_inline_think.json": "server started with --reasoning-format none",
    "error_401.json": "server started with --api-key; sent a wrong key",
    "models_ps_live.json": "after a request that sent num_ctx 8192",
    "models_show_thinker_live.json": "license and modelfile dropped",
    "models_show_plain_live.json": "license and modelfile dropped; a GGUF imported by a Modelfile",
    "chat_error_think.json": "think: true to a model /api/show lists no thinking for",
    "chat_json_schema.json": (
        "a format + think: true request (the pre-T8-fix probe shape; the probe now "
        "sends think: false)"
    ),
    "chat_stream_thinking.ndjson": "stream: true, think: true; the request is the recipe's",
    "chat_think_ignored.json": "think: false to a model whose template opens <think> anyway",
    "chat_stream_think_ignored.ndjson": (
        "stream: true, think: false, to a model whose template opens <think> anyway; "
        "the request is the recipe's"
    ),
    "chat_stream_starved.ndjson": "stream: true, think: true, num_predict 8; the request is the recipe's",
    "chat_inline_think_live.json": "server started without --reasoning-parser",
    "chat_stream_inline_think_live.json": "server started without --reasoning-parser",
    "health.json": "a canned answer: /health's body is empty",
    "error_404.json": "a model the server does not serve",
}
#: Notes that differ by provider (the same file name, another server's recipe).
PROVIDER_NOTES: dict[str, dict[str, str]] = {
    "vllm": {
        "error_401.json": "server started with --api-key; sent a wrong key",
        "chat_tool_calls.json": "server started with --enable-auto-tool-choice --tool-call-parser hermes",
        "chat_json_schema.json": "the constraint_won probe as the engine sends it, the patch on",
        "chat_json_object.json": "the json_object probe as the engine sends it, the patch on",
        "chat_json_schema_thinking.json": "the probe's grammar with thinking on: it thinks, then answers in the grammar",
        "chat_json_object_starved.json": "the json_object probe with thinking on, at its 200-token cap",
    },
}

#: Ollama recipes answered by its plain (no-``thinking``) model, and by the
#: server as a whole.
OLLAMA_PLAIN_RECIPES = ("models_show_plain_live.json", "chat_error_think.json")
OLLAMA_SERVER_RECIPES = ("version.json", "models_tags_live.json", "models_error.json")
#: ...and by every model loaded at the time.
OLLAMA_LOADED_RECIPES = ("models_ps_live.json",)


def _row_lines(key: str, provider: str, version: str, model: str, today: str) -> list[str]:
    lines = [
        f"  {key}:",
        f"    provider: {provider}",
        f"    server_version: {json.dumps(version)}",
        "    origin: recorded",
        f"    model: {json.dumps(model)}",
        f"    recorded: \"{today}\"",
    ]
    name = key.split("/", 1)[1]
    provider_notes = PROVIDER_NOTES.get(provider, {})
    note = provider_notes[name] if name in provider_notes else NOTES.get(name)
    if note:
        lines.append(f"    note: {json.dumps(note)}")
    return lines


def _update_provenance(provider: str, written: dict[str, str], version: str) -> None:
    """
    Rewrite the rows of ``written`` (file -> model) as recorded, in place.

    Edited as text, row by row, so the file's comments survive: an existing
    row's lines are replaced where they stand, a new row goes after the
    provider's last one.
    """
    lines = PROVENANCE.read_text(encoding="utf-8").splitlines()
    today = _dt.date.today().isoformat()

    def row_span(key: str) -> Optional[tuple[int, int]]:
        for i, line in enumerate(lines):
            if line == f"  {key}:":
                end = i + 1
                while end < len(lines) and lines[end].startswith("    "):
                    end += 1
                return i, end
        return None

    for name, model in written.items():
        key = f"{provider}/{name}"
        new = _row_lines(key, provider, version, model, today)
        span = row_span(key)
        if span is not None:
            lines[span[0]:span[1]] = new
            continue
        last = max(
            (row_span(line.strip()[:-1]) or (0, 0))[1]
            for line in lines
            if line.startswith(f"  {provider}/") and line.endswith(":")
        ) if any(line.startswith(f"  {provider}/") for line in lines) else len(lines)
        lines[last:last] = new
    PROVENANCE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))  # still YAML, or raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--provider", required=True, choices=["llamacpp", "ollama", "vllm"])
    parser.add_argument("--config", help="a YAML file read as the local config layer")
    parser.add_argument("--only", help="comma-separated fixture names (without .json)")
    parser.add_argument(
        "--wait-for-load", type=float, default=0.0, metavar="SECONDS",
        help="first poll /health that long for a 503 while the model loads "
             "(start the server just before), recording health_loading.json",
    )
    parser.add_argument(
        "--allow-lmstudio-origin", action="store_true",
        help="record from a server at LM Studio's default address anyway "
             "(refused otherwise: that is the owner's LM Studio)",
    )
    args = parser.parse_args(argv)

    _use_config(args.config)
    server = Server()
    if server.provider.name != args.provider:
        print(f"the config names {server.provider.name!r}, not {args.provider!r}")
        return 2
    from engine.llm.routes import origin

    if origin(server.base) == origin(str(PROVIDERS["lmstudio"].default_base_url.value)) and (
        not args.allow_lmstudio_origin
    ):
        print(
            f"{server.base} is LM Studio's default address: this script does not "
            "record from the owner's LM Studio unless asked (--allow-lmstudio-origin)"
        )
        return 2

    written: dict[str, str] = {}
    directory = FIXTURES / args.provider
    if args.wait_for_load:
        loading = _record_loading(server, args.wait_for_load)
        if loading is None:
            print("health_loading.json: no 503 seen (was the model already loaded?)")
        else:
            _write(directory / "health_loading.json", loading, (server.api_key,))
            written["health_loading.json"] = ""
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline and server.get(f"{server.root}/health").status_code != 200:
                time.sleep(0.5)

    if args.provider == "ollama":
        version = _ollama_version(server)
        thinker, plain = _ollama_models(server)
        recipes = _ollama_recipes(server)
        models = {name: thinker for name in recipes}
        models.update({n: plain for n in OLLAMA_PLAIN_RECIPES})
        models.update({n: "every installed model" for n in OLLAMA_SERVER_RECIPES})
        models.update({n: "every loaded model" for n in OLLAMA_LOADED_RECIPES})
    elif args.provider == "vllm":
        version, model = _vllm_version(server)
        recipes = _vllm_recipes(server)
        models = {name: model for name in recipes}
        models["version.json"] = "every served model"
    else:
        version, model = _llamacpp_version(server)
        recipes = _llamacpp_recipes(server)
        models = {name: model for name in recipes}
    stems = {name.rsplit(".", 1)[0]: name for name in recipes}
    wanted = (
        [stems.get(n.strip(), n.strip()) for n in args.only.split(",")] if args.only else list(recipes)
    )
    unknown = [n for n in wanted if n not in recipes]
    if unknown:
        print(f"no recipe named {unknown}; recipes: {sorted(recipes)}")
        return 2
    # Refuse before asking anything: a recipe that needs a model the server
    # does not have would otherwise be sent (and recorded) against a blank name.
    blank = [n for n in wanted if not models.get(n)]
    if blank:
        print(
            f"no model for {blank}: the server has no "
            + ("chat model /api/show lists thinking for, or none it does not"
               if args.provider == "ollama" else "model loaded")
            + "; install one or leave these out of --only"
        )
        return 2
    failed = 0
    for name in wanted:
        try:
            value = recipes[name]()
        except Refused as exc:
            print(f"{name}: NOT written -- {exc}")
            failed += 1
            continue
        _write(directory / name, value, (server.api_key,))
        written[name] = models[name]
        print(f"{name}: recorded ({models[name]})")
    if "health_loading.json" in written:
        written["health_loading.json"] = next(iter(models.values()), "")
    if written:
        _update_provenance(args.provider, written, version)
        print(f"PROVENANCE.yaml: {len(written)} row(s) now recorded against {version}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
