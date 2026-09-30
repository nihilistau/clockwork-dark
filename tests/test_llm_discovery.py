"""
Model discovery for every server, from each server's own fixtures (spec §3).

``engine/llm/discovery.py`` has one parser per provider row, each filling
the same ``ModelInfo``; ``ModelRegistry.refresh`` runs the configured one
through ``_fetch``. Every request here goes through ``tests/llm_wire.py`` (the
``httpx`` transport seam), so the real ``_fetch`` runs and no socket opens.
This file is ABOUT discovery, so it is ``real_discovery``: the conftest pin
that answers discovery with an empty list would replace the code under test.

The non-LM Studio fixtures are ``authored`` from each server's documentation
(``tests/fixtures/llm/PROVENANCE.yaml``); LM Studio's body is the golden's
own recorded answer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

import engine.config as config
from engine.llm import discovery
from engine.llm.providers import PROVIDERS, get_provider
from engine.llm.registry import (
    ModelInfo,
    ModelRegistry,
    ModelUnavailable,
    NotAModelList,
    NotV1Models,
    probe_models,
    reset_registry,
)
from tests.llm_wire import wire

pytestmark = pytest.mark.real_discovery

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "llm"
GOLDEN_MODELS = FIXTURES / "golden_lmstudio" / "shipped" / "18_registry_refresh.responses.json"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _lmstudio_body() -> dict[str, Any]:
    return json.loads(GOLDEN_MODELS.read_text(encoding="utf-8"))[0]["json"]


def _ok(body: Any) -> dict[str, Any]:
    return {"status": 200, "json": body}


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Configure a provider through the real layers (``tmp_path`` local.yaml)."""
    from engine.llm.profiles import reset_profiles

    monkeypatch.delenv("CLOCKWORK_ENV", raising=False)
    monkeypatch.delenv("CLOCKWORK_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)
    monkeypatch.setattr(config, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "_DEFAULT_PATH", REPO / "config" / "default.yaml")
    monkeypatch.setattr(config, "_overlay", {})
    monkeypatch.setattr(config, "_instance", None)

    def configure(provider: str, **llm: Any) -> None:
        block = {"provider": provider, "api_key": "discovery-test-key"}
        url = PROVIDERS[provider].default_base_url.value or "https://models.example/v1"
        block["base_url"] = url
        block.update(llm)
        (tmp_path / "local.yaml").write_text(
            yaml.safe_dump({"llm": block}), encoding="utf-8"
        )
        config._instance = None
        reset_registry()
        reset_profiles()

    yield configure
    config._instance = None
    reset_registry()
    reset_profiles()


# -- the LM Studio row: v0.18, moved -------------------------------------------


def test_lmstudio_parses_the_golden_body_as_v018_did() -> None:
    recorded = json.loads(
        (GOLDEN_MODELS.parent / "18_registry_refresh.parsed.json").read_text(encoding="utf-8")
    )["result"]
    import dataclasses

    models = discovery.parse_lmstudio_v1(_lmstudio_body())
    parsed = json.loads(json.dumps([dataclasses.asdict(m) for m in models]))
    assert parsed == recorded
    assert {m.source for m in models} == {"lmstudio_v1"}


def test_lmstudio_refresh_is_one_get_of_the_v1_list(server: Any) -> None:
    server("lmstudio")
    with wire([_ok(_lmstudio_body())], exhaust=True) as seam:
        models = ModelRegistry().refresh()
    assert [r["method"] + " " + r["url"] for r in seam.requests] == [
        "GET http://localhost:1234/api/v1/models"
    ]
    assert [m.id for m in models][:2] == ["golden/narrator-26b", "golden/utility-8b"]


def test_notv1models_is_the_same_class() -> None:
    assert NotV1Models is NotAModelList


# -- vLLM ----------------------------------------------------------------------


def test_vllm_reads_max_model_len_as_the_served_context(server: Any) -> None:
    server("vllm")
    with wire([_ok(_fixture("vllm/models.json"))], exhaust=True) as seam:
        models = ModelRegistry().refresh()
    assert [r["url"] for r in seam.requests] == ["http://localhost:8000/v1/models"]
    assert seam.requests[0]["headers"]["authorization"] == "Bearer discovery-test-key"
    (model,) = models
    assert model.id == "Qwen/Qwen3-8B"
    assert model.source == "openai_models"
    assert model.usable_context == 32768
    assert model.is_loaded and model.is_chat_model
    # Nothing in /v1/models says what it can do, and nothing guesses.
    assert not model.supports_tools
    assert not model.is_reasoning
    assert not model.reasoning_configurable


# -- llama-server --------------------------------------------------------------


def test_llamacpp_reads_n_ctx_from_props(server: Any) -> None:
    server("llamacpp")
    answers = [_ok(_fixture("llamacpp/models.json")), _ok(_fixture("llamacpp/models_props.json"))]
    with wire(answers, exhaust=True) as seam:
        models = ModelRegistry().refresh()
    assert [r["url"] for r in seam.requests] == [
        "http://localhost:8080/v1/models",
        "http://localhost:8080/props",
    ]
    (model,) = models
    assert model.id == "Qwen3-4B-Thinking-2507-Q4_K_M.gguf"
    assert model.source == "llamacpp_props"
    assert model.loaded_context_length == 16384
    assert model.max_context_length == 262144  # meta.n_ctx_train
    assert model.usable_context == 16384
    assert model.is_loaded and model.is_chat_model
    assert not model.supports_tools and not model.is_reasoning


def test_llamacpp_props_error_is_not_a_model_list(server: Any, caplog: Any) -> None:
    server("llamacpp")
    answers = [_ok(_fixture("llamacpp/models.json")), _ok(_fixture("llamacpp/models_error.json"))]
    with caplog.at_level(logging.ERROR), wire(answers, exhaust=True):
        assert ModelRegistry().refresh() == []
    assert "/props did not answer with llamacpp's model list" in caplog.text


# -- Ollama --------------------------------------------------------------------


def _ollama_answers(show_qwen3: Any = None) -> list[dict[str, Any]]:
    return [
        _ok(_fixture("ollama/models_tags.json")),
        _ok(_fixture("ollama/models_ps.json")),
        _ok(show_qwen3 or _fixture("ollama/models_show_qwen3.json")),
        _ok(_fixture("ollama/models_show_llama.json")),
        _ok(_fixture("ollama/models_show_nomic.json")),
    ]


def test_ollama_reads_tags_ps_and_show(server: Any) -> None:
    server("ollama")
    with wire(_ollama_answers(), exhaust=True) as seam:
        models = {m.id: m for m in ModelRegistry().refresh()}
    assert [(r["method"], r["url"]) for r in seam.requests] == [
        ("GET", "http://localhost:11434/api/tags"),
        ("GET", "http://localhost:11434/api/ps"),
        ("POST", "http://localhost:11434/api/show"),
        ("POST", "http://localhost:11434/api/show"),
        ("POST", "http://localhost:11434/api/show"),
    ]
    assert [json.loads(r["body"]) for r in seam.requests[2:]] == [
        {"model": "qwen3:8b"},
        {"model": "llama3.1:8b"},
        {"model": "nomic-embed-text:latest"},
    ]

    qwen = models["qwen3:8b"]
    assert qwen.source == "ollama_show"
    assert qwen.is_loaded  # listed by /api/ps
    assert qwen.supports_tools
    assert qwen.is_reasoning and qwen.reasoning_configurable
    assert qwen.accepts_reasoning("off") and qwen.accepts_reasoning("on")
    assert qwen.max_context_length == 40960
    # The num_ctx the engine will send (llm.context_tokens), capped by the window.
    assert qwen.usable_context == 8192

    llama = models["llama3.1:8b"]
    assert not llama.is_loaded
    assert llama.supports_tools
    assert not llama.is_reasoning and not llama.accepts_reasoning("off")
    assert llama.max_context_length == 131072

    nomic = models["nomic-embed-text:latest"]
    assert nomic.type == "embedding" and not nomic.is_chat_model


def test_ollama_reads_the_recorded_live_list(server: Any) -> None:
    """
    Recorded from Ollama 0.34.4 (v0.19.0 T8): ``qwen3:4b`` from the library
    (thinking, tools, a 262144-token window) and a GGUF imported by a
    Modelfile (completion only). ``/api/ps`` reported the ``num_ctx`` the
    recording sent (8192) as each loaded model's ``context_length``.
    """
    ps = _fixture("ollama/models_ps_live.json")
    assert {m["context_length"] for m in ps["models"]} == {8192}
    server("ollama")
    answers = [
        _ok(_fixture("ollama/models_tags_live.json")),
        _ok(ps),
        _ok(_fixture("ollama/models_show_thinker_live.json")),
        _ok(_fixture("ollama/models_show_plain_live.json")),
    ]
    with wire(answers, exhaust=True):
        models = {m.id: m for m in ModelRegistry().refresh()}
    qwen = models["qwen3:4b"]
    assert qwen.is_loaded and qwen.supports_tools
    assert qwen.is_reasoning and qwen.accepts_reasoning("off")
    assert qwen.max_context_length == 262144
    assert qwen.usable_context == 8192
    phi = models["phi3.1-mini-local:latest"]
    assert phi.is_chat_model and not phi.supports_tools
    assert not phi.is_reasoning and not phi.accepts_reasoning("off")


def test_ollama_num_ctx_is_capped_by_the_trained_window(server: Any) -> None:
    server("ollama", context_tokens=65536)
    with wire(_ollama_answers(), exhaust=True):
        models = {m.id: m for m in ModelRegistry().refresh()}
    assert models["qwen3:8b"].usable_context == 40960
    assert models["llama3.1:8b"].usable_context == 65536


def test_ollama_reasoning_is_the_thinking_capability_not_the_arch(server: Any) -> None:
    """``qwen3`` is in LM Studio's REASONING_ARCHES; that list is not read here."""
    show = _fixture("ollama/models_show_qwen3.json")
    show["capabilities"] = ["completion", "tools"]
    server("ollama")
    with wire(_ollama_answers(show), exhaust=True):
        qwen = {m.id: m for m in ModelRegistry().refresh()}["qwen3:8b"]
    assert qwen.arch == "qwen3"
    assert not qwen.is_reasoning
    assert not qwen.accepts_reasoning("off")


# -- a generic OpenAI-compatible server ------------------------------------------


def test_openai_compat_is_ids_only(server: Any) -> None:
    server("openai_compat", base_url="https://models.example/v1")
    with wire([_ok(_fixture("openai_compat/models.json"))], exhaust=True) as seam:
        models = {m.id: m for m in ModelRegistry().refresh()}
    assert [r["url"] for r in seam.requests] == ["https://models.example/v1/models"]
    for model in models.values():
        assert model.source == "openai_models"
        assert model.is_loaded and model.is_chat_model
        # Nothing declared: the configured window, no tools, no reasoning.
        assert model.usable_context == 8192
        assert not model.supports_tools
    # A name that says "reasoning" and "r1" is not evidence (spec §3.2).
    assert not models["qwen3-reasoning-r1-distill"].is_reasoning


def test_the_openai_list_hangs_off_base_url_not_the_root(server: Any) -> None:
    """
    Review #9: a generic base that does not end in ``/v1`` (Gemini's
    ``/v1beta/openai``, a proxy prefix) is where compat chat goes, so the
    model list is asked there too -- ``base_url + /models`` -- and not at the
    root plus ``/v1/models``. Byte-identical for every ``/v1`` base.
    """
    base = "https://gw.example/v1beta/openai"
    server("openai_compat", base_url=base)
    with wire([_ok(_fixture("openai_compat/models.json"))], exhaust=True) as seam:
        assert len(ModelRegistry().refresh()) == 2
    assert [r["url"] for r in seam.requests] == [f"{base}/models"]
    with wire([_ok(_fixture("openai_compat/models.json"))], exhaust=True) as seam:
        ok, _ = probe_models(timeout=1.0)
    assert ok and seam.requests[0]["url"] == f"{base}/models"


def test_is_reasoning_never_reads_a_name_or_an_arch_off_lm_studio() -> None:
    for source in ("openai_models", "llamacpp_props", "ollama_show"):
        model = ModelInfo(id="deepseek-r1-qwen3-thinking", arch="qwen3", source=source)
        assert not model.is_reasoning, source
    # LM Studio's own measured arch list still applies to LM Studio's models.
    assert ModelInfo(id="x", arch="qwen3").is_reasoning
    assert ModelInfo(id="x", arch="qwen3", source="lmstudio_v1").is_reasoning


# -- declared models (spec §3.2) --------------------------------------------------


DECLARED = {
    "house-narrator": {
        "context": 32768,
        "tools": True,
        "reasoning": ["off", "on"],
        "reasoning_default": "on",
    }
}


def test_a_declaration_fills_what_the_server_left_empty(server: Any) -> None:
    server("openai_compat", base_url="https://models.example/v1", declared_models=DECLARED)
    with wire([_ok(_fixture("openai_compat/models.json"))], exhaust=True):
        models = {m.id: m for m in ModelRegistry().refresh()}
    narrator = models["house-narrator"]
    # The parser stays the source; the declaration is recorded beside it (review #6).
    assert narrator.source == "openai_models"
    assert set(narrator.declared_fields) == {"context", "tools", "reasoning", "reasoning_default"}
    assert narrator.usable_context == 32768
    assert narrator.supports_tools
    assert narrator.is_reasoning
    assert narrator.accepts_reasoning("off")
    # The undeclared one is untouched.
    assert models["qwen3-reasoning-r1-distill"].source == "openai_models"


def test_a_served_context_beats_a_declared_one(server: Any) -> None:
    server("vllm", declared_models={"Qwen/Qwen3-8B": {"context": 4096, "tools": True}})
    with wire([_ok(_fixture("vllm/models.json"))], exhaust=True):
        (model,) = ModelRegistry().refresh()
    assert model.usable_context == 32768  # max_model_len, not the declaration
    assert model.supports_tools  # the list said nothing about tools, so this fills


def test_lm_studios_loaded_context_and_capabilities_beat_a_declaration(server: Any) -> None:
    declared = {
        "golden/narrator-26b": {"context": 1024, "tools": False, "reasoning_default": "off"},
        "golden/utility-8b": {"tools": True, "reasoning": ["on"]},
    }
    server("lmstudio", declared_models=declared)
    with wire([_ok(_lmstudio_body())], exhaust=True):
        models = {m.id: m for m in ModelRegistry().refresh()}
    narrator, utility = models["golden/narrator-26b"], models["golden/utility-8b"]
    assert narrator.usable_context == 16384
    assert narrator.supports_tools and narrator.is_reasoning
    assert not utility.supports_tools  # LM Studio reported it; a declaration does not override
    assert utility.reasoning_options == ("off", "on")
    assert {narrator.source, utility.source} == {"lmstudio_v1"}


def test_a_declared_id_the_server_does_not_list_is_warned_and_never_bound(
    server: Any, caplog: Any
) -> None:
    declared = {"ghost/model": {"context": 32768, "tools": True}}
    server("vllm", declared_models=declared)
    registry = ModelRegistry()
    with caplog.at_level(logging.WARNING), wire([_ok(_fixture("vllm/models.json"))], exhaust=True):
        models = registry.refresh()
    assert [m.id for m in models] == ["Qwen/Qwen3-8B"]
    assert "ghost/model" in caplog.text and "not on the server" in caplog.text
    binding = registry.bind("big", prefer=("ghost/model",))
    assert binding.model.id == "Qwen/Qwen3-8B"
    with pytest.raises(ModelUnavailable):
        registry.bind("big", prefer=("ghost/model",), require_tools=True)


def test_apply_declared_leaves_a_list_alone_without_declarations() -> None:
    models = [ModelInfo(id="a", source="openai_models")]
    # `==` ignores provenance (review #5), so it is compared explicitly.
    for out in (discovery.apply_declared(models, {}), discovery.apply_declared(models, None)):
        assert out == models
        assert [(m.source, m.declared_fields) for m in out] == [("openai_models", ())]


def test_source_and_declared_fields_survive_replace_pickle_and_deepcopy() -> None:
    """
    Review #5: both are init-only, kept as attributes so ``asdict`` shows
    v0.18's fields alone (golden scenario 18). Pin that they are carried
    over everywhere a ModelInfo is copied, so a rename cannot drop them.
    """
    import copy
    import dataclasses
    import pickle

    model = ModelInfo(id="m", source="llamacpp_props", declared_fields=("context",))
    for copied in (
        dataclasses.replace(model, state="loaded"),
        pickle.loads(pickle.dumps(model)),
        copy.deepcopy(model),
    ):
        assert copied.source == "llamacpp_props"
        assert copied.declared_fields == ("context",)
    fields = dataclasses.asdict(model)
    assert "source" not in fields and "declared_fields" not in fields
    assert ModelInfo(id="m").source == "lmstudio_v1"
    assert ModelInfo(id="m").declared_fields == ()


def test_a_generic_servers_reported_context_beats_a_declared_one(server: Any) -> None:
    """
    Precedence is reported > declared > ``llm.context_tokens`` for every
    provider, the generic one included (spec §3.2; review #2): a served
    ``max_model_len`` is the number that truncates.
    """
    body = _fixture("openai_compat/models.json")
    body["data"][1]["max_model_len"] = 4096
    server(
        "openai_compat",
        base_url="https://models.example/v1",
        declared_models={"house-narrator": {"context": 32768}},
    )
    with wire([_ok(body)], exhaust=True):
        narrator = {m.id: m for m in ModelRegistry().refresh()}["house-narrator"]
    assert narrator.usable_context == 4096
    assert "context" not in narrator.declared_fields


def test_a_declared_context_beats_a_trained_window(server: Any) -> None:
    """
    Review #7: llama-server's ``meta.n_ctx_train`` is what the weights were
    trained to, not what was served. When ``/props`` gives no ``n_ctx``, a
    declared context wins over it; only a served or loaded number beats a
    declaration.
    """
    props = _fixture("llamacpp/models_props.json")
    del props["default_generation_settings"]["n_ctx"]
    server("llamacpp", declared_models={"Qwen3-4B-Thinking-2507-Q4_K_M.gguf": {"context": 8192}})
    answers = [_ok(_fixture("llamacpp/models.json")), _ok(props)]
    with wire(answers, exhaust=True):
        (model,) = ModelRegistry().refresh()
    assert model.max_context_length == 262144
    assert model.usable_context == 8192
    assert model.source == "llamacpp_props"
    assert model.declared_fields == ("context",)


def test_an_ollama_num_ctx_taken_from_a_declaration_says_so(server: Any) -> None:
    """
    Carried from T3's review: Ollama's usable context IS the ``num_ctx`` the
    engine sends, so a declared context became the loaded number inside the
    parser, ``apply_declared`` then saw a context already filled, and the
    provenance was lost -- ``declared_fields`` said ``()`` for a number only
    the owner's declaration had named. Fails at T4 (2854f07). A declaration
    the trained window CAPPED did not set the number (the window did), so it
    is not credited with it (fix round 1: at 87a7055 it was).
    """
    server(
        "ollama",
        declared_models={"qwen3:8b": {"context": 32768}, "llama3.1:8b": {"context": 200000}},
    )
    with wire(_ollama_answers(), exhaust=True):
        models = {m.id: m for m in ModelRegistry().refresh()}
    qwen, llama = models["qwen3:8b"], models["llama3.1:8b"]
    assert qwen.usable_context == 32768
    assert qwen.declared_fields == ("context",)
    assert qwen.source == "ollama_show"
    assert llama.usable_context == 131072  # capped by llama.context_length
    assert llama.declared_fields == ()
    # llm.context_tokens is not a declaration.
    assert models["nomic-embed-text:latest"].declared_fields == ()


def test_a_declaration_never_erases_lm_studios_provenance(server: Any) -> None:
    """
    Review #6: a declaration used to set ``source="declared"``, which read as
    "not LM Studio" and turned off the measured arch list and the encoder
    checks. The parser stays the source.
    """
    body = _lmstudio_body()
    narrator = body["models"][0]
    narrator["loaded_instances"] = []
    narrator["architecture"] = "qwen3"
    narrator["capabilities"] = {"trained_for_tool_use": True}
    server("lmstudio", declared_models={"golden/narrator-26b": {"context": 12000}})
    with wire([_ok(body)], exhaust=True):
        model = {m.id: m for m in ModelRegistry().refresh()}["golden/narrator-26b"]
    assert model.source == "lmstudio_v1"
    assert model.declared_fields == ("context",)
    assert model.usable_context == 12000  # nothing loaded: advertised 131072 is not served
    assert model.is_reasoning  # REASONING_ARCHES still read for LM Studio's own model
    assert model.is_chat_model


def test_one_failing_ollama_show_costs_that_model_only(server: Any, caplog: Any) -> None:
    """
    Review #1: the shape rule is about the LIST. One model whose ``/api/show``
    answers an error body, or 404s, is skipped with a warning; the rest bind.
    So is one whose 200 is not JSON at all -- a proxy's HTML page (T3
    re-review N3: that ``ValueError`` used to escape and cost every model).
    """
    tags = _fixture("ollama/models_tags.json")
    tags["models"] = tags["models"][:2]
    for failing in (
        _ok(_fixture("ollama/models_error.json")),
        {"status": 404, "json": _fixture("ollama/models_error.json")},
        {"status": 200, "text": "<html><body>502 Bad Gateway</body></html>"},
    ):
        server("ollama")
        answers = [
            _ok(tags),
            _ok(_fixture("ollama/models_ps.json")),
            _ok(_fixture("ollama/models_show_qwen3.json")),
            failing,
        ]
        registry = ModelRegistry()
        caplog.clear()
        with caplog.at_level(logging.WARNING), wire(answers, exhaust=True):
            models = registry.refresh()
        assert [m.id for m in models] == ["qwen3:8b"]
        assert "llama3.1:8b" in caplog.text and "skipped" in caplog.text
        assert registry.bind("big").model.id == "qwen3:8b"


# -- every body is shape-checked --------------------------------------------------


@pytest.mark.parametrize(
    "provider,fixture",
    [
        ("vllm", "vllm/models_error.json"),
        ("vllm", "vllm/models_error_nested.json"),
        ("vllm", "ollama/models_tags.json"),
        ("vllm", "lmstudio"),
        ("llamacpp", "llamacpp/models_error.json"),
        ("llamacpp", "ollama/models_tags.json"),
        ("ollama", "ollama/models_error.json"),
        ("ollama", "llamacpp/models.json"),
        ("ollama", "vllm/models.json"),
        ("ollama", "lmstudio"),
        ("openai_compat", "openai_compat/models_error.json"),
        ("openai_compat", "lmstudio"),
        ("lmstudio", "vllm/models.json"),
        ("lmstudio", "ollama/models_tags.json"),
        ("lmstudio", "ollama/models_error.json"),
    ],
)
def test_another_servers_body_raises_naming_the_provider(provider: str, fixture: str) -> None:
    body = _lmstudio_body() if fixture == "lmstudio" else _fixture(fixture)
    row = get_provider(provider)
    with pytest.raises(NotAModelList) as caught:
        discovery.list_models(row, lambda path, payload=None: body)
    assert caught.value.provider == provider
    assert caught.value.body == body
    if provider != "lmstudio":  # LM Studio's message is v0.18's, word for word
        assert provider in str(caught.value)


def test_an_ollama_show_error_is_shape_checked_and_skips_only_that_model(caplog: Any) -> None:
    """An error body at /api/show is still refused -- for that model alone (review #1)."""
    answers = iter(
        [
            _fixture("ollama/models_tags.json"),
            _fixture("ollama/models_ps.json"),
            _fixture("ollama/models_error.json"),
            _fixture("ollama/models_show_llama.json"),
            _fixture("ollama/models_show_nomic.json"),
        ]
    )
    with caplog.at_level(logging.WARNING):
        models = discovery.list_models(
            get_provider("ollama"), lambda path, body=None: next(answers)
        )
    assert [m.id for m in models] == ["llama3.1:8b", "nomic-embed-text:latest"]
    assert "qwen3:8b" in caplog.text and "/api/show did not answer" in caplog.text
    with pytest.raises(NotAModelList, match="/api/show"):
        discovery.parse_ollama_show("x", _fixture("ollama/models_error.json"))


def test_an_error_body_through_refresh_is_logged_and_binds_nothing(
    server: Any, caplog: Any
) -> None:
    server("vllm")
    with caplog.at_level(logging.ERROR), wire([_ok(_fixture("vllm/models_error.json"))]):
        assert ModelRegistry().refresh() == []
    assert "not the OpenAI-compatible model list" in caplog.text


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_each_providers_empty_list_parses_to_nothing(provider: str) -> None:
    row = get_provider(provider)
    empty = row.empty_model_list()
    assert discovery.list_models(row, lambda path, body=None: empty) == []
    assert discovery.parse_list(row, empty) == []


# -- a failed discovery is v0.18's unbound profile ------------------------------------


def test_an_unbound_profile_is_the_offline_placeholder(server: Any) -> None:
    from engine.llm.profiles import OFFLINE_MODEL, resolve_profile

    server("vllm")
    with wire([_ok(_fixture("vllm/models_error.json"))] * 3):
        profile = resolve_profile("small", refresh=True)
    assert profile.model == OFFLINE_MODEL
    assert profile.bound is False


def test_a_bound_vllm_profile_budgets_on_the_served_context(server: Any) -> None:
    from engine.llm.profiles import resolve_profile

    server("vllm")
    with wire([_ok(_fixture("vllm/models.json"))]):
        profile = resolve_profile("big", refresh=True)
    assert profile.bound is True
    assert profile.model == "Qwen/Qwen3-8B"
    assert profile.context_tokens == 32768
    assert profile.is_reasoning_model is False


# -- the liveness probe asks the provider's list ----------------------------------------


def test_probe_models_asks_the_providers_own_list(server: Any) -> None:
    server("vllm")
    with wire([_ok(_fixture("vllm/models.json"))], exhaust=True) as seam:
        ok, detail = probe_models(timeout=1.0)
    assert ok, detail
    assert seam.requests[0]["url"] == "http://localhost:8000/v1/models"
    # The URL that answered, not the relative "/models": the list hangs off a
    # configurable base, so a doctor row has to say which one (T3 re-review N4).
    assert detail == "http://localhost:8000/v1/models answers: 1 models, loaded: Qwen/Qwen3-8B"


def test_probe_models_refuses_lm_studios_body_on_ollama(server: Any) -> None:
    server("ollama")
    with wire([_ok(_lmstudio_body())], exhaust=True) as seam:
        ok, detail = probe_models(timeout=1.0)
    assert seam.requests[0]["url"] == "http://localhost:11434/api/tags"
    assert not ok
    assert "ollama's model list" in detail


def test_a_refused_key_off_lm_studio_does_not_send_you_to_lm_studio(
    server: Any, caplog: Any
) -> None:
    refused = {"status": 401, "json": _fixture("openai_compat/models_error.json")}
    server("vllm")
    with wire([refused], exhaust=True):
        ok, detail = probe_models(timeout=1.0)
    assert not ok
    assert "llm_api_key.txt" in detail and "LM Studio" not in detail
    with caplog.at_level(logging.ERROR), wire([refused], exhaust=True):
        assert ModelRegistry().refresh() == []
    # Off LM Studio the key may be present and WRONG (a stale file wins the
    # fallback chain), so the message says so (T3 re-review N4).
    assert "vLLM requires an API key and none is configured, or it is wrong." in caplog.text


def test_lm_studios_401_texts_are_v018s_from_the_row(server: Any, caplog: Any) -> None:
    """The wording moved into ``Provider.key_hint`` (review #8); LM Studio's is unchanged."""
    refused = {"status": 401, "json": {"error": "unauthorized"}}
    server("lmstudio")
    with wire([refused], exhaust=True):
        ok, detail = probe_models(timeout=1.0)
    assert not ok
    assert detail == (
        "listening, but it refuses every request: the API key is missing or "
        "wrong. Set llm.api_key in config/local.yaml, or turn off "
        "'Require API key' in LM Studio's server settings"
    )
    with caplog.at_level(logging.ERROR), wire([refused], exhaust=True):
        assert ModelRegistry().refresh() == []
    assert (
        "LM Studio requires an API key and none is configured. Set "
        "llm.api_key in config/local.yaml, or turn off "
        "'Require API key' in LM Studio's server settings. Until then "
        "EVERY request is refused, including the ones the health check "
        "does not make."
    ) in caplog.text


def test_probe_models_on_lm_studio_is_v018s(server: Any) -> None:
    server("lmstudio")
    with wire([_ok(_lmstudio_body())], exhaust=True) as seam:
        ok, detail = probe_models(timeout=1.0)
    assert ok
    assert seam.requests[0]["url"] == "http://localhost:1234/api/v1/models"
    assert detail == (
        "/api/v1/models answers: 3 models, loaded: golden/narrator-26b, golden/utility-8b"
    )
