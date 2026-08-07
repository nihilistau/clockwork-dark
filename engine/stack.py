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
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from engine.config import get_config, project_root

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

    @classmethod
    def from_config(cls, name: str, raw: dict[str, Any]) -> "ServiceSpec":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(name=name, **{k: v for k, v in raw.items() if k in known and k != "name"})

    def resolved_root(self) -> Optional[Path]:
        if not self.root:
            return None
        path = Path(self.root)
        return path if path.is_absolute() else project_root() / path

    def resolved_command(self) -> Optional[Path]:
        """Absolute path to the executable, or None if it cannot be found."""
        if not self.command:
            return None
        candidate = Path(self.command)
        if candidate.is_absolute():
            return candidate if candidate.exists() else None

        root = self.resolved_root()
        if root is not None:
            local = root / candidate
            if local.exists():
                return local

        found = shutil.which(self.command)
        return Path(found) if found else None


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


def load_specs() -> list[ServiceSpec]:
    """Read declared services from config."""
    services = get_config().section("stack.services")
    return [
        ServiceSpec.from_config(name, raw)
        for name, raw in services.items()
        if isinstance(raw, dict)
    ]


def probe(url: str, *, timeout: float = 3.0) -> tuple[bool, str]:
    """
    Health-check a URL.

    Sends the configured LM Studio key when probing LM Studio, so a working
    setup reports as working. Without it the check said "requires an API key"
    even once the key was correctly configured, which is exactly the kind of
    misleading status that sends you debugging a service that is fine.

    A bare 401 still counts as reachable -- the process is up, it just wants
    credentials -- but it is reported as such.
    """
    if not url:
        return False, "no health url"

    headers: dict[str, str] = {}
    if "1234" in url or "lmstudio" in url.lower():
        key = str(get_config().get("lmstudio.api_key", "") or "")
        if key:
            headers["Authorization"] = f"Bearer {key}"

    try:
        response = httpx.get(url, timeout=timeout, headers=headers)
    except httpx.HTTPError as exc:
        return False, type(exc).__name__

    if response.status_code == 401:
        return True, "listening, but the API key is missing or wrong"
    if response.status_code < 400:
        return True, "ready"
    return response.status_code < 500, f"HTTP {response.status_code}"


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
            if not spec.health_url:
                command = spec.resolved_command()
                results.append(
                    ServiceStatus(
                        spec.name,
                        STATUS_UNMANAGED if command else STATUS_FAILED,
                        str(command) if command else f"command not found: {spec.command}",
                    )
                )
                continue
            alive, detail = probe(spec.health_url)
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
        if spec.health_url:
            alive, detail = probe(spec.health_url)
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
                STATUS_DOWN if spec.health_url else STATUS_UNMANAGED,
                "not managed by the stack — start it yourself"
                if spec.health_url
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
        if not spec.health_url:
            return True, "no health check"

        deadline = time.monotonic() + spec.startup_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False, f"process exited with code {process.returncode}"
            alive, detail = probe(spec.health_url, timeout=2.0)
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
