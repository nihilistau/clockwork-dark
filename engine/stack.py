"""
Local Service Stack
===================

Starts and health-checks the local services the game depends on.

Everything is declared in ``config.stack.services`` so machine-specific paths
live in ``config/local.yaml`` rather than in code. Two kinds of service:

    manage: true    we spawn the process and wait for its health endpoint
    manage: false   someone else owns it (LM Studio's desktop toggle, or a CLI
                    that is invoked per request); we only report on it

A service that is already listening is never started twice -- the health check
runs first, so re-running the launcher against a warm stack is a no-op rather
than a port conflict.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from engine.config import get_config, project_root
from engine.llm.routes import MODELS_PATH, same_origin

logger = logging.getLogger(__name__)

STATUS_UP = "up"
STATUS_STARTED = "started"
STATUS_DOWN = "down"
STATUS_DISABLED = "disabled"
STATUS_UNMANAGED = "unmanaged"
STATUS_FAILED = "failed"


@dataclass
class ServiceSpec:
    """One declared service."""

    name: str
    enabled: bool = True
    manage: bool = False
    root: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    health_url: str = ""
    startup_timeout_seconds: int = 300
    model: str = ""
    #: The model server (``stack.services.llm``), set by ``load_specs`` and
    #: never read from config. With no ``health_url`` it is checked by the
    #: configured provider's own health probe (``probe_service``, spec §8).
    model_server: bool = False

    @classmethod
    def from_config(cls, name: str, raw: dict[str, Any]) -> "ServiceSpec":
        known = {f.name for f in cls.__dataclass_fields__.values()} - {"name", "model_server"}
        return cls(name=name, **{k: v for k, v in raw.items() if k in known})

    @property
    def checked(self) -> bool:
        """Whether this service has a health check at all."""
        return bool(self.health_url) or self.model_server

    def resolved_root(self) -> Optional[Path]:
        if not self.root:
            return None
        path = Path(self.root)
        return path if path.is_absolute() else project_root() / path

    def resolved_command(self) -> Optional[Path]:
        """
        Absolute path to the executable, or None if it cannot be found.

        The shipped commands carry no ``.exe`` (``target/release/tts-server``),
        so one config serves Windows and Linux. A path the config names (an
        absolute one, or one under ``root``) is resolved the way
        ``shutil.which`` already resolves a PATH name: on Windows, the name as
        written and then the name plus each ``PATHEXT`` suffix, so the Windows
        build's ``tts-server.exe`` is found as before, and an owner's command
        that still says ``.exe`` is found unchanged.

        Only a regular file counts, and off Windows only one with its exec
        bit set, so a directory or an unbuilt source file reads as "not
        found" rather than failing later at ``Popen``.

        The order is: an absolute ``command``; then ``command`` under
        ``root``; then ``shutil.which(command)``. That last step is the
        pre-v0.20.0 fallback and keeps its behaviour: a bare name
        (``python``) is looked up on PATH, but a command that holds a
        separator (``target/release/tts-server``, the shipped value while
        ``root`` is ``""``) is taken RELATIVE TO THE PROCESS'S WORKING
        DIRECTORY, not the repository or ``root``, because that is how
        ``shutil.which`` treats a path with a directory part. So with no
        ``root`` set, a shipped voxtral command is found only if the launcher
        was started from the directory that holds ``target/``.
        """
        if not self.command:
            return None
        candidate = Path(self.command)
        if candidate.is_absolute():
            return _existing_executable(candidate)

        root = self.resolved_root()
        if root is not None:
            local = _existing_executable(root / candidate)
            if local is not None:
                return local

        found = shutil.which(self.command)
        return Path(found) if found else None


def _runnable(path: Path) -> bool:
    """A regular file, and off Windows one the process may execute. Windows
    has no exec bit: there the suffix decides, as it does for the OS."""
    if not path.is_file():
        return False
    return os.name == "nt" or os.access(path, os.X_OK)


def _existing_executable(path: Path) -> Optional[Path]:
    """
    ``path`` if it is a runnable file, else (on Windows only) ``path`` plus
    the first ``PATHEXT`` suffix that is, else None. Elsewhere a name is taken
    exactly as written: Linux has no implied extension.

    The suffixes are tried in ``PATHEXT``'s own order (by default ``.COM``,
    ``.EXE``, ``.BAT``, ``.CMD``, ...), the order Windows itself and
    ``shutil.which`` use, so the stack finds what typing the name at a prompt
    in that directory would run. That means a ``tts-server.com`` or
    ``tts-server.bat`` beside ``tts-server.exe`` in ``root`` wins over the
    ``.exe``: ``root`` is the owner's own build directory, and whatever they
    put there is what they would run by hand. Naming the ``.exe`` in
    ``command`` pins it.
    """
    if _runnable(path):
        return path
    if os.name != "nt":
        return None
    for suffix in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep):
        if not suffix:
            continue
        with_suffix = path.with_name(path.name + suffix.lower())
        if _runnable(with_suffix):
            return with_suffix
    return None


@dataclass
class ServiceStatus:
    """What happened to one service."""

    name: str
    status: str
    detail: str = ""
    pid: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_UP, STATUS_STARTED, STATUS_UNMANAGED, STATUS_DISABLED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "pid": self.pid,
            "ok": self.ok,
        }


def _service_name(key: str) -> str:
    """
    The name a service is shown and reported under.

    The model server is declared as ``stack.services.llm`` since v0.19.0 (it
    was ``lmstudio``). While ``llm.provider`` is LM Studio it keeps the name
    ``lmstudio``, so the doctor's and the launcher's rows about it -- and the
    FAIL level both give that name -- are what an LM Studio user always saw.
    """
    if key == "llm" and str(get_config().get("llm.provider") or "lmstudio") == "lmstudio":
        return "lmstudio"
    return key


#: The names the model server's service is reported under: ``llm``, and
#: ``lmstudio`` while the provider is LM Studio (``_service_name``). The one
#: FAIL-level service in ``scripts/doctor.py`` and ``launcher.py --check``,
#: whatever the provider: without it there is no narration.
MODEL_SERVER_NAMES: frozenset[str] = frozenset({"llm", "lmstudio"})


def load_specs() -> list[ServiceSpec]:
    """Read declared services from config."""
    services = get_config().section("stack.services")
    specs = []
    for name, raw in services.items():
        if not isinstance(raw, dict):
            continue
        spec = ServiceSpec.from_config(_service_name(name), raw)
        spec.model_server = name == "llm"
        specs.append(spec)
    return specs


def probe_service(spec: ServiceSpec, *, timeout: float = 3.0) -> tuple[bool, str]:
    """
    Health-check one declared service.

    Its ``health_url`` when it names one (``probe``). The model server with
    an empty ``health_url`` -- the shipped default since v0.19.0 -- asks the
    configured provider's own health probe against ``llm.base_url``
    (``Provider.health_probe``, spec §8): LM Studio's ``/api/v1/models`` by
    its shape (v0.18's request, for the shipped config), vLLM's ``/health``
    and model list, llama-server's ``/health``, Ollama's ``/api/version`` and
    ``/api/tags``, a generic server's list. It used to be a fixed
    ``http://localhost:1234/api/v1/models``, so an LM Studio moved to another
    port was health-checked on the wrong one.
    """
    if spec.health_url:
        return probe(spec.health_url, timeout=timeout)
    if spec.model_server:
        from engine.llm.providers import get_provider

        return get_provider().health_probe(timeout=timeout)
    return False, "no health url"


def probe(url: str, *, timeout: float = 3.0) -> tuple[bool, str]:
    """
    Health-check a URL.

    Sends the configured model server's key when -- and only when -- the URL
    is served by the configured model server: the same scheme, host and port
    as ``llm.base_url`` (v0.19.0, finding 3). Without the key a working setup
    reported "requires an API key" even once the key was correctly
    configured, which is exactly the kind of misleading status that sends you
    debugging a service that is fine. Until v0.19.0 the key went to any URL
    containing ``1234`` or ``lmstudio``: never to a vLLM on 8000 that needed
    one, and to anything else on a port that happened to be 1234.

    A bare 401 is NOT healthy. It used to be: "the process is up, it just wants
    credentials" is true and useless, because a server that refuses every
    request cannot narrate a turn, and reporting it green is how the health
    check came to pass while the game fell back to canned lines. Reachable and
    usable are different questions and this function answers the second one.

    NEITHER IS A BARE 200. LM Studio answers routes it does not serve with 200
    and an error body -- ``GET /v1/nonsense`` and ``GET /api/v9/models`` both
    do, measured live -- so status alone would pass against a server
    implementing none of our API. Two rules follow: LM Studio's model list is
    checked by its SHAPE through ``registry.probe_models``, and for every other
    service a 200 whose body is an ``{"error": ...}`` object is a failure, not
    a pass.
    """
    if not url:
        return False, "no health url"

    ours = same_origin(url)
    if url.endswith(MODELS_PATH):
        # The one question worth asking of LM Studio: does it list models, in
        # the shape the v1 REST API returns them. The route is LM Studio's, so
        # its answer is read as LM Studio's list whatever the provider.
        from engine.llm.registry import probe_models

        return probe_models(
            url, timeout=timeout, provider="lmstudio", api_key=None if ours else ""
        )

    headers: dict[str, str] = {}
    if ours:
        key = str(get_config().get("llm.api_key", "") or "")
        if key:
            headers["Authorization"] = f"Bearer {key}"

    try:
        response = httpx.get(url, timeout=timeout, headers=headers)
    except httpx.HTTPError as exc:
        return False, type(exc).__name__

    if response.status_code == 401:
        if ours:
            from engine.llm.providers import get_provider
            from engine.llm.registry import _refused_key_detail

            return False, _refused_key_detail(get_provider())
        return False, (
            "listening, but it refuses every request: it wants a key this "
            "health check does not send"
        )
    if response.status_code < 400:
        if _is_error_body(response):
            return False, "answered 200 with an error body -- it does not serve this route"
        return True, "ready"
    return response.status_code < 500, f"HTTP {response.status_code}"


def _is_error_body(response: httpx.Response) -> bool:
    """A success status carrying ``{"error": ...}`` is a failure wearing a 200."""
    if "json" not in response.headers.get("content-type", "").lower():
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and bool(payload.get("error"))


class StackManager:
    """Starts, checks and stops the local service stack."""

    def __init__(self, specs: Optional[list[ServiceSpec]] = None) -> None:
        self.specs = specs if specs is not None else load_specs()
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def status(self) -> list[ServiceStatus]:
        """Check every service without starting anything."""
        results = []
        for spec in self.specs:
            if not spec.enabled:
                results.append(ServiceStatus(spec.name, STATUS_DISABLED))
                continue
            if not spec.checked:
                command = spec.resolved_command()
                results.append(
                    ServiceStatus(
                        spec.name,
                        STATUS_UNMANAGED if command else STATUS_FAILED,
                        str(command) if command else f"command not found: {spec.command}",
                    )
                )
                continue
            alive, detail = probe_service(spec)
            results.append(
                ServiceStatus(spec.name, STATUS_UP if alive else STATUS_DOWN, detail)
            )
        return results

    def start(self, spec: ServiceSpec) -> ServiceStatus:
        """Start one service, or report it already running."""
        if not spec.enabled:
            return ServiceStatus(spec.name, STATUS_DISABLED)

        # Never double-start. A warm service answering its health check is the
        # success case, not a port conflict waiting to happen.
        if spec.checked:
            alive, detail = probe_service(spec)
            if alive:
                return ServiceStatus(spec.name, STATUS_UP, f"already running ({detail})")

        if not spec.manage:
            command = spec.resolved_command()
            if command is None and spec.command:
                return ServiceStatus(
                    spec.name, STATUS_FAILED, f"command not found: {spec.command}"
                )
            return ServiceStatus(
                spec.name,
                STATUS_DOWN if spec.checked else STATUS_UNMANAGED,
                "not managed by the stack — start it yourself"
                if spec.checked
                else str(command or ""),
            )

        command = spec.resolved_command()
        if command is None:
            return ServiceStatus(
                spec.name,
                STATUS_FAILED,
                f"command not found: {spec.command}"
                + (f" under {spec.resolved_root()}" if spec.root else ""),
            )

        cwd = spec.resolved_root() or project_root()
        argv = [str(command), *[str(a) for a in spec.args]]
        logger.info(
            "[stack] Starting (operation=start, service=%s, cwd=%s)", spec.name, cwd
        )
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return ServiceStatus(spec.name, STATUS_FAILED, str(exc))

        self._processes[spec.name] = process
        ok, detail = self._wait_healthy(spec, process)
        return ServiceStatus(
            spec.name,
            STATUS_STARTED if ok else STATUS_FAILED,
            detail,
            pid=process.pid,
        )

    def _wait_healthy(
        self,
        spec: ServiceSpec,
        process: subprocess.Popen[bytes],
    ) -> tuple[bool, str]:
        """Poll until the service answers, it dies, or we run out of patience."""
        if not spec.checked:
            return True, "no health check"

        deadline = time.monotonic() + spec.startup_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False, f"process exited with code {process.returncode}"
            alive, detail = probe_service(spec, timeout=2.0)
            if alive:
                return True, detail
            time.sleep(1.0)
        return False, f"did not become healthy within {spec.startup_timeout_seconds}s"

    def start_all(self) -> list[ServiceStatus]:
        return [self.start(spec) for spec in self.specs]

    def stop_all(self) -> None:
        """Terminate only the processes this manager spawned."""
        for name, process in self._processes.items():
            if process.poll() is None:
                logger.info("[stack] Stopping (operation=stop_all, service=%s)", name)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        self._processes.clear()


def render_table(statuses: list[ServiceStatus]) -> str:
    """Human-readable status block for the console."""
    glyphs = {
        STATUS_UP: "[ ok ]",
        STATUS_STARTED: "[ ok ]",
        STATUS_UNMANAGED: "[ ok ]",
        STATUS_DISABLED: "[ -- ]",
        STATUS_DOWN: "[down]",
        STATUS_FAILED: "[FAIL]",
    }
    width = max((len(s.name) for s in statuses), default=10)
    lines = []
    for status in statuses:
        glyph = glyphs.get(status.status, "[ ?? ]")
        lines.append(f"  {glyph}  {status.name:<{width}}  {status.detail}")
    return "\n".join(lines)
