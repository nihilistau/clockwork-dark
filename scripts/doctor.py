"""
Health check — the first thing to run when something is wrong.

Probes every external service, validates the content tree, and reports what
each failure actually costs you in play. The point is to answer "why is the
game doing that?" without reading a log.

    python scripts/doctor.py
    python scripts/doctor.py --verbose

The Games section reports which game is active and validates every manifest on
disk -- not only the active one, since a manifest with a missing path is a
launch that will fail and this is where that should be found.

The State section does the same for ``games/<slug>/state.yaml``. A malformed
schema is FATAL at load (``engine/state/schema.py`` raises rather than guessing),
so without this check the first sign of a typo in a story's meters is the game
refusing to start with a traceback -- which is exactly the class of failure a
doctor exists to find first.

The model server's section (``LM Studio``, or ``Model server (<provider>)``
since v0.19.0) asks TWO questions, because they have different answers: a
liveness ping, and a real bounded completion. The ping used to be the whole
check, and it passed on a server that refused every chat call. The model
server is the one FAIL-level service, whatever its provider.

Exit code 0 if nothing is broken, 1 if something is.

Version: v0.5.0 [2026-08-13]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, WARN, FAIL = "ok", "warn", "fail"

GLYPH = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}


class Report:
    """Collects check results and prints them grouped."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, section: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append((section, name, status, detail))

    @property
    def failed(self) -> bool:
        return any(status == FAIL for _, _, status, _ in self.rows)

    def render(self) -> str:
        out: list[str] = []
        width = max((len(n) for _, n, _, _ in self.rows), default=12)
        current = None
        for section, name, status, detail in self.rows:
            if section != current:
                out.append(f"\n{section}")
                current = section
            out.append(f"  {GLYPH[status]}  {name:<{width}}  {detail}")
        return "\n".join(out)


#: Where the case probe runs by default: the checkout itself, because that is
#: the filesystem whose case matters (a Docker Desktop bind mount of NTFS is
#: case-insensitive inside a Linux container whose /tmp is not).
REPO_ROOT = Path(__file__).resolve().parent.parent

#: The first Windows 11 build. Windows 11 still answers "10" to
#: ``platform.release()`` on the Pythons this project supports.
WINDOWS_11_BUILD = 22000


def case_sensitive_filesystem(directory: Optional[Path] = None) -> Optional[bool]:
    """
    Whether the filesystem holding ``directory`` (the repository root by
    default) tells ``CaseProbe`` from ``caseprobe``. A temporary directory is
    made there (``.clockwork-case-probe-*``), a mixed-case file is written in
    it and looked up by its lower-cased name, and the directory is removed
    again whatever happens. None when the probe cannot be made (an unwritable
    or missing directory).
    """
    import tempfile

    base = REPO_ROOT if directory is None else directory
    try:
        with tempfile.TemporaryDirectory(prefix=".clockwork-case-probe-", dir=base) as tmp:
            probe = Path(tmp) / "CaseProbe"
            probe.write_bytes(b"")
            return not (Path(tmp) / "caseprobe").exists()
    except OSError:
        return None


def os_release() -> str:
    """The system and its release as a person would name it: ``Windows 11
    (build 26200)`` where ``platform.release()`` says ``10``, else
    ``platform.system()`` and ``platform.release()``."""
    import platform

    system = platform.system()
    if system == "Windows" and hasattr(sys, "getwindowsversion"):
        build = sys.getwindowsversion().build
        release = platform.release()
        if release == "10" and build >= WINDOWS_11_BUILD:
            release = "11"
        return f"Windows {release} (build {build})"
    return f"{system} {platform.release()}"


def platform_detail(directory: Optional[Path] = None) -> str:
    """The ``platform`` row: the system, its release, and whether filenames
    differ by case in the checkout (``directory``, the repository root by
    default). Informational -- both answers are supported (AGENTS.md rule 11),
    which is why the row is always OK.

    A READ-ONLY CHECKOUT (a container image's ``/app``, a read-only mount)
    cannot hold the probe's directory, so the default probe falls back to the
    storage root (``engine/persistence/storage.py::data_root``), which the
    engine must be able to write anyway, and the row says which was probed
    (v0.20.0 T5; it said "unknown" there before)."""
    sensitive = case_sensitive_filesystem(directory)
    where = "the checkout"
    if sensitive is None and directory is None:
        fallback = _storage_root()
        if fallback is not None:
            sensitive = case_sensitive_filesystem(fallback)
            if sensitive is not None:
                where = f"the storage root {fallback} (the checkout could not be probed)"
    if sensitive is None:
        tried = "the checkout" if directory is not None else "the checkout and the storage root"
        case = f"filesystem case unknown (probe under {tried} failed)"
    else:
        case = f"{'case-sensitive' if sensitive else 'case-insensitive'} filesystem under {where}"
    return f"{os_release()}, {case}"


def _storage_root() -> Optional[Path]:
    """The storage root the engine resolves, or None if it cannot be read."""
    try:
        from engine.persistence.storage import data_root

        return data_root()
    except Exception:  # noqa: BLE001 -- the platform row must never fail the doctor
        return None


def check_python(report: Report) -> None:
    version = sys.version_info
    status = OK if version >= (3, 11) else FAIL
    report.add("Runtime", "python", status, f"{version.major}.{version.minor}.{version.micro}")
    report.add("Runtime", "platform", OK, platform_detail())

    for module in ("flask", "flask_socketio", "httpx", "yaml"):
        try:
            __import__(module)
            report.add("Runtime", module, OK, "installed")
        except ImportError:
            report.add("Runtime", module, FAIL, "missing — run pip install -r requirements.txt")

    # Optional. Absent is a reduced feature, not a broken checkout, so it is a
    # WARN and it says what it costs. See the Voice section for whether the
    # configured provider actually needs it.
    optional = {
        "faster_whisper": "push-to-talk transcription (stt.provider: faster_whisper)",
    }
    for module, feature in optional.items():
        try:
            __import__(module)
            report.add("Runtime", module, OK, f"installed — {feature}")
        except ImportError:
            report.add("Runtime", module, WARN, f"not installed — no {feature}")


def check_services(report: Report) -> None:
    from engine.stack import (
        MODEL_SERVER_NAMES,
        STATUS_DISABLED,
        STATUS_DOWN,
        STATUS_FAILED,
        StackManager,
    )

    consequences = {
        "lmstudio": "no narration - the Storyteller falls back to a canned line",
        # The model server under any other provider (v0.19.0).
        "llm": "no narration - the model server is down, so the Storyteller "
        "falls back to a canned line",
        "voxtral_tts": "no spoken narration (off by default anyway)",
        "voxtral_asr": (
            "no push-to-talk on the voxtral_http provider - switch "
            "stt.provider to faster_whisper, which needs no server"
        ),
        "comfyui": "no live image generation - the shipped art pack still works",
        "grok": "no live image generation - the shipped art pack still works",
    }

    for status in StackManager().status():
        if status.status == STATUS_DISABLED:
            report.add("Services", status.name, OK, "disabled in config")
        elif status.status in (STATUS_DOWN, STATUS_FAILED):
            # Only the model server genuinely breaks the game, whatever its
            # provider; everything else degrades.
            level = FAIL if status.name in MODEL_SERVER_NAMES else WARN
            report.add("Services", status.name, level,
                       f"{status.detail} -> {consequences.get(status.name, 'reduced features')}")
        else:
            report.add("Services", status.name, OK, status.detail)


def check_llm(report: Report) -> None:
    """
    Two questions about LM Studio, asked separately because they have different
    answers.

    THE DEFECT THIS CLOSES. ``GET /v1/models`` was the whole health check, and
    it answers "is a process listening" -- which was true on this machine while
    every chat call was refused. The doctor said ``ok``, the planner's failures
    were swallowed, the pipeline degraded to canned lines, and nothing in the
    health report pointed anywhere near the model. A check that passes while the
    thing it checks cannot do its job is worse than no check.

    So: the liveness ping stays, cheap and clearly labelled as liveness, and a
    bounded real completion sits under it reporting what actually came back --
    including the model id the request named, which is where a failed discovery
    shows up as the fictional placeholder it is.

    THE SECOND ROUND OF THE SAME DEFECT. That liveness ping asked ``/v1/models``,
    which LM Studio does not serve -- it answered 200 and logged
    ``Unexpected endpoint or method``, once per doctor run. It also could not
    fail: this server returns 200 for any unknown path under ``/v1``. It now
    asks ``GET /api/v1/models`` and validates the SHAPE of the body
    (``engine/llm/registry.probe_models``), which is the only part of the
    answer that can distinguish a real LM Studio from a 200.

    EVERY PROVIDER (v0.19.0, spec §8). The section is the configured model
    server's: ``LM Studio`` for LM Studio (its rows byte for byte v0.18's,
    pinned by ``tests/fixtures/llm/golden_lmstudio/doctor_llm.txt``), else
    ``Model server (<provider>)``. The rows: liveness (the provider row's
    health probe), the model bound, the chat probe, the transport (LM
    Studio's native route; elsewhere the reasoning-off patch, trusted or not),
    the grammar rung, inline ``<think>`` seen, any set key the provider
    ignores, and MCP.
    """
    from engine.llm.providers import get_provider

    row = get_provider()
    _check_llm_server(report, row)
    _check_llm_keys(report, row)


def _check_llm_server(report: Report, row: object) -> None:
    """The rows that ask the server (``check_llm``)."""
    section = row.section

    # 1. Liveness. Says nothing about whether a turn can be narrated.
    alive, detail = row.health_probe(timeout=3.0)
    report.add(section, "liveness", OK if alive else FAIL, detail)
    if not alive:
        return

    # 2. Can it actually complete anything? This is the question that matters.
    from engine.llm.backend import chat_probe

    probe = chat_probe(timeout=20.0)
    label = f"model ({probe['model']})"
    if not probe["bound"]:
        report.add(section, label, FAIL,
                   "not confirmed against the server - discovery failed, so "
                   "every request names a model it has never heard of")
    else:
        report.add(section, label, OK, "resolved from the server's own list")

    status = str(probe["status"])
    level = OK if probe["ok"] else (WARN if status == "timeout" else FAIL)
    report.add(section, "chat probe", level, f"{status}: {probe['detail']}")

    # 3. The transport that carries narration. On LM Studio, tools and
    # structured output can only go OpenAI-compat; only native can turn
    # reasoning off. Every other server has one route, and the question is
    # whether that route can be told to stop thinking.
    if row.chat_transport.value == "lmstudio_routed":
        try:
            from engine.llm.backend import get_backend

            native = get_backend().native_available()
        except Exception as exc:  # noqa: BLE001 -- diagnostics must not crash
            report.add(section, "native /api/v1/chat", WARN, repr(exc))
        else:
            report.add(
                section,
                "native /api/v1/chat",
                OK if native else WARN,
                "available - reasoning can be turned off"
                if native
                else "unavailable - reasoning cannot be disabled, so a thinking "
                     "model can spend the whole token budget and return nothing",
            )
    else:
        _reasoning_off_row(report, row, str(probe["model"]))

    # 4. The grammar rung (spec §4.4). LM Studio's is v0.18's ladder, which
    # its baseline does not show; every other server's was probed.
    if not row.v18_ladder:
        _grammar_row(report, row)

    # 5. Thinking sent inside content (spec §4.5), seen in the probes above.
    if row.inline_think.value == "strip":
        from engine.llm.client import inline_think_seen

        seen = inline_think_seen()
        if seen:
            fix = (
                f"to stop it, {row.inline_think_fix}" if row.inline_think_fix
                else "this server has no flag that stops it"
            )
            report.add(section, "inline <think>", WARN,
                       f"seen in {seen} response(s): the server sends its "
                       "thinking inside content. The engine moves it to the "
                       f"reasoning channel before anything reads it; {fix}")
        else:
            report.add(section, "inline <think>", OK, "none seen in the probes")


def _reasoning_off_row(report: Report, row: object, model: str) -> None:
    """``reasoning off: <patch> (trusted | untrusted) | unavailable`` (§5.1)."""
    import json

    try:
        from engine.llm.client import reasoning_patch
        from engine.llm.discovery import REPORTS_CAPABILITIES
        from engine.llm.registry import get_registry

        patch = reasoning_patch(model, "off")
        info = get_registry().cached(model)
    except Exception as exc:  # noqa: BLE001 -- diagnostics must not crash
        report.add(row.section, "reasoning off", WARN, repr(exc))
        return
    if patch is not None and patch.trusted:
        report.add(row.section, "reasoning off", OK,
                   f"{json.dumps(patch.body, sort_keys=True)} (trusted) - an `off` "
                   "profile's cap spends nothing on thinking")
    elif patch is not None:
        report.add(row.section, "reasoning off", WARN,
                   f"{json.dumps(patch.body, sort_keys=True)} (untrusted) - sent, "
                   "but the cap keeps the reasoning budget, so turns are slower "
                   f"than they need be; declare llm.declared_models.{model}.reasoning "
                   "(docs/MODEL_SERVERS.md) once the model is seen to honour it")
    elif (
        info is not None
        and str(getattr(info, "source", "")) in REPORTS_CAPABILITIES
        and not info.reasoning_configurable
    ):
        report.add(row.section, "reasoning off", OK,
                   "unavailable, and not needed - the server reports no thinking "
                   "knob for this model")
    else:
        report.add(row.section, "reasoning off", WARN,
                   "unavailable - nothing on this route turns thinking off, so a "
                   "thinking model can spend its whole budget and return nothing. "
                   "Declare llm.declared_models.<id>.reasoning, or "
                   "llm.reasoning_off_body on a generic server (docs/MODEL_SERVERS.md)")


def _grammar_row(report: Report, row: object) -> None:
    """Which rung of the structured-output ladder turns go out on (§4.1)."""
    try:
        from engine.llm.backend import RUNG_OBJECT, RUNG_SCHEMA, get_backend

        backend = get_backend()
        rung = backend.structured_rung()
        mode = backend.structured_mode()
    except Exception as exc:  # noqa: BLE001 -- diagnostics must not crash
        report.add(row.section, "grammar rung", WARN, repr(exc))
        return
    how = "probed" if mode == "auto" else "set"
    if rung == RUNG_SCHEMA:
        report.add(row.section, "grammar rung", OK,
                   f"1: json_schema (llm.structured_output: {mode}, {how}) - the "
                   "turn's shape is enforced by the server")
    elif rung == RUNG_OBJECT:
        report.add(row.section, "grammar rung", WARN,
                   f"2: json_object (llm.structured_output: {mode}, {how}) - valid "
                   "JSON is enforced, its shape only asked for in the prompt and "
                   "conformed on arrival")
    else:
        report.add(row.section, "grammar rung", WARN,
                   f"3: none (llm.structured_output: {mode}, {how}) - the shape is "
                   "only asked for in the prompt and conformed on arrival")


def _shipped_llm() -> dict:
    """``config/default.yaml``'s own ``llm:`` block: what "set" is measured from."""
    import yaml

    import engine.config as config

    try:
        with config._DEFAULT_PATH.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    migrated, _ = config.migrate_legacy_llm(raw)
    block = migrated.get("llm")
    return block if isinstance(block, dict) else {}


def _check_llm_keys(report: Report, row: object) -> None:
    """
    The config rows of ``check_llm``: each set key this provider ignores
    (spec §2.1, one WARN each), and the MCP row (spec §7). Asked whether or
    not the server is up -- they are about the config, not the server.
    """
    from engine.config import get_config

    cfg = get_config()
    llm = cfg.section("llm")
    shipped = _shipped_llm()
    section = row.section

    def changed(key: str) -> bool:
        return key in llm and llm.get(key) != shipped.get(key)

    ignored: list[tuple[str, str]] = []
    if row.chat_transport.value != "lmstudio_routed" and changed("prefer_native"):
        ignored.append(("llm.prefer_native",
                        "it has no native route to prefer (LM Studio's alone)"))
    if row.keep_alive.value is None and changed("keep_alive_seconds"):
        ignored.append(("llm.keep_alive_seconds",
                        "it keeps a model loaded by its own settings"))
    if row.reasoning_off.value and llm.get("reasoning_off_body"):
        ignored.append(("llm.reasoning_off_body",
                        "it has its own reasoning-off patch (openai_compat only)"))
    if row.chat_transport.value == "lmstudio_routed":
        declared = llm.get("declared_models") or {}
        for model_id, entry in sorted(declared.items()) if isinstance(declared, dict) else ():
            if isinstance(entry, dict) and "reasoning_off_trusted" in entry:
                ignored.append((
                    f"llm.declared_models.{model_id}.reasoning_off_trusted",
                    "it sends no reasoning-off patch to trust: its compat route "
                    "ignores every knob, and its native route asks the model's "
                    "own reasoning list",
                ))
    for key, why in ignored:
        report.add(section, "ignored key", WARN, f"{key} is set, but {row.title} ignores it: {why}")

    _skipped_key_rows(report, row, cfg)

    if bool(cfg.get("llm.mcp.enabled", False)):
        if row.mcp_integrations.value:
            report.add(section, "mcp", OK,
                       "llm.mcp.enabled - Phase A calls the engine's skills through "
                       f"{row.title}'s native integrations")
        else:
            report.add(section, "mcp", FAIL,
                       f"`llm.mcp.enabled` is set but {row.name} has no MCP "
                       "integrations; Phase A is off")


def _key_source(alternative: str) -> tuple[str, str]:
    """
    A chain alternative as ``(its name as written, "holds a key" | "is set")``:
    ``engine.config.key_source_name``, shared with the admin panel's key row
    since v0.20.0 T16 (moved there; the rows here are unchanged).
    """
    from engine.config import key_source_name

    return key_source_name(alternative)


def _skipped_key_rows(report: Report, row: object, cfg: object) -> None:
    """
    N4 (spec §2.3): one WARN per scoped key source that was SKIPPED but would
    have produced a value -- its file exists and is not empty, or its
    variable is set. Skipping is the design (LM Studio's key is never sent to
    another server); saying so is the fix, since the owner otherwise sees only
    a 401. The source is named, never the value or its length (rule 5).
    """
    from engine.config import ConfigManager, scope_matches, scoped_alternatives
    from engine.llm.providers import PROVIDERS

    raw = cfg._raw("llm.api_key")
    if not (isinstance(raw, str) and raw.startswith("${") and raw.endswith("}")):
        return
    pairs = scoped_alternatives(raw[2:-1])

    def ours(scope: object) -> bool:
        return scope is None or scope_matches(str(scope), row.name)

    usable = [f"`{_key_source(alternative)[0]}`" for scope, alternative in pairs if ours(scope)]
    advice = " or ".join(usable) if usable else "`llm.api_key`"
    for scope, alternative in pairs:
        if ours(scope):
            continue
        if not ConfigManager._expand_one(alternative, None):
            continue
        name, verb = _key_source(alternative)
        owner = next(
            (row_.title for key, row_ in PROVIDERS.items() if scope_matches(scope, key)), scope
        )
        report.add(row.section, "skipped key", WARN,
                   f"`{name}` {verb}, but `llm.provider` is `{row.name}`: it is "
                   f"{owner}'s and is not sent. Put this server's key in {advice}.")


def check_voice(report: Report) -> None:
    """
    Push-to-talk: which provider answers, and whether it can.

    Reported here rather than under Services because the default provider is a
    LIBRARY in this process -- there is no port to health-check and no process
    to start, so a stack entry for it would have to invent one.
    """
    from engine.config import get_config
    from engine.media.stt import (
        PROVIDER_FASTER_WHISPER,
        PROVIDER_VOXTRAL_HTTP,
        resolve_provider_name,
    )

    provider = resolve_provider_name()
    report.add("Voice", "stt provider", OK, provider)

    if provider == PROVIDER_FASTER_WHISPER:
        from engine.media.stt_whisper import WhisperSTTProvider, whisper_installed

        if not whisper_installed():
            report.add("Voice", "faster-whisper", WARN,
                       "not installed - push-to-talk returns a legible error "
                       "instead of a transcript. pip install faster-whisper")
            return
        model, device, compute = WhisperSTTProvider().binding()
        report.add("Voice", "faster-whisper", OK,
                   f"{model} on {device} ({compute}) - the first press pays "
                   "for the model load")
        return

    if provider == PROVIDER_VOXTRAL_HTTP:
        from engine.stack import probe as probe_url

        base = str(get_config().get("stt.base_url", "")).rstrip("/")
        alive, detail = probe_url(f"{base}/v1/models") if base else (False, "no base_url")
        report.add("Voice", "transcription server", OK if alive else WARN,
                   f"{base}: {detail} - no push-to-talk without it"
                   if not alive else f"{base}: {detail}")


def _hosting_row(report: Report, cfg: object) -> None:
    """
    Who can reach the game (spec §3.6). Local mode has no login, and binds
    loopback by default since v0.20.0 (the owner's decision); LAN play is one
    line in config/local.yaml, and this row then says what that exposes, in
    the launcher's own words (``engine.scenes.spec.exposure_warning``).
    """
    from engine.scenes.spec import DEFAULT_SCENE_NAME, exposure_warning, scene_host, scene_port

    host = scene_host(DEFAULT_SCENE_NAME)
    if bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        from engine.scenes.spec import is_loopback

        if os.environ.get("CLOCKWORK_ENV", "").strip() == "docker" and is_loopback(host):
            # In the image (T18 fix round 1, I1): the published port reaches
            # the container's interface, never its loopback.
            report.add("Config", "hosting", WARN,
                       f"the front door binds the container's loopback ({host}): the published port "
                       "reaches nothing. Remove scene.clockwork.host from /data/config.yaml; "
                       "publish 127.0.0.1:5573:5573 instead (docs/HOSTING.md § Docker)")
            return
        # Hosted (v0.20.0 T18): every request needs a login, so a LAN bind
        # is the point, not an exposure; the rows below say how it is set up.
        report.add("Config", "hosting", OK,
                   f"hosted: the front door on {host}:{scene_port(DEFAULT_SCENE_NAME)}, "
                   "every request behind a login")
        return
    warning = exposure_warning(host, scene_port(DEFAULT_SCENE_NAME))
    if not warning:
        report.add("Config", "hosting", OK, f"local single-player on {host}")
    else:
        report.add("Config", "hosting", WARN, warning)


#: Where a reader of the lanes row is told to look for its number (spec §5.3).
LANES_HINT = (
    "set narration to the requests your model server really runs at once "
    "(LM Studio: its parallel-requests setting; vLLM: batches natively, 4 is a sane start; "
    "llama-server: --parallel; Ollama: OLLAMA_NUM_PARALLEL) - the rest queue in order"
)

#: The production server row's words on Windows (spec §7.4).
WINDOWS_SERVER_WARNING = (
    "gunicorn does not run on Windows: use Docker, or accept the development server for a trial"
)


def _on_windows() -> bool:
    """Whether this is Windows, where gunicorn cannot run (its own seam, for the tests)."""
    return os.name == "nt"


def _hosted_rows(report: Report, cfg: object) -> None:
    """
    Hosted mode only (spec §7.4, v0.20.0 T18): how the service is set up.

    - ``hosting block``: the closed ``hosting:`` schema, as the instance reads
      it (a FAIL names the key, and the rows that need it are skipped);
    - ``secret key``: where the login cookie's key comes from -- the
      environment, a config file, or the generated file -- never the value;
    - ``cookie_secure`` (WARN when false), ``public_origin`` and
      ``trusted_proxies``, shown;
    - ``refusals``: a FAIL for each §6.7 startup refusal that would fire (the
      studio, ``llm.mcp.enabled``); the Settings panel's POST is a 403, said;
    - ``production server``: WARN on Windows, where gunicorn does not run;
      on POSIX, whether gunicorn is installed;
    - ``llm.lanes``: shown, with the sizing hint.

    Read and probed, never served: the doctor asks no live process anything.
    """
    if not bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        return
    from engine.hosting import refuse_unsupported
    from engine.hosting.auth import SECRET_KEY_FILE
    from engine.hosting.config import HostingConfigError, load
    from engine.persistence.storage import hosting_dir

    try:
        settings = load(cfg)
    except HostingConfigError as exc:
        report.add("Config", "hosting block", FAIL, str(exc))
        settings = None
    else:
        report.add("Config", "hosting block", OK, "the hosting: block validates")

    if settings is not None:
        if settings.secret_key:
            kind, name = cfg.secret_source("hosting.secret_key")  # type: ignore[attr-defined]
            where = {"environment": f"the environment ({name})", "file": f"the file {name}",
                     "config": f"a config file ({name})"}.get(kind, "the config")
            report.add("Config", "secret key", OK, f"from {where}")
        else:
            path = hosting_dir() / SECRET_KEY_FILE
            state = "present" if path.is_file() else "made at the first start"
            report.add("Config", "secret key", OK, f"generated: {path} ({state})")

        if settings.cookie_secure:
            report.add("Config", "cookie_secure", OK, "true: the login cookie travels over HTTPS only")
        else:
            report.add("Config", "cookie_secure", WARN,
                       "false: the login cookie is sent over plain HTTP - for a LAN trial only; "
                       "behind TLS set it true")
        report.add("Config", "public_origin", OK,
                   settings.public_origin or '"" - same-origin only')
        proxies = int(settings.trusted_proxies)
        report.add("Config", "trusted_proxies", OK,
                   f"{proxies} - forwarded headers are ignored" if proxies == 0
                   else f"{proxies} - the client address and scheme are read from the last "
                        f"{proxies} proxy hop(s)")

    try:
        refuse_unsupported(cfg)
    except HostingConfigError as exc:
        report.add("Config", "refusals", FAIL, f"hosted mode will not start: {exc}")
    else:
        report.add("Config", "refusals", OK,
                   "the studio and the skills server are off; the Settings panel is read-only "
                   "(POST /api/settings answers 403)")

    if _on_windows():
        report.add("Config", "production server", WARN, WINDOWS_SERVER_WARNING)
    else:
        from engine.hosting.supervisor.process import gunicorn_runs_here

        if gunicorn_runs_here():
            report.add("Config", "production server", OK,
                       "gunicorn: one gthread worker per process (deploy/gunicorn.conf.py)")
        else:
            report.add("Config", "production server", WARN,
                       "gunicorn is not installed (pip install -r requirements-server.txt "
                       "-c constraints.txt): the supervisor serves with the development server")

    from engine.llm.gate import lane_limits

    lanes = lane_limits(cfg.get("llm.lanes", {}) or {})  # type: ignore[attr-defined]
    shown = ", ".join(f"{name} {count}" for name, count in sorted(lanes.items()))
    report.add("Config", "llm.lanes", OK, f"{shown} - {LANES_HINT}")


def _stories_rows(report: Report, cfg: object) -> None:
    """
    Hosted mode only (spec §7.4): ``hosting.stories``, one worker process per
    slug under the supervisor. Each slug is shown; a slug the registry does not
    know or that does not validate is a FAIL, and so is an empty list -- the
    supervisor refuses to start on either, naming the key. Nothing is
    activated, and the live supervisor is not asked.
    """
    if not bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        return
    from engine.hosting.config import story_problems

    raw = cfg.get("hosting.stories", None)  # type: ignore[attr-defined]
    slugs = [str(s) for s in raw] if isinstance(raw, list) else []
    problems = story_problems(slugs)
    for slug, why in problems:
        report.add("Config", "hosting.stories", FAIL,
                   f"{slug!r} {why}" if slug else why)
    if not problems:
        report.add("Config", "hosting.stories", OK,
                   f"{', '.join(slugs)} - one worker process each")


def _admin_rows(report: Report, cfg: object) -> None:
    """
    Hosted mode only (spec §7.4, v0.20.0 T14): the admins, and the admin layer.

    - ``admins``: how many enabled admins ``users.json`` holds (read, never
      written); WARN at zero, when nobody can open the panel.
    - ``admin layer``: ``<storage.root>/hosting/admin.yaml``, read exactly as
      ``get_config`` reads it -- whenever hosting is on, with no variable --
      so this is the layer the instance runs. Its path and the dotted keys it
      sets (keys, never values); a WARN per key ``CLOCKWORK_CONFIG`` also
      sets, which overrides the panel's edit. A key outside the panel's
      allowlist stops ``get_config`` itself, and ``check_config`` reports
      that as this row's FAIL.
    """
    if not bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        return
    from engine.config import admin_layer, external_config_layers
    from engine.hosting.accounts import AccountsFileError, AccountStore
    from engine.persistence.storage import hosting_dir

    try:
        accounts = AccountStore(hosting_dir()).all()
    except AccountsFileError as exc:
        report.add("Config", "accounts", FAIL, str(exc))
        report.add("Config", "admins", FAIL, str(exc))
    else:
        # Spec §7.4 (v0.20.0 T18): with no account, nobody can log in.
        enabled = [a for a in accounts if not a.disabled]
        if enabled:
            report.add("Config", "accounts", OK,
                       f"{len(enabled)} enabled of {len(accounts)}")
        else:
            report.add("Config", "accounts", FAIL,
                       "nobody can log in: python scripts/users.py add <name>")
        admins = [a for a in accounts if a.admin and not a.disabled]
        if admins:
            report.add("Config", "admins", OK, f"{len(admins)} enabled admin(s)")
        else:
            report.add("Config", "admins", WARN,
                       "none - the admin panel is unreachable: python scripts/users.py admin <name> on")

    layer = admin_layer()
    if layer is None:
        report.add("Config", "admin layer", OK,
                   f"{hosting_dir() / 'admin.yaml'}: none yet (the admin panel writes it)")
        return
    path, keys = layer
    report.add("Config", "admin layer", OK, f"{path}: sets {', '.join(keys) or 'nothing'}")
    for source, external in external_config_layers():
        for key in sorted(set(keys) & set(external)):
            report.add("Config", "admin layer", WARN,
                       f"the panel's edit of {key} is overridden by {source}")


#: Below this many threads per process, the ``hosting.threads`` row WARNs.
MIN_HOSTED_THREADS = 8


def _threads_row(report: Report, cfg: object) -> None:
    """
    Hosted mode only (spec §6.9, §7.4, restated for the front door in v0.20.0
    T12): ``hosting.threads`` is every process's pool, the front door's and
    each worker's. Each open WebSocket pins a thread in the front door (its
    relay) AND one in its story's worker, so the front door -- which carries
    EVERY story's sockets -- runs out first: about ``(threads - reserve) / 2``
    players with two tabs each, across all the stories together, with the
    reserve (``limits.RESERVED_THREADS``) kept for HTTP: since v0.20.0 T13 the
    front door counts every relayed WebSocket, polling ``GET`` and HTTP turn
    against ``threads - reserve`` (``limits.LongHolds``) and refuses the next
    at once, so the reserve is real, and every worker is held to it through
    the front door. WARN below ``MIN_HOSTED_THREADS``.
    """
    if not bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        return
    from engine.hosting.limits import RESERVED_THREADS

    try:
        threads = int(cfg.get("hosting.threads", 0))  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return  # the block's own validation names it
    raw = cfg.get("hosting.stories", None)  # type: ignore[attr-defined]
    count = len(raw) if isinstance(raw, list) else 0
    holds = max(1, threads - RESERVED_THREADS)
    players = max(0, (threads - RESERVED_THREADS) // 2)
    try:
        per_account = int(cfg.get("hosting.max_connections_per_account", 0))  # type: ignore[attr-defined]
    except (TypeError, ValueError):
        per_account = 0
    detail = (
        f"{threads} per process; the front door carries every story's WebSockets "
        f"(each pins a thread there and one in its worker), so about {players} players "
        f"with two tabs each across all {count} stories; open WebSockets, polls and "
        f"HTTP turns together hold at most {holds} (one more is refused at once), "
        f"at most {per_account} of them one account's, leaving {RESERVED_THREADS} "
        "threads for HTTP"
    )
    if threads < MIN_HOSTED_THREADS:
        report.add("Config", "hosting.threads", WARN,
                   f"{detail} - below {MIN_HOSTED_THREADS}, a few open tabs fill the front door")
    else:
        report.add("Config", "hosting.threads", OK, detail)


def _metrics_row(report: Report, cfg: object) -> None:
    """
    Hosted mode only (spec §7.4, v0.20.0 T17): the supervisor's metrics store,
    ``<storage.root>/hosting/metrics.sqlite3`` -- its path and whether it can
    be written (the file, or the directory that will hold it), and the
    retention window. Read and probed, never opened: the doctor asks the
    store nothing.
    """
    if not bool(cfg.get("hosting.enabled", False)):  # type: ignore[attr-defined]
        return
    from engine.hosting.supervisor.metrics import FILE_NAME
    from engine.persistence.storage import hosting_dir

    path = hosting_dir() / FILE_NAME
    days = cfg.get("hosting.observability.retention_days", None)  # type: ignore[attr-defined]
    cap = cfg.get("hosting.observability.metrics_max_mb", None)  # type: ignore[attr-defined]
    ok, detail = _writable(path.parent)
    if ok and path.exists() and not os.access(path, os.W_OK):
        ok, detail = False, "the file is read-only"
    state = f"{path.stat().st_size} bytes" if path.is_file() else "not made yet (the supervisor makes it)"
    # Metrics are best effort (T17 fix round 1, I2): a store that will not
    # open is moved aside and made again, and the supervisor starts without
    # metrics if even that fails -- so a problem here is a WARN, never a FAIL.
    broken = _metrics_broken(path) if path.exists() else ""
    if broken:
        report.add("Config", "metrics store", WARN,
                   f"{path}: {broken} - the supervisor moves it aside (.bad-<time>) and starts a new one")
    elif ok:
        report.add("Config", "metrics store", OK,
                   f"{path}: {state}, {detail}; rows kept {days} days, at most {cap} MB")
    else:
        report.add("Config", "metrics store", WARN,
                   f"{path}: {detail} - the supervisor will run without metrics")


def _metrics_broken(path: Path) -> str:
    """Why the metrics store at ``path`` will not open (read-only ``quick_check``), or ""."""
    import sqlite3

    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"it will not open ({type(exc).__name__})"
    from engine.hosting.supervisor.metrics import QUICK_CHECK_MAX_BYTES

    try:
        if path.stat().st_size > QUICK_CHECK_MAX_BYTES:
            # Too large to read whole (v0.20.0 T18): its header and schema only.
            db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            return ""
        found = db.execute("PRAGMA quick_check(1)").fetchone()
        if not found or str(found[0]).lower() != "ok":
            return "it fails its integrity check"
    except sqlite3.Error as exc:
        return f"it will not open ({type(exc).__name__})"
    finally:
        db.close()
    return ""


def _writable(directory: Path) -> tuple[bool, str]:
    """
    Whether this process can create a file in ``directory``, or in the nearest
    ancestor that exists (the engine creates the rest on first write).

    PROVED BY DOING IT: a temp file is created there and removed at once
    (``tempfile.TemporaryFile``, which deletes itself on close). ``os.access``
    was the first answer, and on Windows it reads only the read-only
    attribute and ignores ACLs, so it said "writable" of a directory the user
    could not write to (T3 fix round 1). The file lives for the length of the
    probe and nothing else is written.
    """
    import tempfile

    probe = directory
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    if not probe.is_dir():
        return False, f"{probe} is not a directory"
    try:
        with tempfile.TemporaryFile(dir=probe, prefix=".doctor-probe-"):
            pass
    except OSError as exc:
        return False, f"cannot write in {probe}: {exc.strerror or exc}"
    return True, "writable" if probe == directory else f"will be created (in {probe})"


#: The Docker image's user and group (the Dockerfile's ``USER``).
IMAGE_UID = 10001


def _storage_rows(report: Report) -> None:
    """
    Where the engine writes (spec §3.6, §4.1): the resolved storage root and
    whether it is writable, and the legacy ``paths.saves`` alias, named with
    its file so it is moved before v0.21.0 removes it.
    """
    from engine.persistence import storage

    root = storage.data_root()
    ok, detail = _writable(root)
    if not ok and os.environ.get("CLOCKWORK_ENV", "").strip() == "docker":
        # In the image (spec §7.4, §8.1, v0.20.0 T18): the likely cause and its fix.
        detail += (
            f" - the image runs as uid {IMAGE_UID}; a host directory bind-mounted on {root} is "
            f"owned by root until you run: sudo chown -R {IMAGE_UID}:{IMAGE_UID} <the host directory> "
            "(docs/HOSTING.md, /data ownership; a named volume needs nothing)"
        )
    report.add("Config", "storage", OK if ok else FAIL, f"{root}: {detail}")

    alias = storage.legacy_saves_alias()
    if alias is not None:
        source, value = alias
        report.add("Config", "legacy paths.saves", WARN,
                   f"{source}: paths.saves {value!r} is read as the save base - "
                   f"move it to storage.root; the alias is removed in "
                   f"{storage.LEGACY_REMOVED_IN}")


def check_config(report: Report) -> None:
    from engine.config import get_config

    from engine.config import external_config_layers, legacy_llm_layers
    from engine.llm.providers import get_provider
    from engine.stack import _service_name

    try:
        cfg = get_config()
    except ValueError as exc:
        # The admin layer (v0.20.0 T14) is checked as it is read: a key
        # outside the panel's allowlist, or a file that does not parse, stops
        # get_config, and the instance with it. Its message names the file
        # and the key, never a value.
        if "the admin layer" not in str(exc):
            raise
        report.add("Config", "admin layer", FAIL, str(exc))
        return

    # A stray test-suite marker (T5 re-review, N4): this process then runs as
    # a child of a test suite -- local.yaml ignored, no model server, nothing
    # saved -- so every other row below would describe the wrong machine.
    from engine.config import TEST_SANDBOX_ENV, stray_sandbox_message

    stray = stray_sandbox_message()
    if stray is not None:
        report.add("Config", TEST_SANDBOX_ENV, FAIL, stray)

    # A v0.18 `lmstudio:` block still in a layer (spec §2.2): read as `llm:`,
    # and named here so it is renamed before the alias goes in v0.21.0.
    for source, renamed in legacy_llm_layers():
        report.add("Config", "legacy lmstudio: block", WARN,
                   f"{source}: read as llm: ({'; '.join(renamed)}) - rename it "
                   "there; the alias is removed in v0.21.0")

    # The key's LENGTH only, never the key (rule 5). The row is named after
    # the model server's service: `lmstudio key` on LM Studio, as it always
    # was, `llm key` under any other provider.
    row = get_provider()
    label = f"{_service_name('llm')} key"
    key = str(cfg.get("llm.api_key", "") or "")
    if key:
        report.add("Config", label, OK, f"resolved ({len(key)} chars)")
    else:
        # The row's own words (identity data; LM Studio's are v0.18's).
        report.add("Config", label, WARN, row.key_missing)

    _hosting_row(report, cfg)
    _hosted_rows(report, cfg)
    _stories_rows(report, cfg)
    _threads_row(report, cfg)
    _admin_rows(report, cfg)
    _metrics_row(report, cfg)
    _storage_rows(report)

    # An operator's file outside the repo (spec §2.1): it outranks
    # config/local.yaml, so a Settings save of a key it sets changes nothing.
    # Named here with its keys -- never a value (rule 5).
    for source, keys in external_config_layers():
        report.add("Config", "CLOCKWORK_CONFIG", OK,
                   f"{source}: sets {', '.join(keys) or 'nothing'} - these outrank "
                   "config/local.yaml, so the Settings panel cannot change them")

    # No literal defaults here any more. They were the flagship's four content
    # paths, so a story that had lost one of these keys was reported against
    # Edgewood's file -- the doctor said "ok" about a file the running story
    # does not use. An undeclared key is now its own answer.
    for label, path_key in (
        ("economy", "paths.economy"),
        ("procgen", "paths.procgen_templates"),
        ("schedules", "paths.world_schedules"),
        ("art manifest", "paths.art_manifest"),
    ):
        path = cfg.resolve_path(path_key)
        if path is None:
            report.add("Config", label, WARN, f"{path_key} is not declared")
            continue
        exists = path.exists()
        report.add("Config", label, OK if exists else WARN,
                   str(path) if exists else f"missing: {path}")


def check_games(report: Report) -> None:
    """
    Report the active game and validate every manifest on disk.

    Deliberately validates ALL games, not just the active one: a manifest with
    a missing path is a launch that will fail, and the point of a doctor is to
    find that before somebody tries to play it.
    """
    from engine.games.caches import registered_caches
    from engine.games.registry import active_slug, catalog, discover

    current = active_slug()
    manifests = discover()
    if not manifests:
        report.add("Games", "discovery", FAIL,
                   "no games found - expected games/<slug>/game.yaml")
        return

    report.add("Games", "active", OK, f"{current} ({len(manifests)} installed)")
    if current not in manifests:
        report.add("Games", "active", FAIL,
                   f"{current} is selected but has no games/{current}/game.yaml")

    for row in catalog():
        slug = str(row["slug"])
        label = f"{slug}{' (active)' if row['active'] else ''}"
        if row["playable"]:
            report.add("Games", label, OK,
                       f"{row['title']} v{row['version']}, {len(row['paths'])} paths ok")
        else:
            # One line per problem: a manifest with four broken paths should
            # print four lines, not "invalid".
            for problem in row["problems"]:
                report.add("Games", label, FAIL, problem)

    # A retired `paths:` key still declared (v0.20.0: `saves`): an advisory,
    # never a FAIL -- the story plays, and the key moves nothing.
    for slug, manifest in sorted(manifests.items()):
        for _key, note in manifest.retired_paths():
            report.add("Games", slug, WARN, note)

    report.add("Games", "cache registry", OK,
               f"{len(registered_caches())} caches invalidated on activation")


def check_story_content(report: Report) -> None:
    """
    Run the shared referential-integrity pass over every story on disk.

    One summary line per game -- N errors / N advisories -- with the first few
    errors shown so the doctor points somewhere. The full listing is
    ``scripts/validate_content.py --game <slug> --warnings``; a doctor that
    printed four hundred findings would be a doctor nobody runs.
    """
    from engine.games.registry import active_slug, discover
    from engine.games.validation import errors_only, validate_story, warnings_only

    current = active_slug()
    shown_per_game = 3

    for slug, manifest in sorted(discover().items()):
        label = f"{slug}{' (active)' if slug == current else ''}"
        issues = validate_story(manifest)
        errors = errors_only(issues)
        warnings = warnings_only(issues)
        if not errors:
            report.add("Content integrity", label, OK if not warnings else WARN,
                       f"0 errors / {len(warnings)} advisories")
            continue
        report.add("Content integrity", label, FAIL,
                   f"{len(errors)} errors / {len(warnings)} advisories - "
                   f"run: python scripts/validate_content.py --game {slug}")
        for issue in errors[:shown_per_game]:
            report.add("Content integrity", label, FAIL, str(issue))
        if len(errors) > shown_per_game:
            report.add("Content integrity", label, FAIL,
                       f"... and {len(errors) - shown_per_game} more")


def check_inherited_content(report: Report) -> None:
    """
    Which stories are silently reading another story's content.

    THE DEFECT THIS SURFACES. A ``paths.*`` key a story omits does not fall back
    to nothing -- it falls back to ``config/default.yaml``, and twenty-three of
    those defaults point at The Clockwork Dark's own files. So a story that
    forgets ``quests`` does not get no quests; it gets Edgewood's, offered by
    name in a world that has never heard of Edgewood.

    Nothing announced this. It is invisible unless you happen to meet a rumour
    about grain tallies in a fae garden, and by then it looks like a content
    bug rather than a missing line in a manifest.

    THE CAUSE IS FIXED; THIS IS THE GUARD. Every content key in
    ``config/default.yaml`` is empty now, and each story declares what it reads.
    So this check should be quiet forever -- it exists to catch the regression,
    which is somebody adding a real path back to the engine default and
    reintroducing the leak for every story that omits it.

    WARN rather than FAIL because the failure mode is a trap rather than a
    break: the content is reachable but usually unreached, which is precisely
    why it survived undetected. A trap is what a doctor is for.
    """
    import yaml

    from engine.config import project_root
    from engine.games.registry import discover

    root = project_root()
    try:
        with (root / "config" / "default.yaml").open(encoding="utf-8") as handle:
            defaults = (yaml.safe_load(handle) or {}).get("paths") or {}
    except (OSError, yaml.YAMLError) as exc:
        report.add("Story paths", "defaults", WARN, f"could not read config/default.yaml: {exc}")
        return

    # Only keys whose default resolves to a file that EXISTS and is not itself
    # story-scoped or a runtime output directory. Those are the ones where an
    # omission means "read the flagship" rather than "read nothing".
    # The engine's run-time outputs: the storage root's saves and media
    # (v0.20.0, `engine/persistence/storage.py`), as the repo-relative
    # prefix a default would spell them with, and the two caches beside it.
    from engine.persistence import storage

    data = storage.data_root()
    try:
        data_rel = data.relative_to(root).as_posix()
    except ValueError:
        data_rel = "data"  # a root outside the repo: no default names it
    owned = {"games/", f"{data_rel}/saves", f"{data_rel}/media", "data/cache", "data/telemetry"}
    flagship = {
        key
        for key, value in defaults.items()
        if str(value)
        and not str(value).startswith(tuple(owned))
        and (root / str(value)).exists()
    }

    if not flagship:
        report.add(
            "Story paths", "engine defaults", OK, "name no story's content"
        )
    else:
        # A regression: somebody put a story's file back in the engine default.
        report.add(
            "Story paths",
            "engine defaults",
            WARN,
            f"{len(flagship)} default path(s) name content on disk, which every "
            f"story omitting them will read: {', '.join(sorted(flagship))}",
        )

    for slug, manifest in sorted(discover().items()):
        inherited = sorted(flagship - set(manifest.paths))
        if not inherited:
            report.add("Story paths", slug, OK, "declares every content path it reads")
            continue
        report.add(
            "Story paths",
            slug,
            WARN,
            f"reads {len(inherited)} path(s) it does not declare: {', '.join(inherited)}",
        )


def check_state_schemas(report: Report) -> None:
    """
    Validate every story's declared state, and report its shape.

    Reports counts by BACKING (field-backed values describe an attribute that
    already exists on GameState; bag-backed ones live in the generic containers)
    and by VISIBILITY, because those two numbers are how you tell at a glance
    whether a story has actually been described or is still running on the
    engine spine.

    A schema that will not parse is a FAIL, not a warning: the story asked for
    state it is not going to get.
    """
    from engine.games.registry import active_slug, discover
    from engine.state.schema import (
        BACKING_BAG,
        BACKING_FIELD,
        VISIBILITY_HIDDEN,
        VISIBILITY_PUBLIC,
        VISIBILITY_VEILED,
        SchemaError,
        load_schema,
    )

    current = active_slug()
    manifests = discover()
    if not manifests:
        return

    for slug, manifest in manifests.items():
        label = f"{slug}{' (active)' if slug == current else ''}"
        path = manifest.state_schema_path
        if path is None:
            # Absent is legal everywhere: a story with no state.yaml runs on the
            # engine spine, which is what both shipped games did before schemas.
            report.add("State", label, OK, "no state.yaml - runs on the engine spine")
            continue

        try:
            schema = load_schema(path, slug=slug)
        except SchemaError as exc:
            report.add("State", label, FAIL, f"{path.name}: {exc}")
            continue

        by_backing = {BACKING_FIELD: 0, BACKING_BAG: 0}
        by_visibility = {VISIBILITY_PUBLIC: 0, VISIBILITY_VEILED: 0, VISIBILITY_HIDDEN: 0}
        for spec in schema.values.values():
            by_backing[spec.backing] = by_backing.get(spec.backing, 0) + 1
            by_visibility[spec.visibility] = by_visibility.get(spec.visibility, 0) + 1

        report.add(
            "State",
            label,
            OK if schema.values else WARN,
            "{n} values ({f} field, {b} bag) - {p} public, {v} veiled, {h} hidden".format(
                n=len(schema.values),
                f=by_backing[BACKING_FIELD],
                b=by_backing[BACKING_BAG],
                p=by_visibility[VISIBILITY_PUBLIC],
                v=by_visibility[VISIBILITY_VEILED],
                h=by_visibility[VISIBILITY_HIDDEN],
            )
            if schema.values
            else f"{path.name} declares no values",
        )

        # The load-menu columns are resolved against this schema at save time,
        # where a bad name is a logged warning nobody reads. Here it is visible.
        for name in manifest.save_summary:
            spec = schema.get(name)
            if spec is None:
                report.add("State", label, FAIL,
                           f"save_summary names '{name}', which is not declared")
            elif spec.visibility == VISIBILITY_HIDDEN:
                report.add("State", label, FAIL,
                           f"save_summary names '{name}', which is hidden from the player")


def check_content(report: Report) -> None:
    """Load every content tree and count it, so an empty file is visible."""
    from engine.game.locations import LOCATIONS

    report.add("Content", "locations", OK if LOCATIONS else FAIL, f"{len(LOCATIONS)} places")

    probes = [
        ("skills", "engine.game.checks", "load_skill_rules", ("skills",)),
        ("archetypes", "engine.game.checks", "load_archetypes", ("archetypes",)),
        ("npc schedules", "engine.world.npc_sim", "load_npc_schedules", None),
        ("factions", "engine.game.reputation", "load_factions", ("factions",)),
    ]
    for label, module_path, func_name, sub in probes:
        try:
            module = __import__(module_path, fromlist=[func_name])
            data = getattr(module, func_name)()
            if sub:
                for key in sub:
                    data = (data or {}).get(key, data)
            count = len(data or {})
            report.add("Content", label, OK if count else WARN, f"{count} entries")
        except (ImportError, AttributeError) as exc:
            report.add("Content", label, WARN, f"not available: {exc}")

    art = Path("content/scenes/clockwork/static/art")
    files = list(art.rglob("*.jpg")) + list(art.rglob("*.png")) if art.exists() else []
    report.add("Content", "art pack", OK if files else WARN,
               f"{len(files)} images" if files else "no shipped art - falling back to procedural SVG")


def check_ui(report: Report) -> None:
    dist = Path("content/scenes/clockwork/static/dist")
    built = (dist / "app.js").exists() and (dist / "index.css").exists()
    report.add("UI", "build output", OK if built else FAIL,
               "dist present" if built else "missing - run: cd ui && npm run build")

    fonts = list((dist / "fonts").glob("*.woff2")) if dist.exists() else []
    report.add("UI", "fonts", OK if fonts else WARN,
               f"{len(fonts)} self-hosted" if fonts else "not self-hosted - will not render offline")


def check_saves(report: Report) -> None:
    try:
        from engine.persistence import get_save_store

        saves = get_save_store().list_saves()
        report.add("Saves", "store", OK, f"{len(saves)} run(s)")
        if saves:
            newest = saves[0]
            report.add("Saves", "newest", OK,
                       f"{newest.player_name}, day {newest.world_day}, turn {newest.turn_number}")
    except Exception as exc:  # noqa: BLE001 — diagnostics must not crash
        report.add("Saves", "store", WARN, str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Clockwork Dark — health check")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.verbose:
        import logging

        logging.disable(logging.WARNING)

    report = Report()
    for check in (
        check_python,
        check_config,
        check_games,
        check_state_schemas,
        check_story_content,
        check_inherited_content,
        check_services,
        check_llm,
        check_voice,
        check_content,
        check_ui,
        check_saves,
    ):
        try:
            check(report)
        except Exception as exc:  # noqa: BLE001 — one bad check must not hide the rest
            report.add("Errors", check.__name__, FAIL, repr(exc))

    print("The Clockwork Dark — doctor")
    print(report.render())

    if report.failed:
        print("\nSomething is broken. See [FAIL] above.")
        return 1
    print("\nAll good. Play with:  python launcher.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
