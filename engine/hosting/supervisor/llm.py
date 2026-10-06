"""
The Supervisor's Model Server: Health, Models, and the Apply
============================================================

v0.20.0 T16, spec §14.9. The supervisor holds the instance's config and
serves no turn, so it is the process that reads ``llm.*`` for the admin panel
(the front door never does) and the one that may re-read the config after an
edit: ``reset_config`` is safe in a process that holds no story and runs no
turn (spec §5.2). No serving process -- a worker or the front door -- resets
anything on the apply path; the workers are RESTARTED instead.

``llm.health`` (the fan-out pool, cached ``CACHE_SECONDS``): the provider,
its base URL as shown (``display_url``: no credentials, no query), the
provider's health probe (``Provider.health_probe``, as the doctor runs it)
with its detail and latency, the API key's presence and source kind
(``ConfigManager.secret_source``, the doctor's names) -- never the value --
every ``EDITABLE`` key's value, the keys a ``CLOCKWORK_CONFIG`` file sets
(``locked``: the page shows them locked, the apply refuses them), the admin
layer's file and keys, and ``llm.declared_models`` (ids and the facts
declared, no values).

``llm.models`` (the fan-out pool, cached ``CACHE_SECONDS``): the server's
models through ``engine.llm.discovery.list_models`` -- id, loaded, context,
capabilities -- at most ``MAX_MODELS``.

``llm.apply {changes, apply_anyway}`` is an OPERATION (spec §14.3): answered
``{op_id}`` at once (``submit``), run on the operations thread
(``perform``), in spec §14.9's order:

1. ``validating``: the changes checked (``admin.model.validate_changes``:
   the allowlist, each row's rule, not set by ``CLOCKWORK_CONFIG``) and held
   in memory; nothing is written yet;
2. when ``llm.provider`` or ``llm.base_url`` changes, the NEW server is
   probed, and the apply refused if it does not answer ("the new model server
   does not answer: nothing was changed"), unless ``apply_anyway``;
3. ``draining``: new narration admissions paused for every story, and a wait
   until no ticket is held in any lane, at most ``supervisor.drain_seconds``.
   Running out resumes everything and refuses ("turns are still running;
   nothing was changed"): nothing was written, so nothing is restored;
4. only then: ``admin.yaml`` copied to ``admin.yaml.prev`` (or, with no
   file yet, no ``.prev`` and none left over), the new layer written
   atomically, the config re-read (``reset_config``) and the lanes resized;
5. ``restarting``: the workers restarted ONE AT A TIME, in
   ``hosting.stories`` order -- each one's waiting turns answered busy (they
   never started), stopped, started under the new file, and its story's
   admissions resumed once it is ``ready`` (the pause is narrowed to each
   story first, ``LaneQueue.narrow_pause``). A worker not ``ready`` within
   ``supervisor.boot_seconds`` (or that exits) ROLLS BACK: ``.prev``
   restored (or the new layer removed), the config re-read, the lanes
   resized, and the workers already restarted restarted again with the
   failed one -- ``rolled_back``, audited ``llm.rollback``.

FIX ROUND 1. Step 1 also refuses a form built on another version of the
layer (``STALE``); step 4 also records where the API key may go
(``llm.api_key_origin``, ``_key_origin``: the new origin only on "send the API
key to this host"). After the write, ANY failure rolls back as a failed boot
does, and a shutdown ends the operation ``done`` with an ``error`` row (the
new file applies at the next start); the rollback restarts only the workers
this apply stopped. A supervisor that dies mid-apply rolls nothing back: the
new file is in force at its next start, the old one beside it as ``.prev``.

Until step 4 the committed file is the old one, so a worker that restarts for
any other reason during the drain boots under the config the instance is
running, never a split between the two. While the apply owns a worker's
restart (``Child.applying``) the main thread leaves it alone, and none of
these restarts counts toward ``max_restarts``. A stopped or held-down story
is not started: it reads the new file when an admin starts it.

THE ROLLBACK COVERS A CONFIG THAT FAILS TO BOOT; it does not cover a model
server that is down or a model it does not serve: workers do not call the
model server while they warm. Step 2's probe guards the server, only at the
moment of the apply; the Model server page's health row shows it after.

THE AUDIT (spec §14.11): the front door writes ``llm.apply``'s ``started``
row before it sends the op; this module writes its outcome under the same
``ref`` (``ok``, ``refused``, or ``error`` for a rollback), with each key's
old and new value (a URL as ``display_url`` shows it) and ``apply_anyway``
in its detail. A rollback writes its own ``llm.rollback`` rows (actor
``supervisor``), ``started`` before it acts. These are written on the
operations thread itself, which may wait on the audit lock.

THREADS AND LOCKS: ``health`` and ``models`` run on the fan-out pool;
``_cache_lock`` (a leaf) guards only the two cached answers, never held
across a probe, so two pages at once may each probe once. ``perform`` runs on
the operations thread and takes ``Supervisor._lock`` only as ``server.py``'s
own code does.

Version: v0.1.0 [2026-10-06]
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from engine.hosting.bus import WORKER, BusError, BusRefusal
from engine.hosting.supervisor.ops import (
    DONE,
    DRAINING,
    REFUSED,
    RESTARTING,
    ROLLED_BACK,
    VALIDATING,
    Operation,
    OperationRefused,
)
from engine.hosting.supervisor.process import (
    HELD_DOWN,
    READY,
    STOPPED,
    Child,
    operation_audit,
    stop_process,
)

if TYPE_CHECKING:  # pragma: no cover
    from engine.hosting.supervisor.server import Supervisor

logger = logging.getLogger(__name__)

#: How long ``llm.health`` and ``llm.models`` answers are reused (spec §14.9).
CACHE_SECONDS = 10.0

#: The health probe's timeout (the doctor's).
PROBE_SECONDS = 3.0

#: The model list's timeout.
LIST_SECONDS = 5.0

#: The most models ``llm.models`` lists (a page, inside one bus frame).
MAX_MODELS = 200

#: The most declared models ``llm.health`` lists.
MAX_DECLARED = 50

#: The longest detail line passed on.
MAX_DETAIL = 500

#: The bus health check's timeout while a restarted worker boots.
BOOT_CHECK_SECONDS = 5.0

#: How long a worker's own drain (its open requests) is given before its stop.
WORKER_DRAIN_SECONDS = 5.0

#: Extra time to wait for the reaper to let go of a crashed child.
CLAIM_MARGIN_SECONDS = 30.0

#: The refusals (spec §14.9), fixed text.
NOT_ANSWERING = "the new model server does not answer: nothing was changed"
DRAIN_REFUSED = "turns are still running; nothing was changed"
NOT_WRITTEN = "the admin layer could not be written: nothing was changed"
NOT_LOADED = "the new settings do not load: nothing was changed"
SHUTTING_DOWN = "the server is shutting down"
STALE = "these settings changed since the page was loaded: nothing was changed"
WRITTEN_AT_NEXT_START = (
    "the server is shutting down: the new settings are written, and apply at its next start"
)

#: The layer file's header (it is rewritten whole; hand edits are checked at load).
LAYER_HEADER = (
    "# The admin layer: the admin panel's model server settings (spec §14.9).\n"
    "# Written by the supervisor (engine/hosting/supervisor/llm.py); a hand edit is\n"
    "# checked at load, and a key outside the panel's allowlist refuses to start.\n"
)


def layer_version(path: Path) -> str:
    """
    The admin layer's version as a form carries it (fix round 1, I1): the
    first 16 hex digits of its bytes' SHA-256, or ``none`` when there is no
    file. A form built on another version is refused whole.
    """
    import hashlib

    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return "none"
    return hashlib.sha256(data).hexdigest()[:16]


def _value(key: str, value: Any) -> Any:
    """A config value as the panel and the audit show it: a URL without credentials, a scalar."""
    from engine.hosting.admin.model import display_url

    if key == "llm.base_url":
        return display_url(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


class ModelServer:
    """The supervisor's ``llm.*`` (see the module docstring); one per ``Supervisor``."""

    def __init__(self, supervisor: "Supervisor") -> None:
        self.sup = supervisor
        #: A leaf: guards the two cached answers only.
        self._cache_lock = threading.Lock()
        self._health: Optional[tuple[float, dict[str, Any]]] = None
        self._models: Optional[tuple[float, dict[str, Any]]] = None
        #: Bumped by ``forget`` (fix round 1, M4): an answer computed under an
        #: older generation -- begun before the config changed -- is answered
        #: but never cached.
        self._generation = 0
        #: Children the running apply has claimed (the operations thread only).
        self._claimed: set[int] = set()

    # -- health and models (the fan-out pool) --------------------------------------

    def _cached(self, which: str) -> Optional[dict[str, Any]]:
        with self._cache_lock:
            entry = self._health if which == "health" else self._models
        if entry is not None and time.monotonic() - entry[0] < CACHE_SECONDS:
            return entry[1]
        return None

    def _begin(self) -> int:
        """The generation an answer is computed under."""
        with self._cache_lock:
            return self._generation

    def _keep(self, which: str, answer: dict[str, Any], generation: int) -> dict[str, Any]:
        with self._cache_lock:
            if generation != self._generation:
                return answer  # the config changed while it was computed: not kept
            if which == "health":
                self._health = (time.monotonic(), answer)
            else:
                self._models = (time.monotonic(), answer)
        return answer

    def forget(self) -> None:
        """Drop both cached answers (the config changed), and any being computed."""
        with self._cache_lock:
            self._generation += 1
            self._health = None
            self._models = None

    @staticmethod
    def locked() -> dict[str, str]:
        """Each ``EDITABLE`` key a ``CLOCKWORK_CONFIG`` file sets, and the (last) file that sets it."""
        from engine.config import external_config_layers
        from engine.hosting.admin.model import EDITABLE

        found: dict[str, str] = {}
        for path, keys in external_config_layers():
            for key in keys:
                if key in EDITABLE:
                    found[key] = path
        return found

    def health(self, _args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """``llm.health``: see the module docstring."""
        cached = self._cached("health")
        if cached is not None:
            return cached
        generation = self._begin()
        from engine.config import admin_layer_keys, get_config
        from engine.hosting.admin.model import EDITABLE_ORDER, display_url, scrub
        from engine.llm.providers import get_provider
        from engine.persistence.storage import hosting_dir

        cfg = get_config()
        row = get_provider()
        began = time.monotonic()
        try:
            ok, detail = row.health_probe(timeout=PROBE_SECONDS)
        except Exception as exc:  # noqa: BLE001 -- a probe that raised is a failed probe
            ok, detail = False, f"the probe failed ({type(exc).__name__})"
        latency = int(round((time.monotonic() - began) * 1000))
        kind, source = cfg.secret_source("llm.api_key")
        withheld = getattr(cfg, "withheld_key", None)
        if not kind and withheld:
            # Fix round 1 (I2): set, but withheld from a base URL an admin
            # moved to another origin without sending the key there.
            kind, source = withheld
        declared_raw = cfg.get("llm.declared_models", {}) or {}
        declared = []
        if isinstance(declared_raw, dict):
            for model_id, entry in sorted(declared_raw.items())[:MAX_DECLARED]:
                fields = sorted(str(k) for k in entry) if isinstance(entry, dict) else []
                declared.append({"id": str(model_id)[:180], "fields": fields[:8]})
        answer = {
            "provider": row.name,
            "title": row.title,
            "base_url": display_url(cfg.get("llm.base_url", "")),
            "ok": bool(ok),
            "detail": scrub(detail)[:MAX_DETAIL],
            "latency_ms": latency,
            "checked_at": round(time.time(), 3),
            # Presence and source kind, NEVER the value (spec §14.9).
            "key": {"set": bool(kind), "kind": kind, "source": source[:120], "withheld": bool(withheld)},
            "values": {key: _value(key, cfg.get(key)) for key in EDITABLE_ORDER},
            "locked": self.locked(),
            "layer": {
                "path": str(hosting_dir() / "admin.yaml"),
                "keys": admin_layer_keys(),
                "version": layer_version(hosting_dir() / "admin.yaml"),
            },
            "declared": declared,
        }
        logger.info(
            "[supervisor] Model server probed (operation=llm.health, provider=%s, ok=%s, latency_ms=%d)",
            row.name,
            bool(ok),
            latency,
        )
        return self._keep("health", answer, generation)

    def models(self, _args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """``llm.models``: see the module docstring."""
        cached = self._cached("models")
        if cached is not None:
            return cached
        generation = self._begin()
        from engine.config import get_config
        from engine.llm.discovery import list_models
        from engine.llm.registry import ModelRegistry

        cfg = get_config()
        error = ""
        rows: list[dict[str, Any]] = []
        try:
            registry = ModelRegistry(timeout=LIST_SECONDS)
            declared = cfg.get("llm.declared_models", {}) or {}
            found = list_models(
                registry.provider,
                registry._fetch,
                declared=declared if isinstance(declared, dict) else {},
                context_tokens=int(cfg.get("llm.context_tokens", 8192) or 0),
            )
            for model in found[:MAX_MODELS]:
                rows.append(
                    {
                        "id": str(model.id)[:180],
                        "loaded": bool(model.is_loaded),
                        "context": int(model.loaded_context_length or model.max_context_length or 0),
                        "capabilities": [str(c)[:32] for c in tuple(model.capabilities)[:8]],
                    }
                )
        except Exception as exc:  # noqa: BLE001 -- the page says the list could not be read
            error = type(exc).__name__
        return self._keep("models", {"models": rows, "error": error, "checked_at": round(time.time(), 3)}, generation)

    # -- the apply: queued at once (the selector thread) ---------------------------

    def submit(self, args: dict[str, Any]) -> dict[str, Any]:
        """``llm.apply``: queued as an operation, its id at once (validated on the operations thread)."""
        from engine.hosting.supervisor.server import BUSY, SHUTTING_DOWN as SHUTTING_DOWN_CODE

        if self.sup.shutting_down.is_set():
            raise BusRefusal(SHUTTING_DOWN_CODE)
        audit = operation_audit(args)
        name = str(args.get("actor_name") or args.get("actor") or "")
        payload = {
            "changes": dict(args["changes"]),
            "apply_anyway": bool(args.get("apply_anyway", False)),
            "send_key": bool(args.get("send_key", False)),
            "version": args.get("version"),
        }
        try:
            return {"op_id": self.sup.ops.submit("llm.apply", "", name, audit=audit, payload=payload)}
        except OperationRefused:
            raise BusRefusal(BUSY) from None

    # -- the apply: performed (the operations thread) -------------------------------

    def perform(self, op: Operation, step: Any) -> None:
        """Spec §14.9's five steps (the module docstring); ends ``done``, ``refused`` or ``rolled_back``."""
        from engine.config import get_config
        from engine.hosting.admin.model import ChangeRefused, SERVER_KEYS, validate_changes

        payload = op.payload or {}
        anyway = bool(payload.get("apply_anyway"))
        send_key = bool(payload.get("send_key"))
        queue = self.sup.queue
        paused = False
        self._claimed = set()
        clean: dict[str, Any] = {}
        old: dict[str, Any] = {}
        try:
            step(VALIDATING)
            cfg = get_config()
            layer, prev = self._paths()
            version = payload.get("version")
            if version is not None and str(version) != layer_version(layer):
                # Fix round 1 (I1): the form was built on another admin layer.
                op.reason = STALE
                self._finish(op, step, REFUSED, {}, {}, anyway, send_key)
                return
            try:
                clean, _notes = validate_changes(payload.get("changes") or {}, self.locked())
            except ChangeRefused as refusal:
                op.reason = str(refusal)[:200]
                self._finish(op, step, REFUSED, {}, {}, anyway, send_key)
                return
            old = {key: cfg.get(key) for key in clean}
            extra = self._key_origin(cfg, clean, send_key, layer)
            if any(key in clean for key in SERVER_KEYS):
                if not self._new_server_answers(cfg, clean, send_key):
                    if not anyway:
                        op.reason = NOT_ANSWERING
                        self._finish(op, step, REFUSED, old, clean, anyway, send_key)
                        return
                    logger.warning(
                        "[supervisor] The new model server does not answer; applying anyway "
                        "(operation=llm.apply, op_id=%s)",
                        op.op_id,
                    )
            if self.sup.shutting_down.is_set():
                op.reason = SHUTTING_DOWN
                self._finish(op, step, REFUSED, old, clean, anyway, send_key)
                return

            # 3. Drain every story: no ticket held in any lane.
            step(DRAINING)
            queue.pause(None)
            paused = True
            if not queue.wait_until_idle(None, float(self.sup.settings.drain_seconds)):
                queue.resume(None)
                paused = False
                logger.warning(
                    "[supervisor] The model apply did not drain: a lane ticket is still held; resumed, "
                    "nothing written (operation=llm.apply, op_id=%s, held=%d)",
                    op.op_id,
                    queue.held(None),
                )
                op.reason = DRAIN_REFUSED
                self._finish(op, step, REFUSED, old, clean, anyway, send_key)
                return

            # 4. Only now: .prev, the new layer, the config re-read, the lanes.
            try:
                had_prev = self._write(layer, prev, {**clean, **extra})
            except OSError as exc:
                logger.error(
                    "[supervisor] The admin layer could not be written (operation=llm.apply, op_id=%s, error=%s)",
                    op.op_id,
                    type(exc).__name__,
                )
                op.reason = NOT_WRITTEN
                self._finish(op, step, REFUSED, old, clean, anyway, send_key)
                return
            restarted: list[Child] = []
            try:
                if not self._reload():
                    self._restore(layer, prev, had_prev)
                    self._reload()
                    op.reason = NOT_LOADED
                    self._finish(op, step, REFUSED, old, clean, anyway, send_key)
                    return
                self._resize()
                logger.info(
                    "[supervisor] Admin layer written (operation=llm.apply, op_id=%s, file=%s, keys=%s)",
                    op.op_id,
                    layer,
                    ",".join(sorted({**clean, **extra})),
                )

                # 5. The workers, one at a time; each story resumed once ready.
                step(RESTARTING)
                workers = [c for c in self.sup.children if c.role == WORKER]
                queue.narrow_pause([c.slug for c in workers])
                for child in workers:
                    outcome = self._restart(child, op)
                    if outcome == "skipped":
                        queue.resume(child.slug)
                        continue
                    if outcome == "ready":
                        restarted.append(child)
                        queue.resume(child.slug)
                        continue
                    if self.sup.shutting_down.is_set():
                        # Fix round 1 (M2): the new file IS written; it is in
                        # force from the next start, and the outcome says so.
                        op.reason = WRITTEN_AT_NEXT_START
                        self._finish(op, step, DONE, old, clean, anyway, send_key, result="error")
                        return
                    reason = f"{child.name} did not start under the new settings; the previous settings were restored"
                    self._rollback(op, step, layer, prev, had_prev, restarted, child, old, clean, anyway, send_key, reason)
                    return
            except Exception as exc:  # noqa: BLE001 -- after the write, a failure rolls back (M2)
                logger.exception(
                    "[supervisor] The model apply failed after the admin layer was written; rolling back "
                    "(operation=llm.apply, op_id=%s)",
                    op.op_id,
                )
                if self.sup.shutting_down.is_set():
                    op.reason = WRITTEN_AT_NEXT_START
                    self._finish(op, step, DONE, old, clean, anyway, send_key, result="error")
                    return
                reason = (
                    f"the apply failed after the new settings were written ({type(exc).__name__}); "
                    "the previous settings were restored"
                )
                self._rollback(op, step, layer, prev, had_prev, restarted, None, old, clean, anyway, send_key, reason)
                return
            queue.resume(None)
            paused = False
            self.forget()
            self._finish(op, step, DONE, old, clean, anyway, send_key)
        finally:
            if paused:
                queue.resume(None)
            self._release_all()

    def _key_origin(self, cfg: Any, clean: dict[str, Any], send_key: bool, layer: Path) -> dict[str, Any]:
        """
        The admin layer's ``llm.api_key_origin`` for this apply (fix round 1,
        I2): with "send the API key to this host", the new base URL's origin;
        otherwise the origin the layer already names, or -- when the base URL
        moves to another origin for the first time -- the origin in force
        now, so the key stays with the host it was given for. {} when the
        base URL does not change, or nothing needs recording.
        """
        import yaml

        from engine.config import url_origin

        if "llm.base_url" not in clean:
            return {}
        new = url_origin(clean["llm.base_url"])
        if send_key:
            return {"llm.api_key_origin": new}
        existing = ""
        try:
            loaded = yaml.safe_load(layer.read_text(encoding="utf-8")) or {}
            llm = loaded.get("llm") if isinstance(loaded, dict) else None
            existing = str(llm.get("api_key_origin") or "") if isinstance(llm, dict) else ""
        except (OSError, ValueError, yaml.YAMLError):
            existing = ""
        if existing:
            return {}
        current = url_origin(cfg.get("llm.base_url"))
        return {"llm.api_key_origin": current} if new != current else {}

    # -- the steps --------------------------------------------------------------------

    def _new_server_answers(self, cfg: Any, clean: dict[str, Any], send_key: bool = False) -> bool:
        """
        Step 2: the NEW provider's health probe at the NEW base URL. The API
        key goes with it only on "send the API key to this host" (fix round 1,
        I2); otherwise ``health_probe`` sends none to another origin.
        """
        from engine.llm.providers import DEFAULT_PROVIDER, get_provider

        provider = str(clean.get("llm.provider") or cfg.get("llm.provider") or DEFAULT_PROVIDER)
        base_url = str(clean.get("llm.base_url") or cfg.get("llm.base_url") or "")
        try:
            key = (str(cfg.get("llm.api_key", "") or "") or None) if send_key else None
            ok, _detail = get_provider(provider).health_probe(base_url or None, api_key=key, timeout=PROBE_SECONDS)
        except Exception as exc:  # noqa: BLE001 -- a probe that raised does not answer
            logger.warning("[supervisor] The new server's probe failed (operation=llm.apply, error=%s)", type(exc).__name__)
            return False
        logger.info("[supervisor] The new model server was probed (operation=llm.apply, provider=%s, ok=%s)", provider, ok)
        return bool(ok)

    @staticmethod
    def _paths() -> tuple[Path, Path]:
        from engine.hosting.admin.model import ADMIN_LAYER_FILE, ADMIN_LAYER_PREV
        from engine.persistence.storage import hosting_dir

        directory = hosting_dir()
        return directory / ADMIN_LAYER_FILE, directory / ADMIN_LAYER_PREV

    @staticmethod
    def _replace_with(target: Path, data: bytes) -> None:
        """
        Write ``data`` to ``target`` atomically (a sibling temp file, then a
        replace); 0600 on POSIX. Binary on Windows too (``O_BINARY``), so the
        bytes copied to ``.prev`` and back are the bytes written.
        """
        from engine.hosting.accounts import secure_dir

        secure_dir(target.parent)
        temp = target.with_name(target.name + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(str(temp), flags, 0o600)
            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temp, target)
        except OSError:
            # Fix round 1 (M3): no half-written temp file is left behind.
            try:
                temp.unlink()
            except OSError:
                pass
            raise

    def _write(self, layer: Path, prev: Path, clean: dict[str, Any]) -> bool:
        """
        Step 4's file work: the current layer copied to ``.prev`` (a stale
        ``.prev`` removed when there is none), the new layer -- the current
        one with ``clean`` merged in -- written atomically. Whether a previous
        file existed.
        """
        import yaml

        from engine.config import deep_merge
        from engine.hosting.admin.model import nested

        current: dict[str, Any] = {}
        had_prev = layer.is_file()
        if had_prev:
            raw = layer.read_bytes()
            self._replace_with(prev, raw)
            loaded = yaml.safe_load(raw.decode("utf-8")) or {}
            current = loaded if isinstance(loaded, dict) else {}
        elif prev.exists():
            prev.unlink()
        merged = deep_merge(current, nested(clean))
        text = LAYER_HEADER + yaml.safe_dump(merged, sort_keys=True, allow_unicode=False)
        self._replace_with(layer, text.encode("utf-8"))
        return had_prev

    def _restore(self, layer: Path, prev: Path, had_prev: bool) -> None:
        """The previous file back (``.prev`` copied over the layer), or the new layer removed."""
        if had_prev and prev.is_file():
            self._replace_with(layer, prev.read_bytes())
        else:
            try:
                layer.unlink()
            except FileNotFoundError:
                pass
        logger.warning("[supervisor] Admin layer restored to its previous version (operation=llm.rollback)")

    def _reload(self) -> bool:
        """Re-read this process's config (safe here: no story, no turn); whether it loads."""
        from engine.config import get_config, reset_config

        reset_config()
        self.forget()
        try:
            get_config()
        except ValueError as exc:
            logger.error("[supervisor] The config does not load after the apply (operation=llm.apply): %s", exc)
            return False
        return True

    def _resize(self) -> None:
        """Every ``llm.lanes`` lane to its configured size (the queue is paused for all, idle)."""
        from engine.config import get_config
        from engine.hosting.supervisor.__main__ import lane_limits
        from engine.hosting.supervisor.queue import QueueRefusal

        for lane, size in sorted(lane_limits(get_config()).items()):
            try:
                self.sup.queue.resize(lane, size)
            except QueueRefusal:
                logger.error(
                    "[supervisor] A lane was not resized: tickets are held (operation=llm.apply, lane=%s)", lane
                )

    # -- one worker ----------------------------------------------------------------------

    def _claim(self, child: Child) -> Optional[bool]:
        """
        Take ``child`` from the main thread: True once claimed; None when it is
        stopped or held down (not started: it reads the new file when an admin
        starts it); False when the reaper never let go of it.
        """
        deadline = time.monotonic() + float(self.sup.settings.stop_seconds) + CLAIM_MARGIN_SECONDS
        pause = threading.Event()
        while True:
            with self.sup._lock:
                if not child.stopping:
                    if child.state in (STOPPED, HELD_DOWN) and not child.alive():
                        return None
                    child.stopping = True
                    child.applying = True
                    self._claimed.add(id(child))
                    return True
            if time.monotonic() > deadline or self.sup.shutting_down.is_set():
                return False
            pause.wait(0.1)

    def _take_down(self, child: Child) -> None:
        """Its waiting turns answered busy, its open requests let finish, then stopped."""
        self.sup.queue.close_story(child.slug)
        conn = child.conn
        if conn is not None:
            try:
                self.sup.server.request(
                    conn, "drain", {"seconds": WORKER_DRAIN_SECONDS}, timeout=WORKER_DRAIN_SECONDS + 5.0
                )
            except BusError:
                pass  # it is stopped regardless
        self.sup._stop(child, float(self.sup.settings.stop_seconds))
        with self.sup._lock:
            child.state = STOPPED
            child.conn = None
            child.port = 0

    def _bring_up(self, child: Child) -> bool:
        """Start ``child`` (claimed, stopped) and wait for it to be ``ready``; on failure it is stopped again."""
        sup = self.sup
        try:
            with sup._lock:
                sup._spawn(child)  # clears ``stopping``; ``applying`` keeps the main thread away
                child.applying = True
        except Exception as exc:  # noqa: BLE001 -- a start that failed is a failed boot
            logger.error("[supervisor] %s could not be started (operation=llm.apply, error=%s)", child.name, type(exc).__name__)
            with sup._lock:
                child.state = STOPPED
                child.stopping = True
            sup._flush_said()
            return False
        sup._flush_said()
        if self._await_ready(child, float(sup.settings.boot_seconds)):
            return True
        stop_process(child.popen, ask=None, stop_seconds=0.0, name=child.name)
        sup._join_capture(child, 5.0)
        with sup._lock:
            child.record_exit()
            sup._retire(child)
            child.state = STOPPED
            child.conn = None
            child.port = 0
            child.stopping = True
        sup._flush_said()
        return False

    def _await_ready(self, child: Child, seconds: float) -> bool:
        """
        Until ``child`` is ``ready`` (its ``ready`` and a passing bus and HTTP
        check, as ``Supervisor._check`` decides it), at most ``seconds``.
        False when it exits first, or the time runs out.
        """
        sup = self.sup
        deadline = time.monotonic() + max(0.0, seconds)
        pause = threading.Event()
        while time.monotonic() < deadline and not sup.shutting_down.is_set():
            popen = child.popen
            if popen is None or popen.poll() is not None:
                logger.error(
                    "[supervisor] %s exited while starting under the new model settings (operation=llm.apply, code=%s)",
                    child.name,
                    None if popen is None else popen.poll(),
                )
                return False
            conn, port = child.conn, child.port
            if child.ready_sent and conn is not None:
                try:
                    sup.server.request(conn, "health", timeout=BOOT_CHECK_SECONDS)
                    bus_ok = True
                except BusError:
                    bus_ok = False
                http_ok = bool(port) and sup._http_ok(port)
                with sup._lock:
                    if child.conn is conn:
                        sup._apply_health(child, bus_ok, http_ok)
                    state = child.state
                sup._flush_said()
                if state == READY:
                    return True
            pause.wait(0.1)
        logger.error(
            "[supervisor] %s was not ready within boot_seconds (%ss) under the new model settings "
            "(operation=llm.apply)",
            child.name,
            seconds,
        )
        return False

    def _release(self, child: Child) -> None:
        """Give ``child`` back to the main thread."""
        with self.sup._lock:
            child.applying = False
            child.stopping = False
        self._claimed.discard(id(child))

    def _release_all(self) -> None:
        """
        Anything still claimed when the apply ends goes back to the main
        thread: one that is not running is put through the restart policy (a
        start that failed is a crash), so nothing is left stopped by accident.
        """
        for child in self.sup.children:
            if id(child) not in self._claimed:
                continue
            with self.sup._lock:
                child.applying = False
                if not child.alive() and child.state == STOPPED and not self.sup.shutting_down.is_set():
                    self.sup._apply_policy(child, "did not start after a model settings change")
                else:
                    child.stopping = False
            self.sup._flush_said()
        self._claimed = set()

    def _restart(self, child: Child, op: Operation) -> str:
        """One worker: ``ready``, ``skipped`` (stopped or held down) or ``failed``."""
        claimed = self._claim(child)
        if claimed is None:
            logger.info(
                "[supervisor] %s is not running; it reads the new model settings when started "
                "(operation=llm.apply, op_id=%s)",
                child.name,
                op.op_id,
            )
            return "skipped"
        if not claimed:
            return "failed"
        logger.info("[supervisor] Restarting %s for the model settings (operation=llm.apply, op_id=%s)", child.name, op.op_id)
        self._take_down(child)
        if not self._bring_up(child):
            return "failed"
        logger.info(
            "[supervisor] %s is serving under the new model settings (operation=llm.apply, op_id=%s)",
            child.name,
            op.op_id,
        )
        self._release(child)
        return "ready"

    def _rollback(
        self,
        op: Operation,
        step: Any,
        layer: Path,
        prev: Path,
        had_prev: bool,
        restarted: list[Child],
        failed: Optional[Child],
        old: dict[str, Any],
        clean: dict[str, Any],
        anyway: bool,
        send_key: bool,
        reason: str,
    ) -> None:
        """
        A worker would not boot under the new file (``failed``), or the apply
        failed after the write (``failed`` None, fix round 1 M2): ``.prev``
        restored, the config re-read, the lanes resized, and ONLY the workers
        this apply stopped -- those it restarted, and the failed one, still
        claimed -- started again (fix round 1, M1). A stopped or held-down
        story, or a child the reaper never let go of, is never started here.
        """
        from engine.hosting import audit

        queue = self.sup.queue
        info = op.audit or {}
        directory = info.get("directory")
        target = self._target(clean)
        ref = audit.new_ref()
        if info:
            try:
                audit.append(
                    "llm.rollback",
                    actor=audit.SUPERVISOR_ACTOR,
                    result=audit.STARTED,
                    target=target,
                    detail={"op_id": op.op_id, "story": failed.slug if failed is not None else ""},
                    ref=ref,
                    directory=directory,
                )
            except audit.AuditUnavailable:
                pass  # a rollback is never refused for want of its row; append logged it
        logger.error("[supervisor] Rolling back the model settings (operation=llm.rollback, op_id=%s): %s", op.op_id, reason)
        queue.pause(None)
        queue.wait_until_idle(None, float(self.sup.settings.drain_seconds))
        ours: list[Child] = []
        for child in restarted:
            if self._claim(child):
                self._take_down(child)
                ours.append(child)
            else:
                logger.warning(
                    "[supervisor] %s was not taken back for the rollback (stopped, held down, or still the "
                    "reaper's); it is left as it is (operation=llm.rollback)",
                    child.name,
                )
        for child in self.sup.children:
            # Anything else this apply still holds (the failed one, or one
            # stopped when an exception cut a restart short).
            if id(child) in self._claimed and child not in ours and not child.alive():
                ours.append(child)
        self._restore(layer, prev, had_prev)
        self._reload()
        self._resize()
        workers = [c for c in self.sup.children if c.role == WORKER]
        queue.narrow_pause([c.slug for c in workers])
        again = [c for c in workers if c in ours]
        clean_start = True
        for child in again:
            logger.info("[supervisor] Restarting %s under the previous model settings (operation=llm.rollback)", child.name)
            if self._bring_up(child):
                self._release(child)
            else:
                clean_start = False
            queue.resume(child.slug)
        queue.resume(None)
        self.forget()
        op.reason = reason[:200]
        if info:
            try:
                audit.append(
                    "llm.rollback",
                    actor=audit.SUPERVISOR_ACTOR,
                    result=audit.OK if clean_start else audit.ERROR,
                    target=target,
                    detail={
                        "op_id": op.op_id,
                        "story": failed.slug if failed is not None else "",
                        "restarted": len(again),
                    },
                    ref=ref,
                    directory=directory,
                )
            except audit.AuditUnavailable:
                pass
        self._finish(op, step, ROLLED_BACK, old, clean, anyway, send_key)

    # -- the outcome ---------------------------------------------------------------------

    @staticmethod
    def _target(clean: dict[str, Any]) -> str:
        from engine.hosting import audit

        keys = sorted(clean)
        target = ",".join(keys)
        return target if len(target) <= audit.MAX_TEXT else f"{len(keys)} llm keys"

    def _finish(
        self,
        op: Operation,
        step: Any,
        status: str,
        old: dict[str, Any],
        clean: dict[str, Any],
        anyway: bool,
        send_key: bool = False,
        *,
        result: Optional[str] = None,
    ) -> None:
        """
        The final step, and the ``llm.apply`` outcome row under the front
        door's ``ref``. ``result`` overrides the row's result (a shutdown after
        the write: ``done`` -- the new file is in force -- recorded ``error``).
        """
        from engine.hosting import audit

        step(status)
        info = op.audit
        if not info:
            return
        if result is None:
            result = {DONE: audit.OK, REFUSED: audit.REFUSED}.get(status, audit.ERROR)
        detail: dict[str, Any] = {"op_id": op.op_id, "apply_anyway": anyway}
        if "llm.base_url" in clean:
            detail["send_key"] = send_key
        for key in sorted(clean):
            detail[key] = {"old": _value(key, old.get(key)), "new": _value(key, clean[key])}
        if op.reason and result != audit.OK:
            detail["reason"] = op.reason[: audit.MAX_TEXT]
        actor = audit.Actor(info["actor"], info["actor_name"], info["address"])
        rows = (detail, {k: v for k, v in detail.items() if not isinstance(v, dict)})
        for row_detail in rows:
            try:
                audit.append(
                    "llm.apply",
                    actor=actor,
                    result=result,
                    target=self._target(clean) if clean else "",
                    detail=row_detail,
                    ref=info["ref"],
                    directory=info["directory"],
                )
                return
            except audit.AuditRowError:
                continue  # a value too long for a row: written without the values
            except audit.AuditUnavailable:
                return  # logged by append; the started row stands


__all__ = [
    "CACHE_SECONDS",
    "DRAIN_REFUSED",
    "ModelServer",
    "NOT_ANSWERING",
    "STALE",
    "WRITTEN_AT_NEXT_START",
    "layer_version",
]
