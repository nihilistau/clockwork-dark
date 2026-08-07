"""
Media Queue
===========

In-memory job queue for images, cutscenes, and TTS.

Version: v0.1.0 [2026-06-20]
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MediaJob:
    """Single media generation job."""

    job_id: str
    kind: str
    cache_key: str
    prompt: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    url: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "cache_key": self.cache_key,
            "prompt": self.prompt,
            "payload": dict(self.payload),
            "status": self.status,
            "url": self.url,
            "error": self.error,
        }


def make_cache_key(
    location_id: str,
    time_of_day: str,
    phase_bucket: str,
) -> str:
    """Hash cache key per DESIGN: location + time + evil phase."""
    raw = f"{location_id}|{time_of_day}|{phase_bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_image_tag(tag: str) -> tuple[str, str]:
    """
    Parse image tag like edgewood_square_dawn into location and time.

    Args:
        tag: StreamProcessor image request id.

    Returns:
        (location_id, time_of_day)
    """
    known_times = ("dawn", "noon", "dusk", "night", "mist", "rain")
    for suffix in known_times:
        needle = f"_{suffix}"
        if tag.endswith(needle):
            return tag[: -len(needle)], suffix
    return tag, "dawn"


class MediaQueue:
    """Thread-local style in-memory media job queue."""

    def __init__(self) -> None:
        self._jobs: list[MediaJob] = []
        self._by_cache: dict[str, MediaJob] = {}

    def enqueue(self, job: MediaJob) -> MediaJob:
        """Add job to queue; dedupe by cache_key unless newer status wins."""
        if job.cache_key and job.cache_key in self._by_cache:
            existing = self._by_cache[job.cache_key]
            if job.status == "cached" and existing.status != "cached":
                self._by_cache[job.cache_key] = job
                self._jobs.append(job)
                return job
            return existing
        self._jobs.append(job)
        if job.cache_key:
            self._by_cache[job.cache_key] = job
        return job

    def all_jobs(self) -> list[MediaJob]:
        return list(self._jobs)

    def clear(self) -> None:
        self._jobs.clear()
        self._by_cache.clear()

    def new_job_id(self) -> str:
        return uuid.uuid4().hex[:12]


_queue: Optional[MediaQueue] = None


def get_media_queue() -> MediaQueue:
    """Return singleton media queue."""
    global _queue
    if _queue is None:
        _queue = MediaQueue()
    return _queue


def reset_media_queue() -> MediaQueue:
    """Reset queue — for tests."""
    global _queue
    _queue = MediaQueue()
    return _queue