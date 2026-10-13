"""
The Phone's Media Job Worker
============================

One background thread per process that turns a queued generation job into a
stored file (v0.22.0 spec §13.2, §13.4 "The protocol" and "Scheduling"):

1. **build** the workflow (``workflows.load_workflow`` + ``bind``);
2. **upload** a reference image, only when the workflow binds
   ``reference_image``;
3. **submit** (``POST /prompt``, ``client_id`` = the job's ``mid``, so a
   resubmission after a restart is the same request);
4. **poll** ``/history`` every ``comfyui.poll_seconds`` -- an execution error
   is resubmitted up to ``comfyui.retries`` times; past
   ``comfyui.job_timeout_seconds`` the client interrupts and the job FAILS;
5. **collect** the declared output node's files;
6. **fetch** the main file (capped at ``comfyui.max_bytes``) and type it by
   its magic bytes (``storage.sniff``); a video's poster is the first
   image file under ``images`` of the workflow's ``poster_node``, else of
   the output node, the clip itself never fetched twice
   (:meth:`MediaJobWorker._store_poster`);
7. **store** it through ``write_bytes_atomic`` at the owner-scoped path;
8. **hand off** the :class:`JobResult` to ``on_done`` (T19 wires it to the
   session: liveness, the turn lock, ``social_media``, the ``media_ready``
   push);
9. **failure** is a ``failed`` result, never a raise into anything.

ORDER (I8): priority (0 thread media, 1 the player's own photos, 2
portraits), then round-robin by account, then age; one job at a time.
``phone_media.daily_job_cap`` jobs per account per real day: past it
``submit`` returns False and the caller uses the procedural tile.

STOPPING. ``stop()`` sets an event that the poll sleep waits on, so a job
waiting between polls is ABANDONED at once (``ComfyError("cancelled")``):
logged, never handed to ``on_done``. The next process's resubmission (same
``mid``, same ``client_id``) finishes it (§13.2).

LOCKS. ``_lock`` (a leaf, ``engine/locks.py``) guards only the queue, the
day's counts and the running job's key; no HTTP call, no config read, no log
and no ``on_done`` runs under it. ``_worker_lock`` guards only building the
process's one worker.

Nothing here reads, filters or rewrites a prompt or a result (AGENTS.md rule
12): the request reaches ComfyUI as the caller bound it.

Version: v0.1.0 [2026-10-12]
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import itertools
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from engine.config import get_config
from engine.locks import renew_after_fork
from engine.media.comfy import storage
from engine.media.comfy.client import ComfyClient, ComfyError
from engine.media.comfy.workflows import BindingError, bind, load_workflow
from engine.persistence.atomic import write_bytes_atomic
from engine.persistence.saves import check_save_id

logger = logging.getLogger(__name__)

#: The idle worker's longest sleep: a backstop, since submit() and stop()
#: both wake it at once.
_IDLE_WAIT_SECONDS = 30.0

#: Which output keys hold the MAIN file for each workflow kind; anything else
#: under the node (a video's first-frame ``images``) is secondary.
_MAIN_KEYS = {"image": ("images",), "video": ("videos", "gifs"), "audio": ("audio",)}


@dataclass
class JobSpec:
    """One generation job (a ``state.social.media`` row's request)."""

    mid: str
    kind: str
    owner: str
    save_id: str
    session_id: str
    epoch: int
    workflow: str
    values: dict
    priority: int
    account: str
    reference: Optional[bytes] = None
    created: float = 0.0
    #: The story whose save this is; "" is the active story (one per worker process).
    slug: str = ""

    def digest(self) -> str:
        """
        The REQUEST's fingerprint: its workflow and bound values (8 hex). A
        resubmission of the same request (a resume's: the stored values) has
        the same digest; a different request under a reused ``mid`` does not
        (v0.22.0 T19 review I1).
        """
        payload = json.dumps([self.workflow, self.values], sort_keys=True, default=str).encode("utf-8")
        return hashlib.blake2b(payload, digest_size=4).hexdigest()

    def stem(self) -> str:
        """The stored files' name: ``<mid>-<digest>`` (its poster ``<stem>_poster``)."""
        return f"{self.mid}-{self.digest()}"


@dataclass
class JobResult:
    """What became of one job: ``ready``, ``failed`` or ``abandoned``."""

    mid: str
    status: str
    url: str = ""
    poster_url: str = ""
    path: str = ""
    error: str = ""
    kind: str = ""
    attempts: int = 0
    #: A voice note's measured length (T21); 0 for anything else.
    seconds: float = 0.0


def _local_today() -> str:
    return _dt.date.today().isoformat()


def _key(spec: JobSpec) -> tuple[str, str, str, str]:
    """A job's identity: its owner, save, media id AND request digest, so two
    different requests under one reused ``mid`` are two jobs (review I1)."""
    return (spec.owner, spec.save_id, spec.mid, spec.digest())


def _account(spec: JobSpec) -> str:
    """The one account key the daily cap and the round-robin both use."""
    return spec.account or spec.owner or storage.LOCAL_OWNER


def _check_spec(spec: JobSpec) -> None:
    """Every id that reaches a path is a plain name; ``ValueError`` otherwise."""
    from engine.games.manifest import is_valid_slug

    check_save_id(spec.mid, what="media id")
    check_save_id(spec.save_id)
    if spec.owner:
        check_save_id(spec.owner, what="owner")
    if spec.slug and not is_valid_slug(spec.slug):
        raise ValueError(f"not a story slug: {spec.slug!r}")


class SaveGone(Exception):
    """The job's save folder no longer exists (deleted or purged): nothing is written."""


def _save_folder(spec: JobSpec) -> Path:
    """The save's own folder (what ``SaveStore._dir`` names), which a write requires to exist."""
    from engine.persistence.saves import save_store_for

    return save_store_for(spec.owner, spec.slug or None).root / check_save_id(spec.save_id)


def write_media(spec: JobSpec, name: str, data: bytes) -> Path:
    """
    Store one file of ``spec``'s save: the name checked first, then the save
    folder required to exist (a delete or a purge since the job began writes
    nothing and creates no folder), then the atomic write, which makes only
    the save's media folder.
    """
    storage.check_name(name)
    if not _save_folder(spec).is_dir():
        raise SaveGone(f"save {spec.save_id} is gone")
    target = storage.phone_media_dir(spec.owner, spec.save_id) / name
    write_bytes_atomic(target, data)
    return target


class MediaJobWorker:
    """The phone's media queue and its one worker thread (spec §13.4)."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], ComfyClient],
        on_done: Callable[[JobSpec, JobResult], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Optional[Callable[[float], None]] = None,
        today: Callable[[], str] = _local_today,
        start: bool = True,
    ) -> None:
        self._client_factory = client_factory
        self._on_done = on_done
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._lock = threading.Lock()
        self._queue: list[tuple[int, JobSpec]] = []
        self._seq = itertools.count()
        self._last_account: Optional[str] = None
        self._running: Optional[tuple[str, str, str, str]] = None
        #: A resubmission of the RUNNING job: the newer spec its result is handed off with.
        self._respec: dict[tuple[str, str, str, str], JobSpec] = {}
        self._day = ""
        self._spent: dict[str, int] = {}
        self._capped: set[str] = set()
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._attempts = 0  # the running job's submits so far (the worker thread's own)
        if start:
            self.start()

    # -- the queue -------------------------------------------------------

    def submit(self, spec: JobSpec) -> bool:
        """
        Queue a copy of ``spec``. False when the account's daily cap is spent
        (the caller shows the procedural tile), or when its media id, owner,
        save id or slug is not a plain name (refused, logged). A job already queued or running
        under the same owner, save, ``mid`` AND request (``digest``: the same
        workflow and values -- a resume's resubmission) is not queued twice:
        True -- and its result goes to the NEWER spec's run (its
        ``session_id`` and ``epoch``), so a resumed run is handed the job it
        resubmitted. A different request under the same ``mid`` is another job,
        stored under its own file name: an older run's job is never handed to,
        nor written over, a newer run's different medium.
        """
        try:
            _check_spec(spec)
        except ValueError as exc:
            logger.warning("[media] Job refused (operation=submit, mid=%r): %s", spec.mid, exc)
            return False
        cap = int(get_config().get("phone_media.daily_job_cap", 40))
        today = self._today()
        account = _account(spec)
        # A copy: the caller's spec is never changed (its account normalised,
        # its age stamped).
        spec = dataclasses.replace(spec, account=account, created=spec.created or self._clock())
        refused = log_refusal = False
        with self._lock:
            if today != self._day:
                self._day, self._spent, self._capped = today, {}, set()
            key = _key(spec)
            if self._running == key:
                self._respec[key] = spec
                return True
            for i, (seq, queued) in enumerate(self._queue):
                if _key(queued) == key:
                    self._queue[i] = (seq, dataclasses.replace(queued, session_id=spec.session_id, epoch=spec.epoch))
                    return True
            refused, log_refusal = self._spend_locked(account, cap)
            if not refused:
                self._queue.append((next(self._seq), spec))
        if refused:
            self._log_cap(log_refusal, account, cap, today)
            return False
        self._wake.set()
        return True

    def charge(self, spec: JobSpec) -> bool:
        """
        One job of ``spec``'s account against ``phone_media.daily_job_cap``
        WITHOUT queueing it here: a voice note, spoken by the speech worker
        but counted with the account's images and videos (v0.22.0 T21 review
        I2). False -- logged once per account per day, as ``submit`` logs --
        when the day's cap is spent.
        """
        cap = int(get_config().get("phone_media.daily_job_cap", 40))
        today = self._today()
        account = _account(spec)
        with self._lock:
            if today != self._day:
                self._day, self._spent, self._capped = today, {}, set()
            refused, log_refusal = self._spend_locked(account, cap)
        if refused:
            self._log_cap(log_refusal, account, cap, today)
            return False
        return True

    def _spend_locked(self, account: str, cap: int) -> tuple[bool, bool]:
        """(refused, log it) -- one of ``account``'s jobs today spent unless the cap is (CALLER HOLDS ``_lock``)."""
        spent = self._spent.get(account, 0)
        if spent >= cap:
            log_refusal = account not in self._capped
            self._capped.add(account)
            return True, log_refusal
        self._spent[account] = spent + 1
        return False, False

    @staticmethod
    def _log_cap(log_refusal: bool, account: str, cap: int, today: str) -> None:
        if log_refusal:  # once per account per day
            logger.info(
                "[media] Daily job cap reached; further media are procedural today "
                "(operation=submit, account=%s, cap=%d, day=%s)",
                account,
                cap,
                today,
            )

    def pending(self) -> int:
        """Jobs queued and not yet started."""
        with self._lock:
            return len(self._queue)

    def _pick(self) -> Optional[JobSpec]:
        """Priority (0 thread media, 1 own photos, 2 portraits), then account round-robin, then age."""
        with self._lock:
            if not self._queue:
                return None
            best_priority = min(spec.priority for _, spec in self._queue)
            tier = [(seq, s) for seq, s in self._queue if s.priority == best_priority]
            accounts = sorted({s.account for _, s in tier})
            start = 0
            if self._last_account in accounts:
                start = (accounts.index(self._last_account) + 1) % len(accounts)
            account = accounts[start]
            entry = min((e for e in tier if e[1].account == account), key=lambda e: (e[1].created, e[0]))
            self._queue.remove(entry)
            self._last_account = account
            self._running = _key(entry[1])
            return entry[1]

    # -- the thread ------------------------------------------------------

    def start(self) -> None:
        """Start the one worker thread (once)."""
        with self._lock:
            if self._thread is not None:
                return
            thread = self._thread = threading.Thread(target=self._loop, name="media-jobs", daemon=True)
        thread.start()

    def stop(self) -> None:
        """Stop: a job sleeping between polls is abandoned at once (pre-flight F13)."""
        self._stopping.set()
        self._wake.set()

    def join(self, timeout: float) -> bool:
        """True once the worker thread has ended (or never started)."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _pause(self, seconds: float) -> None:
        """The poll sleep: returns at once on ``stop()``, then raises ``cancelled``."""
        if self._sleep is not None:
            self._sleep(seconds)
        else:
            self._stopping.wait(seconds)
        if self._stopping.is_set():
            raise ComfyError("cancelled", "the media worker stopped")

    def _loop(self) -> None:
        while not self._stopping.is_set():
            self._wake.clear()
            # Re-checked AFTER the clear: a stop() between the loop's check
            # and the clear would otherwise have its wake erased (review I1).
            if self._stopping.is_set():
                break
            spec = self._pick()
            if spec is None:
                self._wake.wait(_IDLE_WAIT_SECONDS)
                continue
            self._attempts = 0
            try:
                result = self._run_one(spec)
            except Exception as exc:  # noqa: BLE001 -- step 9: never a raise, never a dead worker
                logger.exception("[media] Job crashed (operation=job, mid=%s)", spec.mid)
                result = JobResult(
                    spec.mid,
                    "failed",
                    error=f"crash: {type(exc).__name__}: {str(exc)[:300]}",
                    attempts=self._attempts,
                )
            finally:
                with self._lock:
                    self._running = None
                    newer = self._respec.pop(_key(spec), None)
            if newer is not None:
                spec = dataclasses.replace(spec, session_id=newer.session_id, epoch=newer.epoch)
            if result.status == "abandoned":
                break
            try:
                self._on_done(spec, result)
            except Exception:  # noqa: BLE001 -- a hand-off fault must not end the worker
                logger.exception("[media] Hand-off failed (operation=on_done, mid=%s)", spec.mid)
        logger.info("[media] Media job worker stopped (operation=stop, left=%d)", self.pending())

    # -- one job ---------------------------------------------------------

    def _run_one(self, spec: JobSpec) -> JobResult:
        cfg = get_config()
        retries = int(cfg.get("comfyui.retries", 1))
        poll_seconds = float(cfg.get("comfyui.poll_seconds", 1.5))
        job_timeout = float(cfg.get("comfyui.job_timeout_seconds", 600))
        attempts = 0
        client = self._client_factory()
        try:
            wf = load_workflow(spec.workflow)  # 1. build (a BindingError is FAILED)
            values = dict(spec.values)
            if spec.reference is not None and "reference_image" in wf.bindings:
                values["reference_image"] = client.upload_image(spec.reference, f"{spec.stem()}_ref.png")  # 2.
            graph = bind(wf, values)
            while True:
                attempts += 1
                self._attempts = attempts
                try:
                    prompt_id = client.submit(graph, client_id=spec.mid)  # 3. submit
                    logger.info("[media] Submitted (operation=job, mid=%s, prompt=%s)", spec.mid, prompt_id)
                    entry = client.wait(  # 4. poll (raises "cancelled" once stopped, F13)
                        prompt_id, poll_seconds=poll_seconds, timeout=job_timeout, sleep=self._pause, now=self._clock
                    )
                    break
                except ComfyError as exc:
                    if exc.kind == "execution" and attempts <= retries:
                        logger.info(
                            "[media] Execution error, resubmitting (operation=job, mid=%s, attempt=%d)",
                            spec.mid,
                            attempts,
                        )
                        continue
                    raise
            files = client.outputs(entry, wf.output_node)  # 5. collect
            if not files:
                raise ComfyError("http", "no output files")
            main = _main_file(files, wf.output_kind)
            data = client.fetch(main)  # 6. fetch (capped)
            sniffed = storage.sniff(data)
            is_video = sniffed is not None and sniffed[0] in ("mp4", "webm")
            if sniffed is None or is_video != (wf.output_kind == "video"):
                raise ComfyError("bad_type", f"output is not a {wf.output_kind}")
            ext, _mime = sniffed
            target = write_media(spec, f"{spec.stem()}.{ext}", data)  # 7. store (the save must still exist)
            poster = ""
            if wf.output_kind == "video":
                candidates = client.outputs(entry, wf.poster_node) if wf.poster_node else files
                poster = self._store_poster(client, candidates, spec, main=main)
            logger.info("[media] Stored (operation=job, mid=%s, kind=%s, bytes=%d)", spec.mid, wf.output_kind, len(data))
            return JobResult(
                spec.mid,
                "ready",
                url=storage.url_for(spec.save_id, target.name),
                path=str(target),
                poster_url=poster,
                kind=wf.output_kind,
                attempts=attempts,
            )
        except ComfyError as exc:
            if exc.kind == "cancelled":  # stop() during a poll sleep (F13)
                logger.info("[media] Job abandoned: the worker stopped (operation=job, mid=%s)", spec.mid)
                return JobResult(spec.mid, "abandoned", error="cancelled", attempts=attempts)
            logger.warning("[media] Job failed (operation=job, mid=%s, kind=%s): %s", spec.mid, exc.kind, exc)
            return JobResult(spec.mid, "failed", error=f"{exc.kind}: {exc.detail[:300]}", attempts=attempts)
        except SaveGone as exc:
            logger.info("[media] Job dropped: its save is gone (operation=job, mid=%s)", spec.mid)
            return JobResult(spec.mid, "failed", error=f"save_gone: {exc}", attempts=attempts)
        except (BindingError, OSError, ValueError) as exc:  # 9. failure: never a raise
            if isinstance(exc, BindingError):
                kind = "binding"
            elif isinstance(exc, OSError):
                kind = type(exc).__name__
            else:
                kind = "invalid"  # an id or a name that is not a plain name: never a path
            logger.warning("[media] Job failed (operation=job, mid=%s, kind=%s): %s", spec.mid, kind, exc)
            return JobResult(spec.mid, "failed", error=f"{kind}: {str(exc)[:300]}", attempts=attempts)
        finally:
            client.close()

    def _store_poster(self, client: ComfyClient, files: list[dict], spec: JobSpec,
                      main: Optional[dict] = None) -> str:
        """
        A video's poster (Plan decision 29; T20 fix round 1): the first
        ``images`` file of ``files`` (the ``poster_node``'s outputs, else the
        output node's) that is not ``main`` (the clip) and is named as an
        image -- chosen BEFORE any fetch, so native ``SaveWEBM``'s clip
        listed under ``images`` is never downloaded twice -- fetched
        (capped), sniffed (an image, else none) and stored as
        ``<mid>_poster.<ext>`` beside the video; its URL, or ``""`` when there
        is none (the client then shows the procedural tile).
        """
        image = next((f for f in files if f.get("key") == "images" and not _same_file(f, main)
                      and Path(str(f.get("filename", ""))).suffix.lower() in _POSTER_SUFFIXES), None)
        if image is None:
            return ""
        storage.check_name(f"{spec.stem()}_poster.png")  # a bad id fails before any fetch (ValueError)
        data = client.fetch(image)
        sniffed = storage.sniff(data)
        if sniffed is None or sniffed[0] not in ("png", "jpg", "webp"):
            logger.warning("[media] Poster is not an image (operation=job, mid=%s)", spec.mid)
            return ""
        name = f"{spec.stem()}_poster.{sniffed[0]}"
        write_media(spec, name, data)
        return storage.url_for(spec.save_id, name)


#: The file names a poster candidate may carry (``storage.sniff``'s images).
_POSTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _same_file(a: dict, b: Optional[dict]) -> bool:
    """The same ComfyUI output file (its filename, subfolder and type)."""
    return b is not None and all(str(a.get(k, "")) == str(b.get(k, "")) for k in ("filename", "subfolder", "type"))


def _main_file(files: list[dict], kind: str) -> dict:
    """The main output: the first file under the kind's own keys, else the first file."""
    keys = _MAIN_KEYS.get(kind, ())
    return next((f for f in files if f.get("key") in keys), files[0])


# -- the process's one worker ------------------------------------------------

_worker: Optional[MediaJobWorker] = None
#: Guards building and dropping ``_worker``: two first callers would start two
#: worker threads (``max_concurrent: 1``).
_worker_lock = threading.Lock()
renew_after_fork(globals(), _worker_lock=threading.Lock)

#: The hand-off for the process's worker (T19 sets it: the session's side).
_on_done: Optional[Callable[[JobSpec, JobResult], None]] = None
#: The client factory for the process's worker when not ``from_config``
#: (tests and the ``stub`` provider set it before the worker is built).
_client_factory: Optional[Callable[[], ComfyClient]] = None


def set_on_done(fn: Optional[Callable[[JobSpec, JobResult], None]]) -> None:
    """Where the process's worker hands a finished job (T19: the session)."""
    global _on_done
    _on_done = fn


def set_client_factory(fn: Optional[Callable[[], ComfyClient]]) -> None:
    """The client the process's worker builds per job; None is ``ComfyClient.from_config``."""
    global _client_factory
    _client_factory = fn


def _hand_off(spec: JobSpec, result: JobResult) -> None:
    fn = _on_done
    if fn is None:
        logger.info("[media] No hand-off set; result kept only on disk (operation=on_done, mid=%s)", spec.mid)
        return
    fn(spec, result)


def _build_client() -> ComfyClient:
    factory = _client_factory
    return factory() if factory is not None else ComfyClient.from_config()


def get_media_worker() -> MediaJobWorker:
    """The process's one media job worker (double-checked: no lock once built)."""
    global _worker
    worker = _worker
    if worker is not None:
        return worker
    with _worker_lock:
        if _worker is None:
            _worker = MediaJobWorker(client_factory=_build_client, on_done=_hand_off, start=False)
        worker = _worker
    worker.start()  # with the lock released; start() is idempotent
    return worker


def reset_media_worker(timeout: float = 10.0) -> bool:
    """
    Stop and drop the process's worker (a drain, tests). The reference is
    swapped under the lock; the old worker is stopped and joined after it.
    True when its thread ended within ``timeout``.
    """
    global _worker
    with _worker_lock:
        old, _worker = _worker, None
    if old is None:
        return True
    old.stop()
    return old.join(timeout)


__all__ = [
    "JobResult",
    "JobSpec",
    "MediaJobWorker",
    "SaveGone",
    "get_media_worker",
    "reset_media_worker",
    "set_client_factory",
    "set_on_done",
    "write_media",
]
