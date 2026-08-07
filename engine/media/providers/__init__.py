"""
Image providers — selection and the background generation queue.

Ordering is a fallback chain, not a preference list: the configured provider is
tried first and the procedural stand-in always terminates it, so the game never
renders a broken image regardless of what is installed or running.

Version: v0.2.0 [2026-08-07]
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from engine.config import get_config
from engine.media.providers.base import (
    IMAGE_DIR,
    ImageProvider,
    ImageRequest,
    ImageResult,
    cached_image,
)
from engine.media.providers.procedural import ProceduralProvider
from engine.media.providers.shipped import ShippedArtProvider

logger = logging.getLogger(__name__)


def build_provider(name: str) -> Optional[ImageProvider]:
    if name == "grokbuild":
        from engine.media.providers.grokbuild import GrokImagineProvider

        return GrokImagineProvider()
    if name == "comfyui":
        from engine.media.providers.comfy import ComfyProvider

        return ComfyProvider()
    if name == "procedural":
        return ProceduralProvider()
    logger.warning("[media] Unknown image provider (operation=build_provider, name=%s)", name)
    return None


def active_provider() -> ImageProvider:
    """The configured provider, or the procedural floor if it cannot run."""
    name = str(get_config().get("media.image_provider", "grokbuild"))
    provider = build_provider(name)
    if provider is not None and provider.available():
        return provider
    if provider is not None:
        logger.info(
            "[media] Provider unavailable, using procedural "
            "(operation=active_provider, wanted=%s)",
            name,
        )
    return ProceduralProvider()


def live_generation_enabled() -> bool:
    """
    Whether images may be generated on demand during play.

    Off by default, and that is a measurement rather than a preference: a Grok
    Imagine still takes two to three minutes, which cannot sit in a real-time
    loop. ComfyUI is seconds and is the backend worth enabling this for. Either
    way the shipped pack covers the common case, so live generation is for
    filling gaps, not for running the game.
    """
    return bool(get_config().get("media.live_generation", False))


def peek(request: ImageRequest) -> ImageResult:
    """
    Instant result. Never blocks, always returns something renderable.

    Resolution order:
        1. shipped art pack   authored, free, correct
        2. disk cache         generated in an earlier session
        3. procedural SVG     deterministic, offline, never fails
    """
    shipped = ShippedArtProvider()
    if shipped.available():
        result = shipped.generate(request)
        if result.ok:
            return result

    hit = cached_image(request)
    if hit:
        return hit

    return ProceduralProvider().generate(request)


class ImageWorker:
    """
    Background generation queue.

    Single worker: both real backends are GPU- or API-bound and contend with
    the language model, and a second concurrent generation is not faster for
    having started.
    """

    def __init__(self, *, on_ready: Optional[Callable[[ImageRequest, ImageResult], None]] = None) -> None:
        self._queue: "queue.Queue[Optional[ImageRequest]]" = queue.Queue()
        self._seen: set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._on_ready = on_ready

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="image-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def submit(self, request: ImageRequest) -> bool:
        """
        Queue a request. Returns False if nothing needs generating.

        Skipped entirely when live generation is off, which is the default --
        the shipped pack already answered, so there is nothing to improve on
        and no reason to spend minutes of GPU on it.
        """
        if not live_generation_enabled():
            return False
        key = request.cache_key()
        if key in self._seen or cached_image(request):
            return False
        if ShippedArtProvider().generate(request).ok:
            return False
        self._seen.add(key)
        self._queue.put(request)
        self.start()
        return True

    def pending(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        provider = active_provider()
        while not self._stop.is_set():
            request = self._queue.get()
            if request is None:
                break
            try:
                result = provider.generate(request)
                if result.ok and self._on_ready is not None:
                    self._on_ready(request, result)
            except Exception as exc:  # noqa: BLE001 — one bad image must not kill the worker
                logger.warning("[media] Worker item failed (operation=_run): %s", exc)
            finally:
                self._queue.task_done()


_worker: Optional[ImageWorker] = None


def get_image_worker() -> ImageWorker:
    global _worker
    if _worker is None:
        _worker = ImageWorker()
    return _worker


def reset_image_worker() -> None:
    """Tests only."""
    global _worker
    if _worker is not None:
        _worker.stop()
    _worker = None


__all__ = [
    "IMAGE_DIR",
    "ImageRequest",
    "ImageResult",
    "ImageWorker",
    "active_provider",
    "build_provider",
    "get_image_worker",
    "peek",
    "reset_image_worker",
]
