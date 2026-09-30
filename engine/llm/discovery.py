"""
Model discovery, for every server
=================================

One parser per provider row (``Provider.discovery``), each turning that
server's model list into the same ``ModelInfo`` (spec §3.1):

=================  =====================  ===========================================
parser (source)    routes                 fills
=================  =====================  ===========================================
``lmstudio_v1``    GET /api/v1/models     everything, as v0.18 did (unchanged)
``openai_models``  GET /v1/models         ids; vLLM's ``max_model_len`` as the served
                                          context; always loaded
``llamacpp_props`` GET /v1/models,        ids; ``default_generation_settings.n_ctx``
                   GET /props             as the served context; always loaded
``ollama_show``    GET /api/tags,         ids; ``capabilities`` (``tools``,
                   POST /api/show each,   ``thinking``); ``<arch>.context_length``;
                   GET /api/ps            loaded per ``/api/ps``
=================  =====================  ===========================================

EVERY BODY IS SHAPE-CHECKED. LM Studio taught this in v0.2: a server answers a
route it does not own with 200 and an error body, so a status code proves
nothing. A 200 whose body is another server's list, or an ``{"error": ...}``
object, raises ``NotAModelList`` naming the provider -- never half-parsed into
models with no capabilities and no context.

DECLARED FACTS FILL ONLY WHAT THE SERVER LEFT EMPTY (``apply_declared``, spec
§3.2). ``llm.declared_models`` maps a model id to ``context``, ``tools``,
``reasoning`` and ``reasoning_default``. A context the server SERVED or
LOADED always wins, because that is the number that truncates; a declaration
beats a trained or advertised window, and ``llm.context_tokens`` answers only
when neither the server nor a declaration sized a model. Tools and
reasoning are filled only for a source that does not report them (LM Studio's
and Ollama's lists do) -- except that a declared ``reasoning`` NARROWS an
Ollama model's reported knob (``NARROWS_REASONING``). A declared id the
server does not list is warned
about and binds nothing: a declaration describes a model, it does not conjure
one.

NO GUESSING FROM NAMES. Nothing in ``/v1/models`` says what a model is, and a
regex over its id would be a fact nobody measured. ``ModelInfo.is_reasoning``
for any model not from LM Studio's list therefore reads only
``reasoning_default``, which only a declaration or Ollama's ``thinking``
capability sets.

``fetch`` is ``ModelRegistry._fetch``: ``fetch(path)`` GETs a route
(``routes.route_url``: the OpenAI list under ``llm.base_url``, the rest under
the server root), ``fetch(path, body)`` POSTs JSON to one.

ONE MODEL'S FAILURE COSTS THAT MODEL. The shape rule is about the LIST: a
list route that answers the wrong shape fails discovery. Ollama's per-model
``/api/show`` is not the list, so one model whose show errors or 404s is
skipped with a WARNING and the rest are still listed. It is the tests'
discovery pin, so the pin covers every provider.

Version: v0.1.0 [2026-09-29]
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Callable, Mapping, Optional

import httpx

from engine.llm.providers import Provider
from engine.llm.registry import ModelInfo, NotAModelList
from engine.llm.routes import (
    LLAMACPP_PROPS_PATH,
    MODELS_PATH,
    OLLAMA_PS_PATH,
    OLLAMA_SHOW_PATH,
    OLLAMA_TAGS_PATH,
    OPENAI_MODELS_PATH,
)

logger = logging.getLogger(__name__)

#: ``fetch(path)`` GETs, ``fetch(path, body)`` POSTs; both return parsed JSON.
Fetch = Callable[..., Any]

# The ``ModelInfo.source`` values, one per parser. What a declaration filled
# is ``ModelInfo.declared_fields``, beside the source and never over it.
SOURCE_LMSTUDIO = "lmstudio_v1"
SOURCE_OPENAI = "openai_models"
SOURCE_LLAMACPP = "llamacpp_props"
SOURCE_OLLAMA = "ollama_show"

#: Sources whose list itself says whether a model takes tools and reasoning.
#: A declaration never overrides them.
REPORTS_CAPABILITIES: frozenset[str] = frozenset({SOURCE_LMSTUDIO, SOURCE_OLLAMA})

#: Sources whose reported reasoning knob a declaration may NARROW. Ollama's
#: `thinking` capability says a knob exists and nothing about its values: the
#: parser reads it as ``off``/``on``, which a model like gpt-oss contradicts
#: (it takes ``think: "low" | "medium" | "high"`` and, per Ollama's docs,
#: reasons whatever ``true``/``false`` says). A declared ``reasoning`` list
#: replaces those options for a model that reports the knob; it never grants
#: one to a model that does not. LM Studio's list names its options itself,
#: and is never overridden.
NARROWS_REASONING: frozenset[str] = frozenset({SOURCE_OLLAMA})

#: Each parser's primary list route, under the server root.
LIST_PATHS: dict[str, str] = {
    SOURCE_LMSTUDIO: MODELS_PATH,
    SOURCE_OPENAI: OPENAI_MODELS_PATH,
    SOURCE_LLAMACPP: OPENAI_MODELS_PATH,
    SOURCE_OLLAMA: OLLAMA_TAGS_PATH,
}


#: What each parser's list is called, in a log line a person reads.
LIST_NAMES: dict[str, str] = {
    SOURCE_LMSTUDIO: "the v1 model list",
    SOURCE_OPENAI: "the OpenAI-compatible model list",
    SOURCE_LLAMACPP: "llama-server's model list",
    SOURCE_OLLAMA: "Ollama's model list",
}


def empty_model_list(source: str) -> dict[str, Any]:
    """The primary list route's answer with nothing installed, in its own shape."""
    if source in (SOURCE_LMSTUDIO, SOURCE_OLLAMA):
        return {"models": []}
    return {"object": "list", "data": []}


def _describe(payload: Any) -> str:
    """Name what came back, for an error a person can act on."""
    if isinstance(payload, dict):
        if isinstance(payload.get("error"), (dict, str)):
            return "an error body (the server does not serve this route)"
        if isinstance(payload.get("data"), list):
            return (
                "the OpenAI-compat shape ({'data': [{'id': ...}]}), which is "
                "/v1/models answering for a route it does not own"
            )
        models = payload.get("models")
        if isinstance(models, list):
            first = next((m for m in models if isinstance(m, dict)), {})
            if "key" in first:
                return "LM Studio's v1 model list ({'models': [{'key': ...}]})"
            if "name" in first or "model" in first:
                return "Ollama's model list ({'models': [{'name': ...}]})"
        return f"a JSON object with keys {sorted(payload)[:6]}"
    return f"{type(payload).__name__}"


def _refuse(provider: str, path: str, wanted: str, payload: Any) -> NotAModelList:
    return NotAModelList(
        provider,
        payload,
        f"{path} did not answer with {provider}'s model list ({wanted}); "
        f"it returned {_describe(payload)}",
    )


def _error_body(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("error"), (dict, str))


# -- LM Studio (unchanged from v0.18's registry) --------------------------------


def _quant_name(raw: Any) -> str:
    """v1 reports quantization as ``{"name", "bits_per_weight"}``."""
    if isinstance(raw, dict):
        return str(raw.get("name") or "")
    return str(raw or "")


def _loaded_context(instances: Any) -> int:
    """
    The context an instance was ACTUALLY loaded with.

    v1 nests it: ``loaded_instances[].config.context_length``. It is the number
    to budget against -- the live gemma4 advertises 262,144 and is resident at
    160,768.
    """
    best = 0
    for instance in instances or []:
        if not isinstance(instance, dict):
            continue
        config = instance.get("config") or {}
        if isinstance(config, dict):
            best = max(best, int(config.get("context_length") or 0))
    return best


def _capabilities(raw: Any) -> tuple[tuple[str, ...], str, bool, tuple[str, ...]]:
    """
    Flatten v1's capability OBJECT into the flat names the engine asks about.

    ``/api/v0/models`` gave a list of strings; v1 gives
    ``{"vision": bool, "trained_for_tool_use": bool, "reasoning": {...}}``.
    Returns (names, reasoning_default, configurable, options).
    """
    if not isinstance(raw, dict):
        return (), "", False, ()
    names: list[str] = []
    if raw.get("trained_for_tool_use"):
        names.append("tool_use")
    if raw.get("vision"):
        names.append("vision")
    reasoning = raw.get("reasoning")
    default = ""
    options: tuple[str, ...] = ()
    # The PRESENCE of the block is its own fact, and the one this parser used
    # to throw away: it is what says whether the `reasoning` parameter may be
    # sent at all. See ModelInfo.reasoning_configurable.
    configurable = isinstance(reasoning, dict)
    if configurable:
        default = str(reasoning.get("default") or "")
        raw_options = reasoning.get("allowed_options")
        if isinstance(raw_options, (list, tuple)):
            options = tuple(str(o) for o in raw_options if o)
    return tuple(names), default, configurable, options


def _lmstudio_entry(raw: dict[str, Any]) -> ModelInfo:
    """One entry of ``GET /api/v1/models``."""
    caps, reasoning_default, configurable, options = _capabilities(
        raw.get("capabilities")
    )
    instances = raw.get("loaded_instances") or []
    return ModelInfo(
        # `key`, not `id`. The value is the same string the chat routes want.
        id=str(raw.get("key", "")),
        type=str(raw.get("type", "llm")),
        arch=str(raw.get("architecture") or ""),
        publisher=str(raw.get("publisher") or ""),
        quantization=_quant_name(raw.get("quantization")),
        # v1 has no `state` field: residency IS the instance list.
        state="loaded" if instances else "not-loaded",
        max_context_length=int(raw.get("max_context_length") or 0),
        loaded_context_length=_loaded_context(instances),
        capabilities=caps,
        reasoning_default=reasoning_default,
        reasoning_configurable=configurable,
        reasoning_options=options,
        source=SOURCE_LMSTUDIO,
    )


def parse_lmstudio_v1(payload: Any) -> list[ModelInfo]:
    """
    Turn a ``/api/v1/models`` body into models, or refuse it.

    Raises:
        NotAModelList: The body is not the v1 shape. This is the check that a
            status code cannot do -- see ``engine/llm/registry.py``.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise NotAModelList(
            "lmstudio",
            payload,
            f"{MODELS_PATH} did not answer with the v1 model list "
            f"({{'models': [...]}}); it returned {_describe(payload)}",
        )
    entries = [e for e in payload["models"] if isinstance(e, dict)]
    # An empty list is a legitimate answer: a server with nothing installed.
    if entries and not any(e.get("key") for e in entries):
        raise NotAModelList(
            "lmstudio",
            payload,
            f"{MODELS_PATH} answered with a 'models' array whose entries carry "
            "no 'key' -- this is not the v1 REST API",
        )
    return [_lmstudio_entry(e) for e in entries]


# -- the OpenAI-compatible list: vLLM, llama-server, generic --------------------


def parse_openai_models(payload: Any, provider: str) -> list[ModelInfo]:
    """
    ``GET /v1/models``: ``{"object": "list", "data": [{"id": ...}, ...]}``.

    Ids, and vLLM's ``max_model_len`` -- the context the model is SERVED with
    (``--max-model-len``), which is the one that truncates -- where the server
    reports it. Nothing else here says what a model can do. A model in this
    list is being served, so it is loaded.

    Raises:
        NotAModelList: The body is an error, or another server's list.
    """
    wanted = "{'object': 'list', 'data': [{'id': ...}]}"
    if (
        not isinstance(payload, dict)
        or _error_body(payload)
        or not isinstance(payload.get("data"), list)
        or payload.get("object", "list") != "list"
    ):
        raise _refuse(provider, OPENAI_MODELS_PATH, wanted, payload)
    entries = [e for e in payload["data"] if isinstance(e, dict)]
    if entries and not all(isinstance(e.get("id"), str) and e["id"] for e in entries):
        raise _refuse(provider, OPENAI_MODELS_PATH, wanted, payload)
    models = []
    for entry in entries:
        served = int(entry.get("max_model_len") or 0)
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        models.append(
            ModelInfo(
                id=entry["id"],
                publisher=str(entry.get("owned_by") or ""),
                state="loaded",
                # llama-server's `meta.n_ctx_train` is what the weights were
                # trained to; the served context comes from /props.
                max_context_length=int(meta.get("n_ctx_train") or served or 0),
                loaded_context_length=served,
                source=SOURCE_OPENAI,
            )
        )
    return models


def parse_llamacpp_props(payload: Any, provider: str = "llamacpp") -> int:
    """
    ``GET /props``: the context each slot was started with (``-c``).

    Raises:
        NotAModelList: The body is an error, or has no
            ``default_generation_settings``.
    """
    settings = payload.get("default_generation_settings") if isinstance(payload, dict) else None
    if _error_body(payload) or not isinstance(settings, dict):
        raise _refuse(
            provider,
            LLAMACPP_PROPS_PATH,
            "{'default_generation_settings': {'n_ctx': ...}}",
            payload,
        )
    return int(settings.get("n_ctx") or 0)


# -- Ollama ---------------------------------------------------------------------


def _ollama_name(entry: dict[str, Any]) -> str:
    return str(entry.get("name") or entry.get("model") or "")


def parse_ollama_tags(
    payload: Any, provider: str = "ollama", path: str = OLLAMA_TAGS_PATH
) -> list[dict[str, Any]]:
    """
    ``GET /api/tags`` (and ``GET /api/ps``, the same shape):
    ``{"models": [{"name": ..., "model": ..., "details": {...}}]}``.

    Returns the entries, each with a name. LM Studio's list shares the
    ``models`` key but names its entries by ``key``; it is refused. So is
    llama-server's ``/v1/models``, which carries an Ollama-style ``models``
    array beside its OpenAI ``data`` one: Ollama's list never has ``data``.

    Raises:
        NotAModelList: The body is an error, or another server's list.
    """
    wanted = "{'models': [{'name': ...}]}"
    if (
        not isinstance(payload, dict)
        or _error_body(payload)
        or not isinstance(payload.get("models"), list)
        or "data" in payload
    ):
        raise _refuse(provider, path, wanted, payload)
    entries = [e for e in payload["models"] if isinstance(e, dict)]
    if entries and not all(_ollama_name(e) for e in entries):
        raise _refuse(provider, path, wanted, payload)
    return entries


def _ollama_context(model_info: dict[str, Any], arch: str) -> int:
    value = model_info.get(f"{arch}.context_length") if arch else None
    if value is None:
        # An architecture key that does not match `general.architecture`
        # still names the trained window.
        value = next(
            (v for k, v in model_info.items() if str(k).endswith(".context_length")),
            0,
        )
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_ollama_show(
    name: str,
    payload: Any,
    *,
    tag: Optional[dict[str, Any]] = None,
    loaded: bool = False,
    num_ctx: int = 0,
    provider: str = "ollama",
) -> ModelInfo:
    """
    ``POST /api/show`` for one model, as a ``ModelInfo``.

    * ``capabilities``: ``tools`` is tool use, ``thinking`` is a reasoning
      knob (``think: true | false``, so options ``off`` and ``on``, and the
      model thinks unless told not to), ``embedding`` without ``completion``
      is not a chat model.
    * ``model_info["<arch>.context_length"]`` is the trained window.
    * The usable context is the ``num_ctx`` the engine sends with every request
      (spec §6) -- ``num_ctx`` here, the declared context or
      ``llm.context_tokens`` -- capped by that window. Ollama's own default
      is a few thousand tokens and it truncates a longer prompt from the
      front, silently, so the engine always names the number.

    Raises:
        NotAModelList: The body is an error, or carries neither
            ``capabilities`` nor ``model_info``.
    """
    if (
        not isinstance(payload, dict)
        or _error_body(payload)
        or not (
            isinstance(payload.get("capabilities"), list)
            or isinstance(payload.get("model_info"), dict)
        )
    ):
        raise _refuse(
            provider,
            OLLAMA_SHOW_PATH,
            "{'capabilities': [...], 'model_info': {...}}",
            payload,
        )
    caps = [str(c) for c in payload.get("capabilities") or []]
    model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    if not details and isinstance(tag, dict) and isinstance(tag.get("details"), dict):
        details = tag["details"]
    arch = str(model_info.get("general.architecture") or details.get("family") or "")
    trained = _ollama_context(model_info, arch)
    usable = min(num_ctx, trained) if (num_ctx and trained) else (num_ctx or trained)
    names: list[str] = []
    if "tools" in caps:
        names.append("tool_use")
    if "vision" in caps:
        names.append("vision")
    thinking = "thinking" in caps
    return ModelInfo(
        id=name,
        type="embedding" if ("embedding" in caps and "completion" not in caps) else "llm",
        arch=arch,
        quantization=str(details.get("quantization_level") or ""),
        state="loaded" if loaded else "not-loaded",
        max_context_length=trained,
        loaded_context_length=usable,
        capabilities=tuple(names),
        reasoning_default="on" if thinking else "",
        reasoning_configurable=thinking,
        reasoning_options=("off", "on") if thinking else (),
        source=SOURCE_OLLAMA,
    )


# -- one entry point per provider ----------------------------------------------


def parse_list(provider: Provider, payload: Any) -> list[ModelInfo]:
    """
    The primary list route's body as models, with no further request.

    What a liveness check needs (``registry.probe_models``): the shape is
    right, and how many models there are. Ollama's entries carry no
    capabilities until ``/api/show`` is asked.
    """
    source = provider.discovery.value
    if source == SOURCE_LMSTUDIO:
        return parse_lmstudio_v1(payload)
    if source in (SOURCE_OPENAI, SOURCE_LLAMACPP):
        return parse_openai_models(payload, provider.name)
    if source == SOURCE_OLLAMA:
        return [
            ModelInfo(id=_ollama_name(e), source=SOURCE_OLLAMA)
            for e in parse_ollama_tags(payload, provider.name)
        ]
    raise ValueError(f"no discovery parser named {source!r}")


def _declared_context(declared: Mapping[str, Any], model_id: str) -> int:
    entry = declared.get(model_id)
    if isinstance(entry, Mapping):
        try:
            return int(entry.get("context") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def list_models(
    provider: Provider,
    fetch: Fetch,
    *,
    declared: Optional[Mapping[str, Any]] = None,
    context_tokens: int = 0,
) -> list[ModelInfo]:
    """
    Ask the server what it has, in its own routes, and apply the declarations.

    Args:
        provider: The configured row; its ``discovery`` cell names the parser.
        fetch: ``ModelRegistry._fetch``.
        declared: ``llm.declared_models``.
        context_tokens: ``llm.context_tokens``: Ollama's ``num_ctx`` when no
            context is declared, and the context of any other non-LM Studio
            model neither the server nor a declaration sized.

    Raises:
        NotAModelList: A body was not that server's shape.
    """
    declared = declared or {}
    source = provider.discovery.value
    path = LIST_PATHS.get(source)
    if path is None:
        raise ValueError(f"no discovery parser named {source!r}")
    payload = fetch(path)

    if source == SOURCE_LMSTUDIO:
        models = parse_lmstudio_v1(payload)
    elif source == SOURCE_OPENAI:
        models = parse_openai_models(payload, provider.name)
    elif source == SOURCE_LLAMACPP:
        models = parse_openai_models(payload, provider.name)
        if models:
            n_ctx = parse_llamacpp_props(fetch(LLAMACPP_PROPS_PATH), provider.name)
            if n_ctx:
                models = [
                    replace(m, loaded_context_length=n_ctx, source=SOURCE_LLAMACPP)
                    for m in models
                ]
            else:
                models = [replace(m, source=SOURCE_LLAMACPP) for m in models]
    else:  # SOURCE_OLLAMA
        tags = parse_ollama_tags(payload, provider.name)
        loaded: set[str] = set()
        if tags:
            resident = parse_ollama_tags(fetch(OLLAMA_PS_PATH), provider.name, OLLAMA_PS_PATH)
            loaded = {_ollama_name(e) for e in resident}
        models = []
        for tag in tags:
            name = _ollama_name(tag)
            declared_ctx = _declared_context(declared, name)
            try:
                model = parse_ollama_show(
                    name,
                    fetch(OLLAMA_SHOW_PATH, {"model": name}),
                    tag=tag,
                    loaded=name in loaded,
                    num_ctx=declared_ctx or int(context_tokens or 0),
                    provider=provider.name,
                )
                if declared_ctx and model.loaded_context_length == declared_ctx:
                    # The num_ctx the engine will send came from the owner's
                    # declaration, so the context is the declaration's even
                    # though it lands as the "loaded" number here --
                    # `apply_declared` then sees it filled and records nothing.
                    # A declaration the trained window capped did not set the
                    # number, and is not credited with it.
                    model = replace(
                        model,
                        source=model.source,
                        declared_fields=tuple(
                            dict.fromkeys(model.declared_fields + ("context",))
                        ),
                    )
                models.append(model)
            except (NotAModelList, httpx.HTTPError, ValueError) as exc:
                # One model's facts failing costs that model, not the list
                # (deleted between /api/tags and /api/show, a broken manifest,
                # a 200 whose body is not JSON at all -- a proxy's HTML page).
                logger.warning(
                    "[discovery] Model skipped: its %s failed, so nothing is "
                    "known of it and nothing binds to it (operation=list_models, "
                    "provider=%s, model=%s): %s",
                    OLLAMA_SHOW_PATH,
                    provider.name,
                    name,
                    exc,
                )

    models = apply_declared(models, declared)
    if source != SOURCE_LMSTUDIO and context_tokens:
        # Neither the server nor a declaration sized it: budget on the
        # configured window rather than on a number nobody chose.
        models = [
            replace(m, max_context_length=int(context_tokens))
            if not m.loaded_context_length and not m.max_context_length
            else m
            for m in models
        ]
    return models


def _reasoning_options(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, (list, tuple)):
        return tuple(str(o) for o in raw if o)
    return ()


def apply_declared(
    models: list[ModelInfo], declared: Optional[Mapping[str, Any]]
) -> list[ModelInfo]:
    """
    Fill what the server left empty from ``llm.declared_models`` (spec §3.2).

    Per model id: ``context`` fills the context the budget uses whenever the
    server reported no SERVED or LOADED one (that number always wins: it is
    the one that truncates; a trained or advertised window does not beat a
    declaration); ``tools``, ``reasoning`` (the values the knob accepts) and
    ``reasoning_default`` fill only for a source that does not report
    capabilities (``REPORTS_CAPABILITIES``); for a source in
    ``NARROWS_REASONING`` (Ollama) a declared ``reasoning`` list replaces the
    options of a model that reports the knob, and never grants one. What was
    filled is named in
    ``ModelInfo.declared_fields``; ``source`` stays the parser's. A
    ``reasoning_off_trusted: false`` is named there too (it fills nothing; it
    is read per request, ``providers._declared_untrusted``).

    Precedence for the context, every provider alike: reported (served or
    loaded) > declared > ``llm.context_tokens`` (``list_models``).

    A declared id the server does not list is logged as a WARNING and dropped:
    nothing is ever bound to a model the server did not name.
    """
    if not declared:
        return list(models)
    listed = {m.id for m in models}
    for model_id in declared:
        if model_id not in listed:
            logger.warning(
                "[discovery] Declared model is not on the server; its "
                "declaration is ignored and nothing binds to it "
                "(operation=apply_declared, model=%s, listed=%s)",
                model_id,
                sorted(listed) or "none",
            )

    out: list[ModelInfo] = []
    for model in models:
        entry = declared.get(model.id)
        if not isinstance(entry, Mapping):
            out.append(model)
            continue
        changes: dict[str, Any] = {}
        filled: list[str] = []
        context = _declared_context(declared, model.id)
        # Only a SERVED or LOADED number beats a declaration. A trained or
        # advertised window (`max_context_length`: llama-server's
        # n_ctx_train, an unloaded LM Studio model's maximum) is not what
        # truncates the prompt, so the owner's word wins over it.
        if context and not model.loaded_context_length:
            changes["loaded_context_length"] = context
            filled.append("context")
        if model.source not in REPORTS_CAPABILITIES:
            if "tools" in entry and bool(entry["tools"]) and "tool_use" not in model.capabilities:
                changes["capabilities"] = model.capabilities + ("tool_use",)
                filled.append("tools")
            options = _reasoning_options(entry.get("reasoning"))
            if options and not model.reasoning_configurable:
                changes["reasoning_configurable"] = True
                changes["reasoning_options"] = options
                filled.append("reasoning")
            default = str(entry.get("reasoning_default") or "")
            if default and not model.reasoning_default:
                changes["reasoning_default"] = default
                filled.append("reasoning_default")
        elif model.source in NARROWS_REASONING:
            options = _reasoning_options(entry.get("reasoning"))
            if options and model.reasoning_configurable:
                changes["reasoning_options"] = options
                filled.append("reasoning")
            elif options:
                logger.warning(
                    "[discovery] Declared reasoning ignored: the server reports "
                    "no reasoning knob for this model, and a declaration only "
                    "narrows one (operation=apply_declared, model=%s)",
                    model.id,
                )
        if entry.get("reasoning_off_trusted") is False:
            # Read per request by providers._declared_untrusted; recorded here
            # so the model's provenance names it like every other declaration
            # (and the doctor can say where it is ignored: LM Studio).
            filled.append("reasoning_off_trusted")
        if changes or filled:
            # The parser stays the source: a declaration is recorded beside
            # it, never over it, so LM Studio's arch checks still key on it.
            model = replace(
                model,
                declared_fields=tuple(dict.fromkeys(model.declared_fields + tuple(filled))),
                **changes,
            )
        out.append(model)
    return out
