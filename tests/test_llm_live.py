"""
Live model-server tests (spec §9.4): against a REAL server, run by hand.

Skipped, module and all, unless ``CLOCKWORK_LIVE_LLM`` names the provider the
config names -- so the default suite gains exactly one skip, and a run that
meant llama-server can never quietly test LM Studio::

    $env:CLOCKWORK_LIVE_LLM = "llamacpp"
    $env:CLOCKWORK_LIVE_LLM_CONFIG = "C:\\somewhere\\llamacpp.yaml"   # optional
    .\\.venv\\Scripts\\python.exe -m pytest tests\\test_llm_live.py -v -s

``CLOCKWORK_LIVE_LLM_CONFIG`` names a YAML file read as the
``config/local.yaml`` layer for this run (the repo's own ``local.yaml`` is then
not read). Without it the owner's own ``config/local.yaml`` is. Either way the
layers are read from a temp copy, and nothing under ``config/`` is written.

Against the configured server:

* discovery binds ``big`` and ``small`` to models the server listed;
* a flagship narration turn (and a HUE & CRY one) with the real schema parses,
  on the grammar's rung, and every intent its choices carry is one the engine
  offered that turn;
* a ``reasoning: off`` utility call's ANSWER holds no thinking, and when the
  patch is trusted (a declaration lists ``off``) it reports none at all;
* a forced starvation (a profile of 8 content tokens and no reasoning budget)
  recovers, or stands down, per §5.3 -- never more than one retry;
* the doctor's model-server section has no FAIL.

``@pytest.mark.live`` opts every test here out of the conftest guard that
refuses model-server sockets; nothing else in the suite is marked.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any, Iterator

import pytest

PROVIDER = os.environ.get("CLOCKWORK_LIVE_LLM", "").strip()
if not PROVIDER:
    pytest.skip(
        "live model-server tests: set CLOCKWORK_LIVE_LLM=<provider> to run them",
        allow_module_level=True,
    )

pytestmark = pytest.mark.live

REPO = Path(__file__).resolve().parents[1]

MESSAGES = [
    {"role": "system", "content": "Answer in one short sentence."},
    {"role": "user", "content": "What season comes after summer?"},
]


@pytest.fixture(autouse=True)
def live_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """
    The real config layers, read from a temp copy of ``config/``'s local layer.

    Yields the temp config directory, where a test may write an env layer
    (``CLOCKWORK_ENV``) of its own. Every LLM singleton is rebuilt from it and
    rebuilt again from the real config afterwards.
    """
    import engine.config as config
    from engine.llm.client import reset_lms_client

    directory = tmp_path / "config"
    directory.mkdir()
    source = os.environ.get("CLOCKWORK_LIVE_LLM_CONFIG", "").strip()
    local = Path(source) if source else REPO / "config" / "local.yaml"
    if local.is_file():
        shutil.copyfile(local, directory / "local.yaml")
    real = {name: getattr(config, name) for name in ("_CONFIG_DIR", "_DEFAULT_PATH")}
    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    config._CONFIG_DIR = directory
    config._DEFAULT_PATH = REPO / "config" / "default.yaml"
    config.reset_config()
    reset_lms_client()
    try:
        configured = str(config.get_config().get("llm.provider") or "lmstudio")
        if configured != PROVIDER:
            pytest.skip(f"CLOCKWORK_LIVE_LLM={PROVIDER} but the config names {configured}")
        yield directory
    finally:
        for name, value in real.items():
            setattr(config, name, value)
        config.reset_config()
        reset_lms_client()


def _backend() -> Any:
    from engine.llm.backend import get_backend

    return get_backend()


def test_discovery_binds_big_and_small() -> None:
    from engine.llm.profiles import resolve_profile

    for profile in ("big", "small"):
        bound = resolve_profile(profile, refresh=True)
        print(f"{profile}: {bound.model} (ctx {bound.context_tokens}, reasoning "
              f"model {bound.is_reasoning_model})")
        assert bound.bound, f"{profile} did not bind to a model the server listed"


def _intents_offered(state: Any) -> dict[str, set[str]]:
    from engine.game.intents import legal_intents

    return {
        str(verb.action): {str(t) for t in getattr(verb, "targets", ())}
        for verb in legal_intents(state)
    }


@pytest.mark.parametrize("slug", ["clockwork-dark", "hue-and-cry"])
def test_a_narration_turn_parses_and_its_choices_come_from_the_grammar(slug: str) -> None:
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state
    from engine.games import registry

    registry.activate(slug)
    engine = GameEngine(new_game_state(seed=7))
    offered = _intents_offered(engine.state)
    agent = StorytellerAgent(engine)
    shown: list[str] = []
    result = agent.run_turn("I look around and take stock.", on_delta=shown.append)
    print(f"[{slug}] rung {_backend().structured_rung()}; streamed {len(''.join(shown))} chars; "
          f"narration: {result.narration[:300]!r}")
    for choice in result.choices:
        print(f"  choice {choice.get('id')}: {choice.get('text')!r} intent={choice.get('intent')}")

    assert not result.llm_unavailable, "the storyteller fell back to its canned line"
    assert _backend().structured_rung() == 1, "the grammar is not on the wire"
    assert not result.parsed.get("parse_failed"), result.raw_llm[:500]
    assert result.narration.strip()
    assert "</think>" not in result.raw_llm and "<think>" not in result.raw_llm
    assert 2 <= len(result.choices) <= 4
    for choice in result.choices:
        intent = choice.get("intent")
        if not intent:
            continue
        verb = str(intent.get("action") or "")
        assert verb in offered, f"{verb!r} was not offered: {sorted(offered)}"
        target = intent.get("target")
        if target is not None:
            assert str(target) in offered[verb], f"{verb} {target!r} was not offered"


def test_a_reasoning_off_utility_call_answers_without_thinking() -> None:
    from engine.llm.client import reasoning_patch
    from engine.llm.profiles import resolve_profile

    small = resolve_profile("small")
    assert small.reasoning == "off"
    patch = reasoning_patch(small.model, "off")
    result = _backend().chat(MESSAGES, profile="small", label="live:off")
    print(f"patch {patch}; content {result.content!r}; reasoning "
          f"{len(result.reasoning_content)} chars, {result.reasoning_tokens} tokens")
    assert result.content.strip()
    assert "</think>" not in result.content and "<think>" not in result.content
    if patch is not None and patch.trusted:
        assert not result.reasoning_content.strip()
        assert result.reasoning_tokens == 0


def test_a_forced_starvation_recovers_or_stands_down(
    live_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A profile of 8 content tokens, no reasoning budget and reasoning on: a
    reasoning model starves. §5.3: the retry adds the patch once, keeping the
    request otherwise; a request that carried it is never repeated.
    """
    import yaml

    import engine.config as config
    from engine.llm.profiles import resolve_profile

    model = resolve_profile("big").model
    (live_config / "starve.yaml").write_text(
        yaml.safe_dump({"llm": {"profiles": {"starve": {
            "model": model, "max_tokens": 8, "reasoning_budget": 0,
            "reasoning": "on", "lane": "utility", "require_tools": False,
        }}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLOCKWORK_ENV", "starve")
    config.reset_config()

    sent: list[dict[str, Any]] = []
    # The row's own client: the compat one, or Ollama's -- and on LM Studio
    # the native one too, which serves an ungrammared request (v0.18's
    # routing). Spying only the compat client there recorded nothing (T9,
    # measured against LM Studio: an IndexError on sent[0]).
    classes = {type(_backend().route_client())}
    if _backend().provider().name == "lmstudio":
        from engine.llm.lmstudio_native import NativeClient

        classes.add(NativeClient)

    def spying(real_chat: Any) -> Any:
        def spy(self: Any, messages: Any, **kwargs: Any) -> Any:
            result = real_chat(self, messages, **kwargs)
            sent.append({"reasoning": kwargs.get("reasoning"), "result": result})
            return result

        return spy

    for client_class in classes:
        monkeypatch.setattr(client_class, "chat", spying(client_class.chat))
    result = _backend().chat(MESSAGES, profile="starve", label="live:starve")
    for i, call in enumerate(sent):
        r = call["result"]
        print(f"request {i + 1}: reasoning={call['reasoning']} finish={r.finish_reason} "
              f"content={r.content!r} reasoning_chars={len(r.reasoning_content)} "
              f"starved={r.starved_by_reasoning}")
    if not sent[0]["result"].starved_by_reasoning:
        pytest.skip(f"{model} answered in 8 tokens without thinking: not a reasoning model")
    assert len(sent) <= 2, "a starved request was retried more than once"
    if len(sent) == 2:
        assert sent[1]["reasoning"] == "off", "the retry did not carry the patch"
    assert "</think>" not in result.content
    assert result.content.strip() or result.starved_by_reasoning


def test_the_doctor_has_no_fail_row() -> None:
    spec = importlib.util.spec_from_file_location(
        "doctor_live", REPO / "scripts" / "doctor.py"
    )
    assert spec is not None and spec.loader is not None
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    report = doctor.Report()
    doctor.check_llm(report)
    for section, name, status, detail in report.rows:
        print(f"{section} | {name} | {status} | {detail}")
    assert not report.failed
