"""
The LM Studio golden: what v0.18.0 sends, and what it makes of the answers.

WHY IT EXISTS. v0.19.0 makes the engine model-server agnostic, and its first
invariant is that nothing changes for LM Studio. "Nothing changes" has to be a
thing a test can check, so this module records, from the untouched v0.18.0
code, the exact requests each LM Studio path sends and the parse of each canned
answer -- and ``tests/test_llm_golden_lmstudio.py`` replays every scenario and
asserts both are equal to the recording. The fixtures are recorded ONCE, and a
later change that needs one re-recorded has found a regression, or a spec
decision to take back to the owner (the plan's Global Constraints).

HOW A SCENARIO RUNS. Four things are pinned, so the recording is the same on
every machine:

  * CONFIG, through the real layers. ``engine.config._CONFIG_DIR`` points at a
    temp directory holding a ``local.yaml`` this module writes, and
    ``_DEFAULT_PATH`` at the repository's real ``config/default.yaml`` (so a
    later task's edits to it ARE exercised). ``CLOCKWORK_LLM_API_KEY``,
    ``LMSTUDIO_API_KEY`` and ``CLOCKWORK_ENV`` are deleted from the
    environment. The key is therefore ``golden-test-key`` everywhere, whether
    or not a machine holds a ``lmstudio.txt``. ``set_overlay`` is not used.
    Two variants: ``shipped`` (the key alone) and ``legacy`` (a v0.18-shaped
    ``lmstudio:`` block: a moved ``base_url``, a big-profile temperature and a
    ``ttl_seconds``).
  * THE WIRE, through ``tests/llm_wire.py``: every request is captured and
    answered from the scenario's canned list. Nothing opens a socket.
  * THE NATIVE PROBE. ``NativeClient.is_available`` is set per scenario: the
    real method (which then asks the wire) or ``False``, the conftest default.
    The real method is kept here from import time, before any guard pins it.
  * THE CLOCK. ``time.perf_counter`` answers a constant for the length of a
    scenario, so every latency is 0 -- including the one ``chat_probe`` writes
    into its detail text. ``time.monotonic`` is left real: deadline loops
    elsewhere in the engine would spin forever on a frozen one.

WHAT IS PINNED per scenario: the request list (method, URL, the headers the
engine sends -- ``Authorization``, ``content-type``, ``accept``; the ones
httpx's transport authors are dropped, see ``TRANSPORT_HEADERS`` -- and the
body as canonical JSON), the canned answers,
and the parse: the scenario's own result, plus every ``LMSResponse`` the
backend's ``chat`` / ``chat_stream`` returned during it (content, reasoning,
finish reason, token counts, tool calls, stats) and, for a stream, the
``LMSStreamEvent`` sequence. The backend is spied at its public methods; for a
stream the spy adds an ``on_event`` collector, which sends nothing and changes
no request. Latencies and the compat stream's random ``chat.end`` id are the
only values normalised.

RECORDING (on v0.18.0 code only; see above)::

    .venv\\Scripts\\python.exe -m tests.llm_golden record

It refuses to overwrite a recording unless given ``--overwrite``.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import importlib.util
import io
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
import yaml

from engine.llm.lmstudio_native import NativeClient
from engine.scenes import default_state as _default_state
from tests.llm_wire import canonical_body, canonical_json, wire

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "llm" / "golden_lmstudio"

#: The fixed key every variant writes. Recorded in every Authorization header.
API_KEY = "golden-test-key"

#: Headers httpx's transport sets, not the engine: they move with an httpx
#: release or an installed compression library (`brotli`, `zstandard`), never
#: with an engine change, so the golden neither records nor compares them.
#: `accept` is deliberately NOT here (controller's ruling, fix round 1): `*/*`
#: is stable across httpx releases, and an engine that starts sending
#: `Accept: text/event-stream` to LM Studio has changed its request.
TRANSPORT_HEADERS = frozenset(
    {"user-agent", "accept-encoding", "connection", "host", "content-length"}
)


def engine_headers(request: dict[str, Any]) -> dict[str, Any]:
    """A captured request, less the headers httpx's transport authors."""
    out = dict(request)
    out["headers"] = {
        k: v for k, v in dict(request["headers"]).items() if k not in TRANSPORT_HEADERS
    }
    return out


#: Removed from the environment for every scenario, so no machine's own key,
#: environment layer or future provider key reaches the recording.
ENV_KEYS = ("CLOCKWORK_LLM_API_KEY", "LMSTUDIO_API_KEY", "CLOCKWORK_ENV")

#: The temp ``config/local.yaml`` of each variant, before a scenario's extras.
VARIANTS: dict[str, dict[str, Any]] = {
    "shipped": {"lmstudio": {"api_key": API_KEY}},
    # A v0.18-shaped `lmstudio:` block, as an owner's local.yaml holds one.
    "legacy": {
        "lmstudio": {
            "api_key": API_KEY,
            "base_url": "http://127.0.0.1:1235/v1",
            "profiles": {"big": {"temperature": 0.7}},
            "ttl_seconds": 600,
        }
    },
}

#: Kept before any fixture can pin them: ``tests/conftest.py`` replaces the
#: native probe and the summarizer for every test, and a scenario about either
#: needs the real one back.
_REAL_NATIVE_IS_AVAILABLE = NativeClient.__dict__["is_available"]
_REAL_SUMMARIZER_FN = _default_state._summarizer_fn
# These fail if this module is first imported INSIDE a test body, where the
# conftest guard has already pinned both: import it at module level instead.
assert _REAL_NATIVE_IS_AVAILABLE.__name__ == "is_available", "imported under a pin"
assert _REAL_SUMMARIZER_FN.__name__ == "_summarizer_fn", "imported under a pin"


# ---------------------------------------------------------------------------
# Canned answers
# ---------------------------------------------------------------------------

NARRATOR = "golden/narrator-26b"
UTILITY = "golden/utility-8b"
PLAIN = "golden/plain-3b"


def _llm(
    key: str,
    arch: str,
    *,
    loaded_ctx: int,
    max_ctx: int,
    tools: bool,
    reasoning: Optional[dict[str, Any]],
) -> dict[str, Any]:
    capabilities: dict[str, Any] = {"vision": False, "trained_for_tool_use": tools}
    if reasoning is not None:
        capabilities["reasoning"] = reasoning
    return {
        "type": "llm",
        "publisher": "golden",
        "key": key,
        "display_name": key.split("/", 1)[1],
        "architecture": arch,
        "quantization": {"name": "Q4_K_M", "bits_per_weight": 4.8},
        "size_bytes": 4_000_000_000,
        "params_string": "8B",
        "loaded_instances": [{"id": key, "config": {"context_length": loaded_ctx}}],
        "max_context_length": max_ctx,
        "format": "gguf",
        "capabilities": capabilities,
    }


_EMBEDDER = {
    "type": "embedding",
    "publisher": "golden",
    "key": "golden/embedder",
    "display_name": "embedder",
    "architecture": "nomic-bert",
    "quantization": {"name": "F16", "bits_per_weight": 16},
    "size_bytes": 270_000_000,
    "params_string": "137M",
    "loaded_instances": [],
    "max_context_length": 2048,
    "format": "gguf",
    "capabilities": {},
}

#: ``GET /api/v1/models``. `big` binds the narrator (the only tool-trained
#: model), `small` and `draft` the utility model (a reasoning block that
#: defaults off, so it ranks as non-reasoning and accepts `reasoning: off`).
MODELS = {
    "models": [
        _llm(
            NARRATOR,
            "gemma4",
            loaded_ctx=16384,
            max_ctx=131072,
            tools=True,
            reasoning={"allowed_options": ["off", "on"], "default": "on"},
        ),
        _llm(
            UTILITY,
            "llama",
            loaded_ctx=8192,
            max_ctx=32768,
            tools=False,
            reasoning={"allowed_options": ["off", "on"], "default": "off"},
        ),
        _EMBEDDER,
    ]
}

#: The same server with a utility model that publishes NO reasoning block --
#: the model the measured-room retry exists for.
MODELS_NO_KNOB = {
    "models": [
        MODELS["models"][0],
        _llm(PLAIN, "lfm2", loaded_ctx=8192, max_ctx=32768, tools=False, reasoning=None),
        _EMBEDDER,
    ]
}


def _models(payload: dict[str, Any] = MODELS) -> dict[str, Any]:
    return {"status": 200, "json": copy.deepcopy(payload)}


#: ``POST /api/v1/chat {}`` on a server that serves the route.
NATIVE_PROBE_400 = {
    "status": 400,
    "json": {
        "error": {
            "type": "invalid_request",
            "message": "'input' is required",
            "param": "input",
        }
    },
}

#: The same probe against a server that does not.
NATIVE_PROBE_404 = {"status": 404, "text": "Cannot POST /api/v1/chat"}


def _compat_json(
    content: str,
    *,
    model: str = NARRATOR,
    reasoning: str = "",
    finish: str = "stop",
    prompt_tokens: int = 812,
    completion_tokens: int = 431,
    reasoning_tokens: Optional[int] = 120,
    ident: str = "chatcmpl-golden-1",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if reasoning_tokens is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return {
        "status": 200,
        "json": {
            "id": ident,
            "object": "chat.completion",
            "created": 1767225600,
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": usage,
        },
    }


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _compat_sse(
    content: str,
    *,
    reasoning: str = "",
    finish: str = "stop",
    model: str = NARRATOR,
    prompt_tokens: int = 1204,
    completion_tokens: int = 612,
    reasoning_tokens: int = 188,
) -> dict[str, Any]:
    """An OpenAI-compatible stream: reasoning deltas, content deltas, usage."""

    def chunk(delta: dict[str, Any], finish_reason: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": {
                "id": "chatcmpl-golden-stream",
                "object": "chat.completion.chunk",
                "created": 1767225600,
                "model": model,
                "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish_reason}
                ],
            }
        }

    frames = [chunk({"role": "assistant", "content": ""})]
    frames += [chunk({"reasoning_content": part}) for part in _chunks(reasoning, 48)]
    frames += [chunk({"content": part}) for part in _chunks(content, 40)]
    frames.append(chunk({}, finish))
    frames.append(
        {
            "data": {
                "id": "chatcmpl-golden-stream",
                "object": "chat.completion.chunk",
                "created": 1767225600,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
                },
            }
        }
    )
    frames.append({"data": "[DONE]"})
    return {"status": 200, "sse": frames}


def _native_result(
    content: str,
    *,
    model: str,
    reasoning: str = "",
    total: int = 42,
    reasoning_tokens: int = 0,
    input_tokens: int = 120,
    ident: str = "resp_golden_native",
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if reasoning:
        output.append({"type": "reasoning", "content": reasoning})
    if content:
        output.append({"type": "message", "content": content})
    return {
        "model_instance_id": model,
        "output": output,
        "stats": {
            "input_tokens": input_tokens,
            "total_output_tokens": total,
            "reasoning_output_tokens": reasoning_tokens,
            "tokens_per_second": 41.5,
            "time_to_first_token_seconds": 0.25,
        },
        "response_id": ident,
    }


def _native_json(content: str, **kwargs: Any) -> dict[str, Any]:
    return {"status": 200, "json": _native_result(content, **kwargs)}


def _native_sse(
    content: str,
    *,
    model: str,
    reasoning: str = "",
    total: int = 640,
    reasoning_tokens: int = 210,
    tool_frames: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """LM Studio's native typed stream, ``event:`` and ``data:`` both present."""

    def frame(event: str, **data: Any) -> dict[str, Any]:
        return {"event": event, "data": {"type": event, **data}}

    frames = [
        frame("chat.start", model_instance_id=model),
        frame("prompt_processing.start"),
        frame("prompt_processing.progress", progress=1.0),
        frame("prompt_processing.end"),
    ]
    if reasoning:
        frames.append(frame("reasoning.start"))
        frames += [frame("reasoning.delta", content=p) for p in _chunks(reasoning, 48)]
        frames.append(frame("reasoning.end"))
    frames += list(tool_frames or [])
    if content:
        frames.append(frame("message.start"))
        frames += [frame("message.delta", content=p) for p in _chunks(content, 40)]
        frames.append(frame("message.end"))
    frames.append(
        frame(
            "chat.end",
            result=_native_result(
                content,
                model=model,
                reasoning=reasoning,
                total=total,
                reasoning_tokens=reasoning_tokens,
                input_tokens=1204,
                ident="resp_golden_stream",
            ),
        )
    )
    return {"status": 200, "sse": frames}


#: A storyteller turn envelope, as the grammar makes the model write it.
ENVELOPE = json.dumps(
    {
        "narration": (
            "The path east narrows between birches gone silver in the dusk. "
            "Somewhere ahead a clock is ticking where no clock should be, slow "
            "and patient, and the moss underfoot carries the marks of boots that "
            "came this way and did not come back. The trees lean in to listen."
        ),
        "choices": [
            {"id": "a", "text": "Follow the ticking", "hint": "risky"},
            {"id": "b", "text": "Study the boot marks", "hint": "safe"},
            {"id": "c", "text": "Turn back to the clearing", "hint": "unknown"},
        ],
        "ledger_delta": {"facts": [{"text": "A clock ticks in the eastern wood."}]},
    }
)

#: What a model with no grammar writes instead.
PROSE = (
    "The path east narrows between birches gone silver in the dusk. Somewhere "
    "ahead a clock is ticking. What do you do?"
)

REASONING = (
    "The player follows the path east. I should keep the tone uneasy, offer a "
    "risky lead and a safe one, and not resolve the clock yet."
)

#: The storyteller's messages. Fixed text rather than the prompt builder, so the
#: golden pins the model layer and not prompt wording. Two system blocks (the
#: native route joins them) and an assistant turn (it labels one).
STORY_MESSAGES = [
    {"role": "system", "content": "You narrate a golden-test story in the second person."},
    {"role": "system", "content": "WORLD STATE: dusk at the forest clearing; the east path is open."},
    {"role": "assistant", "content": "The wind turns. Something in the trees has noticed you."},
    {"role": "user", "content": "I follow the path east."},
]

UTILITY_MESSAGES = [
    {"role": "system", "content": "Answer in one short sentence."},
    {"role": "user", "content": "What season is it in the golden test?"},
]

#: A small schema for the probe scenarios; the turn scenarios use the real one.
SMALL_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}

PROBE_YES = _compat_json('{"ok": true}', completion_tokens=9, reasoning_tokens=0)
PROBE_NO = _compat_json("Sure. Yes, the server is fine.", completion_tokens=11, reasoning_tokens=0)


# ---------------------------------------------------------------------------
# Normalising what came back, for a fixture
# ---------------------------------------------------------------------------

_RANDOM_RESPONSE_ID = re.compile(r"^resp_[0-9a-f]{12}$")


def _plain(value: Any) -> Any:
    """Anything a scenario returns, as plain JSON-able data."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def response_dict(response: Any) -> dict[str, Any]:
    """An ``LMSResponse``, less its latency."""
    data = _plain(response)
    data.pop("latency_ms", None)
    if isinstance(data.get("stats"), dict):
        data["stats"].pop("latency_ms", None)
    return data


def event_dict(event: Any) -> dict[str, Any]:
    """An ``LMSStreamEvent``, less its latency and the compat stream's random id."""
    data = _plain(event)
    if isinstance(data.get("stats"), dict):
        data["stats"].pop("latency_ms", None)
    if _RANDOM_RESPONSE_ID.match(str(data.get("response_id") or "")):
        data["response_id"] = "resp_<random>"
    return data


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


def _reset_llm_state() -> None:
    """Drop every config-derived LLM singleton, the compat client included."""
    from engine.config import reset_config
    from engine.llm.client import reset_lms_client

    reset_config()  # profiles, registry, backend and lanes, via the reloaders
    reset_lms_client()  # not a reloader: it would keep the previous key


@contextlib.contextmanager
def pinned(
    variant: str,
    directory: Path,
    extra: Optional[dict[str, Any]] = None,
    *,
    native: bool = False,
) -> Iterator[pytest.MonkeyPatch]:
    """
    Run under the pinned config of ``variant``, plus a scenario's ``extra``.

    Args:
        variant: ``shipped`` or ``legacy``.
        directory: Stands in for ``config/``; ``local.yaml`` is written here.
        extra: Deep-merged over the variant's ``local.yaml``.
        native: Whether ``/api/v1/chat`` answers the availability probe. False
            is the conftest default and means no probe request is sent.
    """
    import engine.config as config

    local = config.deep_merge(VARIANTS[variant], extra or {})
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "local.yaml").write_text(
        yaml.safe_dump(local, sort_keys=True), encoding="utf-8"
    )
    patch = pytest.MonkeyPatch()
    try:
        for name in ENV_KEYS:
            patch.delenv(name, raising=False)
        patch.setattr(config, "_CONFIG_DIR", directory)
        patch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
        patch.setattr(
            NativeClient,
            "is_available",
            _REAL_NATIVE_IS_AVAILABLE if native else (lambda self: False),
        )
        # perf_counter only: it times every latency on the LLM path. monotonic
        # stays real, because deadline loops (engine/stack.py, the skills
        # server, comfy) would spin forever on a frozen one.
        patch.setattr(time, "perf_counter", lambda: 1000.0)
        _reset_llm_state()
        yield patch
    finally:
        try:
            _reset_llm_state()
        finally:
            patch.undo()
            _reset_llm_state()


class BackendSpy:
    """Every ``LMSResponse`` the backend returned, and each stream's events."""

    def __init__(self, patch: pytest.MonkeyPatch) -> None:
        from engine.llm.backend import LMStudioBackend

        self.calls: list[dict[str, Any]] = []
        real_chat = LMStudioBackend.chat
        real_stream = LMStudioBackend.chat_stream
        calls = self.calls

        def chat(self_: Any, messages: Any, **kwargs: Any) -> Any:
            result = real_chat(self_, messages, **kwargs)
            calls.append({"call": "chat", "response": response_dict(result)})
            return result

        def chat_stream(self_: Any, messages: Any, **kwargs: Any) -> Any:
            events: list[dict[str, Any]] = []
            outer = kwargs.get("on_event")

            def on_event(event: Any) -> None:
                events.append(event_dict(event))
                if outer is not None:
                    outer(event)

            kwargs["on_event"] = on_event
            result = yield from real_stream(self_, messages, **kwargs)
            calls.append(
                {"call": "chat_stream", "response": response_dict(result), "events": events}
            )
            return result

        patch.setattr(LMStudioBackend, "chat", chat)
        patch.setattr(LMStudioBackend, "chat_stream", chat_stream)


def _load_script(name: str, path: Path) -> Any:
    """A script as a module, reusing one already loaded from the same file."""
    loaded = sys.modules.get(name)
    if loaded is not None and Path(getattr(loaded, "__file__", "") or "") == path:
        return loaded
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """
    One recorded path.

    ``prepare`` runs under the pinned config but BEFORE the wire opens (building
    a game state sends nothing, and a request there would be a finding, not a
    fixture); ``run`` gets its result and runs with the wire open.
    """

    name: str
    about: str
    answers: tuple[dict[str, Any], ...]
    run: Callable[[Any], Any]
    prepare: Optional[Callable[[], Any]] = None
    story: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    native: bool = False


def _structured(mode: str) -> dict[str, Any]:
    return {"lmstudio": {"structured_output": mode}}


def _storyteller(seed: int) -> Callable[[], Any]:
    def prepare() -> Any:
        from engine.agents.storyteller import StorytellerAgent
        from engine.game.engine import GameEngine
        from engine.game.procgen import new_game_state

        return StorytellerAgent(GameEngine(new_game_state(seed=seed)))

    return prepare


def _turn(streamed: bool) -> Callable[[Any], Any]:
    """A storyteller turn through ``StorytellerAgent._infer``, the real caller."""

    def run(agent: Any) -> Any:
        deltas: list[str] = []
        generation = agent._infer(
            [dict(m) for m in STORY_MESSAGES],
            on_delta=deltas.append if streamed else None,
        )
        return {
            "generation": _plain(generation),
            "streamed": deltas,
            "last_reasoning": agent.last_reasoning,
        }

    return run


def _backend_chat(profile: str, **kwargs: Any) -> Callable[[Any], Any]:
    def run(_: Any) -> Any:
        from engine.llm.backend import get_backend

        result = get_backend().chat(
            [dict(m) for m in UTILITY_MESSAGES], profile=profile, **kwargs
        )
        return response_dict(result)

    return run


def _probe(_: Any) -> Any:
    from engine.llm.backend import get_backend

    response_format = get_backend().structured_output(dict(SMALL_SCHEMA))
    return {"supported": response_format is not None, "response_format": response_format}


def _planner_prepare() -> Any:
    from engine.agents.roster import load_roster
    from engine.game.procgen import new_game_state

    roster = load_roster(REPO / "games" / "neon-city" / "agents.yaml", slug="neon-city")
    return roster.get("the_line"), new_game_state(seed=5)


def _planner_run(prepared: Any) -> Any:
    from engine.agents.planner import plan_for

    spec, state = prepared
    return _plain(plan_for(spec, state, "I ask the line what it wants."))


PLAN = json.dumps(
    {"intent": "speak", "beat": "the line hums, interested", "line": "Everyone wants passage."}
)


def _chat_probe(_: Any) -> Any:
    from engine.llm.backend import chat_probe

    return chat_probe(timeout=20.0)


def _refresh(_: Any) -> Any:
    from engine.llm.registry import ModelRegistry

    return _plain(ModelRegistry().refresh())


def _native_is_available(_: Any) -> Any:
    client = NativeClient()
    try:
        return [client.is_available(), client.is_available()]
    finally:
        client.close()


def _summarizer(_: Any) -> Any:
    from engine.memory.ledger import StoryLedger, TurnRecord
    from engine.memory.summarizer import summarize

    fn = _REAL_SUMMARIZER_FN()
    ledger = StoryLedger()
    evicted = [
        TurnRecord(
            turn=1,
            day=1,
            location_id="forest_clearing",
            player_action="I follow the path east.",
            narration="The path east narrows between birches. A clock ticks ahead.",
        )
    ]
    summary = summarize(ledger, evicted, llm_fn=fn)
    return {"summarizer_available": fn is not None, "summary": summary}


SUMMARY = "The traveller followed the eastern path toward a clock ticking in the wood."


def _phase_a_prepare() -> Any:
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state

    return GameEngine(new_game_state(seed=7))


class _StubSkillsServer:
    """Stands in for the skills server: no listening socket, no mcp.json write."""

    def integration(self, session_id: str, **_kwargs: Any) -> dict[str, Any]:
        from engine.mcp.skills_server import plugin_integration

        return plugin_integration("engine-skills-golden")


def _phase_a_run(engine: Any) -> Any:
    from engine.agents import mechanics
    from engine.mcp import skills_server

    patch = pytest.MonkeyPatch()
    patch.setattr(skills_server, "get_skills_server", lambda _resolver: _StubSkillsServer())
    try:
        return mechanics.run_mechanics_phase(engine, "I study the boot marks.")
    finally:
        patch.undo()
        mechanics.release_engine(str(engine.state.session_id))


_TOOL_OUTPUT = json.dumps(
    [{"type": "text", "text": json.dumps({"evil_progress": 0.0, "phase": "dormant"})}]
)

PHASE_A_TOOLS = [
    {"event": "tool_call.start", "data": {"type": "tool_call.start", "tool": "query_evil_state"}},
    {"event": "tool_call.name", "data": {"type": "tool_call.name", "tool_name": "query_evil_state"}},
    {
        "event": "tool_call.arguments",
        "data": {"type": "tool_call.arguments", "tool": "query_evil_state", "arguments": {}},
    },
    {
        "event": "tool_call.success",
        "data": {
            "type": "tool_call.success",
            "tool": "query_evil_state",
            "arguments": {},
            "output": _TOOL_OUTPUT,
            "tool_call_id": "call_golden_1",
        },
    },
]

AUTHOR_ENVELOPE = {
    "name": "item_draft",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "name"],
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                },
            }
        },
    },
}

AUTHOR_REPLY = json.dumps({"items": [{"id": "brass_key", "name": "Brass Key"}]})


def _author(_: Any) -> Any:
    author_mod = _load_script("author", REPO / "scripts" / "author.py")
    author = author_mod.Author("clockwork-dark")
    return author._complete_json(
        "draft:item",
        [
            {"role": "system", "content": "You draft item content for a golden test."},
            {"role": "user", "content": "Draft 1 item for this story.\n\nBRIEF:\nA brass key."},
        ],
        AUTHOR_ENVELOPE,
        profile="small",
        max_tokens=1400,
    )


def _stack_probe(_: Any) -> Any:
    # Through the model server's service, as the stack asks it. v0.18 read a
    # fixed `stack.services.lmstudio.health_url` here; since v0.19.0 T6 the
    # shipped one is empty and the provider's probe is derived from
    # `llm.base_url` (the legacy variant's sanctioned difference, see
    # tests/test_llm_golden_lmstudio.py).
    from engine.stack import load_specs, probe_service

    (spec,) = [s for s in load_specs() if s.model_server]
    ok, detail = probe_service(spec)
    return {"ok": ok, "detail": detail}


_FLAGSHIP = _storyteller(7)
_HUE = _storyteller(11)

_REFUSAL = {
    "status": 400,
    "json": {
        "error": {
            "type": "invalid_request",
            "message": f"Model '{NARRATOR}' failed to load: insufficient memory",
        }
    },
}

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "01_turn_streamed_flagship",
        "Streamed storyteller turn, flagship, structured_output auto, probe yes.",
        (_models(), PROBE_YES, _compat_sse(ENVELOPE, reasoning=REASONING)),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
    ),
    Scenario(
        "02_turn_streamed_hue_and_cry",
        "The same streamed turn for hue-and-cry, with its own legal intents.",
        (_models(), PROBE_YES, _compat_sse(ENVELOPE, reasoning=REASONING)),
        _turn(streamed=True),
        prepare=_HUE,
        story="hue-and-cry",
    ),
    Scenario(
        "03_turn_non_streamed",
        "The non-streamed storyteller turn (no on_delta), auto, probe yes.",
        (_models(), PROBE_YES, _compat_json(ENVELOPE, reasoning=REASONING)),
        _turn(streamed=False),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
    ),
    Scenario(
        "04_turn_json_schema",
        "structured_output: json_schema -- the full schema, and no probe.",
        (_models(), _compat_sse(ENVELOPE, reasoning=REASONING)),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
        config=_structured("json_schema"),
    ),
    Scenario(
        "05_turn_json_object",
        "structured_output: json_object -- LM Studio's permissive json_schema.",
        (_models(), _compat_sse(ENVELOPE, reasoning=REASONING)),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
        config=_structured("json_object"),
    ),
    Scenario(
        "06_turn_off",
        "structured_output: off, native available: the turn goes native with no "
        "grammar. The one fixture whose later diff is sanctioned (spec 4.2).",
        (
            _models(),
            NATIVE_PROBE_400,
            _native_sse(ENVELOPE, model=NARRATOR, reasoning=REASONING),
        ),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
        config=_structured("off"),
        native=True,
    ),
    Scenario(
        "07_probe_yes",
        "The structured-output probe (auto) answering yes.",
        (_models(), PROBE_YES),
        _probe,
    ),
    Scenario(
        "08_probe_no_then_turn",
        "The probe answering no, and the streamed turn after it, sent with no "
        "grammar (native unavailable, so it rides compat).",
        (_models(), PROBE_NO, _compat_sse(PROSE, reasoning=REASONING)),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
    ),
    Scenario(
        "09_planner_auto",
        "planner.plan_for on the small profile (neon-city's the_line), auto.",
        (_models(), _compat_json(PLAN, model=UTILITY, reasoning_tokens=0)),
        _planner_run,
        prepare=_planner_prepare,
        story="neon-city",
    ),
    Scenario(
        "10_planner_off",
        "The same planner call under structured_output: off -- its grammar is "
        "still sent, because the planner builds its own response_format.",
        (_models(), _compat_json(PLAN, model=UTILITY, reasoning_tokens=0)),
        _planner_run,
        prepare=_planner_prepare,
        story="neon-city",
        config=_structured("off"),
    ),
    Scenario(
        "11_native_utility_chat",
        "A native utility chat on the small profile: reasoning off, on the wire.",
        (_models(), NATIVE_PROBE_400, _native_json("It is late autumn.", model=UTILITY)),
        _backend_chat("small", label="utility"),
        native=True,
    ),
    Scenario(
        "12_native_unavailable_utility_chat",
        "Native unavailable (the conftest default): the same chat, on compat.",
        (_models(), _compat_json("It is late autumn.", model=UTILITY, reasoning_tokens=0)),
        _backend_chat("small", label="utility"),
    ),
    Scenario(
        "13_starvation_retry_off",
        "Starved on native (big profile, reasoning on), retried native with "
        "reasoning off.",
        (
            _models(),
            NATIVE_PROBE_400,
            _native_json(
                "",
                model=NARRATOR,
                reasoning=REASONING,
                total=4400,
                reasoning_tokens=4400,
                ident="resp_golden_starved",
            ),
            _native_json("The path east narrows.", model=NARRATOR, total=6),
        ),
        _backend_chat("big", label="narrate"),
        native=True,
    ),
    Scenario(
        "14_starvation_retry_room",
        "Starved on a model with no reasoning block: retried with the measured "
        "room, the reasoning key omitted.",
        (
            _models(MODELS_NO_KNOB),
            NATIVE_PROBE_400,
            _native_json(
                "",
                model=PLAIN,
                reasoning=REASONING,
                total=900,
                reasoning_tokens=900,
                ident="resp_golden_starved",
            ),
            _native_json("It is late autumn.", model=PLAIN, total=960, reasoning_tokens=920),
        ),
        _backend_chat("small", label="utility"),
        native=True,
    ),
    Scenario(
        "15_starvation_stand_down",
        "Starved with no reasoning-token count while native is unavailable: the "
        "backend stands down and sends NOTHING further.",
        (
            _models(),
            _compat_json(
                "",
                model=UTILITY,
                finish="length",
                completion_tokens=1700,
                reasoning_tokens=None,
            ),
        ),
        _backend_chat("small", label="utility"),
    ),
    Scenario(
        "16_turn_streamed_starvation_recovery",
        "The storyteller's streamed turn starves; its recovery call goes out "
        "non-streamed with reasoning off (and, carrying a grammar, on compat).",
        (
            _models(),
            PROBE_YES,
            _compat_sse(
                "",
                reasoning=REASONING,
                finish="length",
                completion_tokens=4400,
                reasoning_tokens=4400,
            ),
            _compat_json(ENVELOPE, reasoning_tokens=0),
        ),
        _turn(streamed=True),
        prepare=_FLAGSHIP,
        story="clockwork-dark",
    ),
    Scenario(
        "17a_chat_probe_real_path",
        "backend.chat_probe answered on its real path (native available).",
        (_models(), NATIVE_PROBE_400, _native_json("ready", model=NARRATOR, total=3)),
        _chat_probe,
        native=True,
    ),
    Scenario(
        "17b_chat_probe_diagnostic_path",
        "backend.chat_probe: the real path is refused, so the raw diagnostic "
        "post runs and reports the server's own words.",
        (_models(), _REFUSAL, _REFUSAL),
        _chat_probe,
    ),
    Scenario(
        "18_registry_refresh",
        "ModelRegistry.refresh: one GET /api/v1/models, parsed.",
        (_models(),),
        _refresh,
    ),
    Scenario(
        "19_native_is_available",
        "NativeClient.is_available, the real method: a 400 means served, a 404 not.",
        (NATIVE_PROBE_400, NATIVE_PROBE_404),
        _native_is_available,
        native=True,
    ),
    Scenario(
        "20_summarizer",
        "The summarizer's call (default_state._summarizer_fn, label summarize), "
        "native available.",
        (
            _models(),
            _models(),
            NATIVE_PROBE_400,
            _native_json(SUMMARY, model=UTILITY),
        ),
        _summarizer,
        native=True,
    ),
    Scenario(
        "21_phase_a_mcp",
        "Phase A with lmstudio.mcp.enabled: the native stream carrying "
        "integrations, and the receipt read off its tool_call.success frame.",
        (
            NATIVE_PROBE_400,
            _models(),
            _native_sse(
                "DONE", model=NARRATOR, total=64, reasoning_tokens=0, tool_frames=PHASE_A_TOOLS
            ),
        ),
        _phase_a_run,
        prepare=_phase_a_prepare,
        story="clockwork-dark",
        config={"lmstudio": {"mcp": {"enabled": True}}},
        native=True,
    ),
    Scenario(
        "22_author_structured_call",
        "scripts/author.py's structured call, with its own response_format.",
        (_models(), _compat_json(AUTHOR_REPLY, model=UTILITY, reasoning_tokens=0)),
        _author,
    ),
    Scenario(
        "23_stack_probe",
        "The stack's model-server probe (stack.services.llm; recorded in v0.18 "
        "as stack.probe on stack.services.lmstudio.health_url).",
        (_models(),),
        _stack_probe,
    ),
)

SCENARIO_BY_NAME = {s.name: s for s in SCENARIOS}


# ---------------------------------------------------------------------------
# Running and fixture form
# ---------------------------------------------------------------------------


def request_to_fixture(request: dict[str, Any]) -> dict[str, Any]:
    """A captured request in fixture form: a JSON body stored as JSON, readable."""
    entry = {k: request[k] for k in ("method", "url", "headers")}
    body = request["body"]
    try:
        entry["json"] = json.loads(body) if body else None
    except ValueError:
        entry["json"] = None
    if entry["json"] is None:
        entry.pop("json")
        entry["text"] = body
    return entry


def fixture_to_request(entry: dict[str, Any]) -> dict[str, Any]:
    """Back to the capture's form: the body as canonical JSON text."""
    body = canonical_json(entry["json"]) if "json" in entry else str(entry.get("text", ""))
    return engine_headers(
        {
            "method": entry["method"],
            "url": entry["url"],
            "headers": dict(entry["headers"]),
            "body": body,
        }
    )


def run_scenario(
    scenario: Scenario,
    variant: str,
    directory: Path,
    *,
    answers: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Run one scenario under ``variant``'s pinning.

    Args:
        answers: The canned answers to serve, in order. The recorder passes
            none and serves the scenario's own; the test passes the recorded
            ``*.responses.json``, so the fixture on disk is what is replayed.

    Returns:
        ``{"requests", "responses", "parsed"}``: requests in capture form.
    """
    from engine.games import registry

    served = copy.deepcopy(list(scenario.answers) if answers is None else answers)
    with pinned(variant, directory, scenario.config, native=scenario.native) as patch:
        spy = BackendSpy(patch)
        activated = False
        try:
            if scenario.story:
                registry.activate(scenario.story)
                activated = True
            prepared = scenario.prepare() if scenario.prepare else None
            with wire(copy.deepcopy(served), exhaust=True) as seam:
                result = scenario.run(prepared)
        finally:
            if activated:
                registry.deactivate()
    parsed = json.loads(
        json.dumps({"result": _plain(result), "backend_calls": spy.calls}, ensure_ascii=False)
    )
    return {
        "requests": [engine_headers(r) for r in seam.requests],
        "responses": served,
        "parsed": parsed,
    }


# -- the doctor and launcher baseline ---------------------------------------

#: Services whose doctor row reads the machine, not the config: `grok` is a
#: PATH lookup (`shutil.which`) and has no health URL for the wire to answer.
MACHINE_ROWS = frozenset({"grok"})

BASELINE_ANSWERS: dict[str, tuple[dict[str, Any], ...]] = {
    # liveness, then chat_probe: discovery, the native probe, the native chat.
    "doctor_llm": (
        _models(),
        _models(),
        NATIVE_PROBE_400,
        _native_json("ready", model=NARRATOR, total=3),
    ),
    # stack.services in config order: lmstudio (answers), voxtral_tts (no
    # server on its port); voxtral_asr and comfyui are disabled and send none.
    "doctor_services": (
        _models(),
        {"raise": "ConnectError", "message": "[WinError 10061] connection refused"},
    ),
    "launcher_report": (_models(),),
}


def _doctor() -> Any:
    return _load_script("doctor", REPO / "scripts" / "doctor.py")


def capture_baseline(name: str, directory: Path) -> str:
    """
    The text one baseline section writes, under the ``shipped`` pinning and a
    healthy LM Studio (native route served) answering from the wire.
    """
    with pinned("shipped", directory, native=True):
        with wire(list(copy.deepcopy(BASELINE_ANSWERS[name])), exhaust=True):
            if name == "doctor_llm":
                doctor = _doctor()
                report = doctor.Report()
                doctor.check_llm(report)
                return report.render() + "\n"
            if name == "doctor_services":
                doctor = _doctor()
                report = doctor.Report()
                doctor.check_services(report)
                report.rows = [r for r in report.rows if r[1] not in MACHINE_ROWS]
                return report.render() + "\n"
            if name == "launcher_report":
                import launcher
                from engine.stack import StackManager, load_specs

                specs = [s for s in load_specs() if s.name == "lmstudio"]
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    launcher._report(StackManager(specs).status())
                return out.getvalue()
    raise KeyError(name)


# -- files -------------------------------------------------------------------


def fixture_paths(variant: str, name: str) -> dict[str, Path]:
    base = FIXTURES / variant
    return {
        "requests": base / f"{name}.requests.json",
        "responses": base / f"{name}.responses.json",
        "parsed": base / f"{name}.parsed.json",
    }


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def record(*, overwrite: bool = False) -> list[Path]:
    """Record every scenario for both variants, and the baseline texts."""
    if FIXTURES.exists() and any(FIXTURES.iterdir()) and not overwrite:
        raise SystemExit(
            f"{FIXTURES} already holds a recording. The golden is recorded once, "
            "on v0.18.0 code; pass --overwrite only if that is what you are doing."
        )
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="golden-") as scratch:
        root = Path(scratch)
        for variant in VARIANTS:
            for scenario in SCENARIOS:
                outcome = run_scenario(scenario, variant, root / variant / scenario.name)
                paths = fixture_paths(variant, scenario.name)
                _dump(paths["requests"], [request_to_fixture(r) for r in outcome["requests"]])
                _dump(paths["responses"], outcome["responses"])
                _dump(paths["parsed"], outcome["parsed"])
                written += list(paths.values())
        for name in BASELINE_ANSWERS:
            text = capture_baseline(name, root / "baseline" / name)
            path = FIXTURES / f"{name}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    return written


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["record"])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    written = record(overwrite=args.overwrite)
    print(f"wrote {len(written)} files under {FIXTURES}")
    return 0


__all__ = [
    "API_KEY",
    "BASELINE_ANSWERS",
    "FIXTURES",
    "SCENARIOS",
    "SCENARIO_BY_NAME",
    "TRANSPORT_HEADERS",
    "VARIANTS",
    "canonical_body",
    "capture_baseline",
    "engine_headers",
    "fixture_paths",
    "fixture_to_request",
    "pinned",
    "record",
    "request_to_fixture",
    "run_scenario",
]


if __name__ == "__main__":
    raise SystemExit(main())
