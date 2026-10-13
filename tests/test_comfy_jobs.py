"""
The phone's media job worker and its storage (v0.22.0 T18; spec §13.2,
§13.4's protocol and scheduling, §13.5).

Every ComfyUI here is ``tests/comfy_stub.py::StubComfy``, in process: nothing
binds, so the file runs in the parallel phase. The one loopback run is
``tests/test_comfy_stub_e2e.py``.
"""

from __future__ import annotations

import itertools
import os
import time
from pathlib import Path
from typing import Any

import pytest

from tests.social_fixtures import _spec, _wait_until, media_root  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _restore_the_overlay() -> Any:
    from engine.config import overlay, set_overlay

    saved = overlay()
    try:
        yield
    finally:
        set_overlay(saved)


def _with_config(values: dict[str, Any]) -> None:
    """Dotted config keys for this test only (the overlay, restored at its end)."""
    from engine.config import deep_merge, overlay, set_overlay

    nested: dict[str, Any] = {}
    for dotted, value in values.items():
        node = nested
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    set_overlay(deep_merge(overlay(), nested))


def _worker(stub, done: list, **kw):
    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker

    kw.setdefault("sleep", lambda s: None)
    return MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test", transport=stub.transport),
                          on_done=lambda spec, result: done.append(result), **kw)


def _jumping_clock():
    """
    A monotonic clock that jumps 250 s per read: a 600 s wait crosses its
    deadline at its third poll, after the stub's two empty answers, so a
    "never" job times out at once and every other script still answers.
    """
    ticks = itertools.count()
    return lambda: float(next(ticks) * 250)


def _video_workflow():
    from engine.media.comfy.workflows import Workflow

    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["0", 0]}},
        "9": {"class_type": "SaveWEBM", "inputs": {"filename_prefix": "video", "images": ["1", 0]}},
    }
    return Workflow(name="video", graph=graph, bindings={"positive": ("1", "text"),
                                                          "filename_prefix": ("9", "filename_prefix")},
                    output_node="9", output_kind="video", size={"width": 480, "height": 480, "frames": 49})


def _stop(worker) -> None:
    worker.stop()
    assert worker.join(5), "the worker's thread did not end"


# -- the protocol ------------------------------------------------------------


def test_a_photo_goes_through_all_nine_steps(media_root) -> None:
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy("ready", polls=2), []
    worker = _worker(stub, done)
    spec = _spec("x1", "photo")
    assert worker.submit(spec)
    _wait_until(lambda: done)
    _stop(worker)
    result = done[0]
    stem = spec.stem()
    assert stem == f"x1-{spec.digest()}"                          # the request's digest names the file (T19 I1)
    assert result.status == "ready" and result.path.endswith(f"{stem}.png")
    assert result.url == f"/api/phone/media/s1/{stem}.png" and result.kind == "image" and result.attempts == 1
    assert Path(result.path).read_bytes().startswith(b"\x89PNG")
    assert Path(result.path).parent == media_root / "phone" / "local" / "s1"
    paths = [r.url.path for r in stub.requests]
    assert paths[0] == "/prompt" and paths.count("/history/p-x1") == 3 and paths[-1] == "/view"


@pytest.mark.parametrize("script, kind", [("node_errors", "node_errors"), ("execution_error", "execution"),
                                          ("never", "timeout"), ("unauthorized", "auth"),
                                          ("oversized", "oversized"), ("wrong_magic", "bad_type")])
def test_every_failure_is_failed_never_raised(media_root, script, kind) -> None:
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy(script), []
    worker = _worker(stub, done, clock=_jumping_clock())     # "never" crosses the deadline at once
    worker.submit(_spec("x2", "photo"))
    _wait_until(lambda: done, timeout=10)
    _stop(worker)
    assert done[0].status == "failed" and done[0].error.startswith(kind), done[0]
    assert not list(media_root.rglob("x2.*")), "a failed job stored a file"
    if script == "never":
        assert stub.requests[-1].url.path == "/interrupt"


def test_an_execution_error_is_retried_once(media_root) -> None:
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy("execution_error_once", polls=0), []
    worker = _worker(stub, done)
    worker.submit(_spec("x3", "photo"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "ready" and done[0].attempts == 2
    prompts = [r for r in stub.requests if r.url.path == "/prompt"]
    assert len(prompts) == 2


def test_the_retries_setting_bounds_the_resubmits(media_root) -> None:
    from tests.comfy_stub import StubComfy

    _with_config({"comfyui.retries": 0})
    stub, done = StubComfy("execution_error_once", polls=0), []
    worker = _worker(stub, done)
    worker.submit(_spec("x3", "photo"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "failed" and done[0].error.startswith("execution") and done[0].attempts == 1


def test_a_video_output_is_stored_with_its_poster(media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    monkeypatch.setattr(jobs, "load_workflow", lambda name: _video_workflow())
    stub, done = StubComfy("video", polls=0), []
    worker = _worker(stub, done)
    spec = _spec("x9", "video")
    worker.submit(spec)
    _wait_until(lambda: done)
    _stop(worker)
    result = done[0]
    stem = spec.stem()
    assert result.status == "ready" and result.kind == "video", result
    assert result.path.endswith(f"{stem}.webm") and result.poster_url.endswith(f"{stem}_poster.png")
    folder = Path(result.path).parent
    assert (folder / f"{stem}.webm").read_bytes().startswith(b"\x1a\x45\xdf\xa3")
    assert (folder / f"{stem}_poster.png").read_bytes().startswith(b"\x89PNG")


def test_a_video_without_an_image_output_has_no_poster(media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    monkeypatch.setattr(jobs, "load_workflow", lambda name: _video_workflow())
    stub, done = StubComfy("video_no_poster", polls=0), []
    worker = _worker(stub, done)
    worker.submit(_spec("x9", "video"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "ready" and done[0].path.endswith(".webm") and done[0].poster_url == ""
    assert Path(done[0].path).name.startswith("x9-")
    assert not list(media_root.rglob("*_poster.*"))


def test_a_png_where_a_video_was_declared_is_bad_type(media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    monkeypatch.setattr(jobs, "load_workflow", lambda name: _video_workflow())
    stub, done = StubComfy("ready", polls=0), []
    worker = _worker(stub, done)
    worker.submit(_spec("x9", "video"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "failed" and done[0].error.startswith("bad_type")


def test_the_real_video_template_runs_through_the_worker(media_root) -> None:
    """
    T20: the shipped `comfyui.workflows.video` (no patch) through the worker.
    The stub answers on every submitted save node, so `ready` with a poster
    means the config's output node is the template's save node.
    """
    from engine.config import get_config
    from engine.media.comfy.workflows import load_workflow
    from tests.comfy_stub import StubComfy

    output_node = str(get_config().get("comfyui.workflows.video.output.node"))
    wf = load_workflow("video")
    assert wf.output_node == output_node and wf.output_kind == "video"
    stub, done = StubComfy("video", polls=0), []
    worker = _worker(stub, done)
    spec = _spec("x9", "video", values={"positive": "a walk", "seed": 5, "width": 480, "height": 832, "frames": 49,
                                       "filename_prefix": "phone/x9"})
    assert worker.submit(spec)
    _wait_until(lambda: done)
    _stop(worker)
    result = done[0]
    assert result.status == "ready" and result.kind == "video", result
    assert result.path.endswith(f"{spec.stem()}.webm") and result.poster_url.endswith(f"{spec.stem()}_poster.png")
    import json

    posted = json.loads(next(r for r in stub.requests if r.url.path == "/prompt").content)["prompt"]
    assert posted[output_node]["inputs"]["filename_prefix"] == "phone/x9"
    assert posted[wf.bindings["frames"][0]]["inputs"][wf.bindings["frames"][1]] == 49


def _views(stub, suffix: str) -> int:
    return sum(1 for r in stub.requests if r.url.path == "/view" and r.url.params.get("filename", "").endswith(suffix))


def test_a_native_savewebm_history_gets_its_poster_from_the_poster_node(media_root, caplog) -> None:
    """
    T20 fix round 1 (I1): ComfyUI's native nodes -- SaveWEBM lists its clip
    under `images` on node 10, SaveImage the first frame on node 12 -- and
    the shipped workflow's `poster_node`: a poster, and the clip fetched once.
    """
    import logging

    from engine.media.comfy.workflows import load_workflow
    from tests.comfy_stub import StubComfy

    assert load_workflow("video").poster_node == "12"
    caplog.set_level(logging.WARNING, logger="engine.media.comfy.jobs")
    stub, done = StubComfy("native_video", polls=0), []
    worker = _worker(stub, done)
    spec = _spec("x9", "video", values={"positive": "a walk", "filename_prefix": "phone/x9"})
    worker.submit(spec)
    _wait_until(lambda: done)
    _stop(worker)
    result = done[0]
    assert result.status == "ready" and result.path.endswith(f"{spec.stem()}.webm"), result
    assert result.poster_url.endswith(f"{spec.stem()}_poster.png")
    assert (Path(result.path).parent / f"{spec.stem()}_poster.png").read_bytes().startswith(b"\x89PNG")
    assert _views(stub, ".webm") == 1 and _views(stub, ".png") == 1
    assert not caplog.records


def test_with_no_poster_node_the_clip_is_never_fetched_as_a_poster(media_root, monkeypatch, caplog) -> None:
    """I1: no `poster_node` and a SaveWEBM-shaped output -- no second download, no warning, the tile."""
    import dataclasses
    import logging

    from engine.media.comfy import jobs
    from engine.media.comfy.workflows import load_workflow
    from tests.comfy_stub import StubComfy

    shipped = load_workflow("video")
    monkeypatch.setattr(jobs, "load_workflow", lambda name: dataclasses.replace(shipped, poster_node=""))
    caplog.set_level(logging.WARNING, logger="engine.media.comfy.jobs")
    stub, done = StubComfy("native_video", polls=0), []
    worker = _worker(stub, done)
    worker.submit(_spec("x9", "video", values={"positive": "a walk", "filename_prefix": "phone/x9"}))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "ready" and done[0].path.endswith(".webm") and done[0].poster_url == ""
    assert _views(stub, ".webm") == 1 and _views(stub, ".png") == 0
    assert not caplog.records
    assert not list(media_root.rglob("*_poster.*"))


def test_a_poster_node_not_in_the_template_is_a_load_error(monkeypatch) -> None:
    from engine.config import get_config
    from engine.media.comfy import workflows

    declared = dict(get_config().get("comfyui.workflows.video"))
    declared["output"] = {"node": "10", "kind": "video", "poster_node": "99"}
    _with_config({"comfyui.workflows.video": declared})
    with pytest.raises(workflows.BindingError, match=r"output\.poster_node: node 99"):
        workflows.load_workflow("video")


def test_store_poster_takes_the_first_image_output(media_root) -> None:
    """``_store_poster`` alone (Plan decision 29): the first ``images`` file, else ``""``."""
    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker
    from tests.comfy_stub import StubComfy

    stub = StubComfy("video")
    worker = MediaJobWorker(client_factory=lambda: None, on_done=lambda s, r: None, start=False)
    files = [{"filename": "p-x4.webm", "subfolder": "", "type": "output", "key": "gifs"},
             {"filename": "p-x4.png", "subfolder": "", "type": "output", "key": "images"}]
    with ComfyClient("http://comfy.test", transport=stub.transport) as client:
        spec = _spec("x4", "video", owner="u_0123456789ab", save_id="s2")
        url = worker._store_poster(client, files, spec)
        assert url == f"/api/phone/media/s2/{spec.stem()}_poster.png"
        assert (media_root / "phone" / "u_0123456789ab" / "s2" / f"{spec.stem()}_poster.png").is_file()
        assert worker._store_poster(client, files[:1], _spec("x5", "video")) == ""


def test_a_binding_error_is_failed(media_root, monkeypatch) -> None:
    from engine.media.comfy import jobs
    from engine.media.comfy.workflows import BindingError
    from tests.comfy_stub import StubComfy

    def broken(name: str):
        raise BindingError("comfyui.workflows.photo.bindings.seed: node 99 is not in the template")

    monkeypatch.setattr(jobs, "load_workflow", broken)
    stub, done = StubComfy("ready"), []
    worker = _worker(stub, done)
    worker.submit(_spec("x6", "photo"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].status == "failed" and done[0].error.startswith("binding") and stub.requests == []


def test_a_hand_off_fault_does_not_end_the_worker(media_root) -> None:
    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker
    from tests.comfy_stub import StubComfy

    stub, seen = StubComfy("ready", polls=0), []

    def on_done(spec, result):
        seen.append(result.mid)
        if spec.mid == "x1":
            raise RuntimeError("a hand-off that breaks")

    worker = MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test", transport=stub.transport),
                            on_done=on_done, sleep=lambda s: None)
    worker.submit(_spec("x1", "photo"))
    worker.submit(_spec("x2", "photo"))
    _wait_until(lambda: len(seen) == 2)
    _stop(worker)
    assert seen == ["x1", "x2"]


# -- stopping ----------------------------------------------------------------


def test_stop_abandons_a_job_sleeping_between_polls(media_root) -> None:
    from tests.comfy_stub import StubComfy

    _with_config({"comfyui.job_timeout_seconds": 600, "comfyui.poll_seconds": 30})
    stub, done = StubComfy("never"), []
    worker = _worker(stub, done, sleep=None)                 # the worker's own sleep: the stop event
    began = time.monotonic()
    worker.submit(_spec("x8", "photo"))
    _wait_until(lambda: any(r.url.path.startswith("/history/") for r in stub.requests), timeout=10)
    worker.stop()
    assert worker.join(5), "the worker did not end while its job slept between polls"
    assert done == [], "an abandoned job was handed on"
    assert time.monotonic() - began < 25, "the stop waited out a poll sleep"


def test_a_resubmitted_job_already_queued_is_not_queued_twice(media_root) -> None:
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy("ready", polls=0), []
    worker = _worker(stub, done, start=False)
    assert worker.submit(_spec("x1", "photo"))
    assert worker.submit(_spec("x1", "photo"))
    assert worker.pending() == 1
    worker.start()
    _wait_until(lambda: done)
    _stop(worker)
    assert [r.mid for r in done] == ["x1"]


# -- scheduling --------------------------------------------------------------


def test_priority_then_round_robin_then_age(media_root) -> None:
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy("ready", polls=0), []
    worker = _worker(stub, done, start=False)
    rows = list(zip(["x1", "x2", "x3", "x4", "x5"], [2, 0, 1, 0, 0], ["a", "a", "b", "b", "a"]))
    for mid, priority, account in rows:
        assert worker.submit(_spec(mid, "photo", priority=priority, account=account))
    assert worker.pending() == 5
    worker.start()
    _wait_until(lambda: len(done) == 5, timeout=10)
    _stop(worker)
    label = {mid: f"{priority}{account}" for mid, priority, account in rows}
    assert [label[r.mid] for r in done] == ["0a", "0b", "0a", "1b", "2a"]


def test_the_daily_cap_turns_further_jobs_procedural(media_root, caplog) -> None:
    from tests.comfy_stub import StubComfy

    _with_config({"phone_media.daily_job_cap": 2})
    day = ["2026-10-12"]
    worker = _worker(StubComfy("ready"), [], start=False, today=lambda: day[0])
    assert worker.submit(_spec("x1", "photo", account="a"))
    assert worker.submit(_spec("x2", "photo", account="a"))
    with caplog.at_level("INFO", logger="engine.media.comfy.jobs"):
        assert worker.submit(_spec("x3", "photo", account="a")) is False
        assert worker.submit(_spec("x4", "photo", account="a")) is False
    assert sum("Daily job cap" in r.getMessage() for r in caplog.records) == 1, "logged once per account per day"
    assert worker.submit(_spec("x5", "photo", account="b")), "another account has its own cap"
    day[0] = "2026-10-13"
    assert worker.submit(_spec("x3", "photo", account="a"))
    assert worker.pending() == 4


# -- storage -----------------------------------------------------------------


def test_media_paths_are_owner_scoped_and_never_traverse(media_root) -> None:
    from engine.media.comfy import storage

    assert storage.phone_media_dir("acct1", "s1") == media_root / "phone" / "acct1" / "s1"
    assert storage.phone_media_dir("", "s1") == media_root / "phone" / "local" / "s1"
    for bad in ("../x", "a/b", "..", "", "x\\y"):
        with pytest.raises(ValueError):
            storage.phone_media_dir("acct1", bad)
    with pytest.raises(ValueError):
        storage.phone_media_dir("../acct2", "s1")
    assert storage.url_for("s1", "x1.png") == "/api/phone/media/s1/x1.png"
    for bad in ("../x1.png", "x1.exe", "x1", ".png"):
        with pytest.raises(ValueError):
            storage.url_for("s1", bad)


def test_sniff_reads_magic_bytes() -> None:
    from engine.media.comfy.storage import sniff
    from tests.comfy_stub import png_bytes, webm_bytes

    assert sniff(png_bytes()) == ("png", "image/png")
    assert sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 16) == ("jpg", "image/jpeg")
    assert sniff(b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 8) == ("webp", "image/webp")
    assert sniff(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8) == ("mp4", "video/mp4")
    assert sniff(webm_bytes()) == ("webm", "video/webm")
    assert sniff(b"<html>not media</html>") is None
    assert sniff(b"") is None


def test_write_bytes_atomic_leaves_no_partial_file(tmp_path, monkeypatch) -> None:
    from engine.persistence import atomic

    target = tmp_path / "out" / "x1.png"
    atomic.write_bytes_atomic(target, b"first")
    assert target.read_bytes() == b"first"

    def refuse(*_a: Any, **_k: Any) -> None:
        raise OSError("replace refused")

    monkeypatch.setattr(atomic.os, "replace", refuse)
    with pytest.raises(OSError):
        atomic.write_bytes_atomic(target, b"second")
    assert target.read_bytes() == b"first", "a failed write touched the destination"
    assert sorted(p.name for p in target.parent.iterdir()) == ["x1.png"], "a temp file was left"

    fresh = tmp_path / "new" / "x2.png"
    with pytest.raises(OSError):
        atomic.write_bytes_atomic(fresh, b"data")
    assert list(fresh.parent.iterdir()) == [], "a failed first write left a file"


def test_deleting_a_save_removes_its_phone_media(media_root) -> None:
    from engine.media.comfy import storage
    from engine.persistence.saves import save_store_for

    for owner in ("", "u_0123456789ab"):
        folder = storage.phone_media_dir(owner, "s1")
        folder.mkdir(parents=True)
        (folder / "x1.png").write_bytes(b"\x89PNG")
        keep = storage.phone_media_dir(owner, "s2")
        keep.mkdir(parents=True)
        save_store_for(owner, "clockwork-dark").delete("s1")
        assert not folder.exists(), f"owner {owner!r}: the deleted save's media stayed"
        assert keep.is_dir(), "another save's media went with it"


def test_purging_an_account_removes_its_phone_media(media_root, monkeypatch, tmp_path) -> None:
    from engine.hosting import accounts
    from engine.media.comfy import storage

    account = type("A", (), {"id": "u_0123456789ab"})()
    folder = storage.phone_media_dir(account.id, "s1")
    folder.mkdir(parents=True)
    other = storage.phone_media_dir("u_ba9876543210", "s1")
    other.mkdir(parents=True)
    assert accounts.purge_user_dir(account) is True
    assert not storage.phone_owner_dir(account.id).exists()
    assert other.is_dir()
    assert accounts.purge_user_dir(account) is False


# -- the process's worker ----------------------------------------------------


def test_the_process_worker_is_built_once_and_hands_off(media_root) -> None:
    from engine.media.comfy import jobs
    from engine.media.comfy.client import ComfyClient
    from tests.comfy_stub import StubComfy

    stub, got = StubComfy("ready", polls=0), []
    jobs.set_client_factory(lambda: ComfyClient("http://comfy.test", transport=stub.transport))
    jobs.set_on_done(lambda spec, result: got.append((spec.mid, result.status)))
    try:
        worker = jobs.get_media_worker()
        assert jobs.get_media_worker() is worker
        worker.submit(_spec("x1", "photo"))
        _wait_until(lambda: got)
        assert got == [("x1", "ready")]
    finally:
        jobs.set_client_factory(None)
        jobs.set_on_done(None)
        assert jobs.reset_media_worker(10)
    assert jobs._worker is None
    assert os.path.isfile(media_root / "phone" / "local" / "s1" / f"{_spec('x1', 'photo').stem()}.png")


# -- review fix round 1 ------------------------------------------------------


def test_a_stop_at_the_wake_clear_still_ends_the_worker(media_root) -> None:
    """I1: a stop() landing between the loop's check and its clear is not lost."""
    from tests.comfy_stub import StubComfy

    worker = _worker(StubComfy("ready"), [], start=False)
    real_clear = worker._wake.clear

    def clear_after_a_stop() -> None:
        worker.stop()          # the race: stop() sets _stopping and _wake ...
        real_clear()           # ... and the loop's clear erases the wake

    worker._wake.clear = clear_after_a_stop  # type: ignore[method-assign]
    worker.start()
    assert worker.join(3), "the worker slept through a stop() that landed at its clear"


@pytest.mark.parametrize("field, value", [("mid", "../x"), ("mid", "a/b"), ("save_id", "../s1"),
                                          ("save_id", ""), ("owner", "../u_0123456789ab")])
def test_a_bad_id_is_refused_at_submit(media_root, field, value) -> None:
    from tests.comfy_stub import StubComfy

    worker = _worker(StubComfy("ready"), [], start=False)
    spec = _spec("x1", "photo", saved=False)
    setattr(spec, field, value)
    assert worker.submit(spec) is False
    assert worker.pending() == 0


def test_a_bad_id_past_submit_fails_and_writes_nothing(media_root, monkeypatch) -> None:
    """I2: a spec that never went through submit (a bug) is a failed job, and no path is built from it."""
    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    for script, workflow in (("ready", None), ("video", _video_workflow())):
        if workflow is not None:
            monkeypatch.setattr(jobs, "load_workflow", lambda name, wf=workflow: wf)
        worker = _worker(StubComfy(script, polls=0), [], start=False)
        spec = _spec("x1", "photo")
        spec.mid = "../x"
        result = worker._run_one(spec)
        assert result.status == "failed" and result.error.startswith("invalid"), result
    root = media_root.parent
    assert not [p for p in root.rglob("*") if p.is_file() and p.suffix in (".png", ".webm")], "a file was written"


def test_a_save_deleted_mid_job_gets_no_file(media_root) -> None:
    """I3: the save's folder goes while the job is held; released, the job writes nothing and makes no folder."""
    import shutil

    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    stub, done = StubComfy("hold", polls=0), []
    worker = _worker(stub, done, sleep=lambda s: time.sleep(0.01))
    spec = _spec("x1", "photo", owner="u_0123456789ab")
    worker.submit(spec)
    _wait_until(lambda: any(r.url.path.startswith("/history/") for r in stub.requests), timeout=10)
    shutil.rmtree(jobs._save_folder(spec))          # the delete (or the purge) lands mid-job
    stub.script = "ready"                           # and the server finishes
    _wait_until(lambda: done, timeout=10)
    _stop(worker)
    assert done[0].status == "failed" and done[0].error.startswith("save_gone"), done[0]
    assert not (media_root / "phone" / "u_0123456789ab").exists(), "the worker re-created the purged tree"


def test_submit_neither_mutates_the_callers_spec_nor_splits_the_account(media_root) -> None:
    """M2, M3: one account key for the cap and the round-robin; the caller's spec is left alone."""
    from tests.comfy_stub import StubComfy

    _with_config({"phone_media.daily_job_cap": 1})
    worker = _worker(StubComfy("ready"), [], start=False)
    mine = _spec("x1", "photo", owner="u_0123456789ab")
    assert worker.submit(mine)
    assert mine.created == 0.0 and mine.account == ""
    queued = worker._queue[0][1]
    assert queued is not mine and queued.account == "u_0123456789ab" and queued.created
    # The same account named outright shares the cap.
    assert worker.submit(_spec("x2", "photo", owner="u_0123456789ab", account="u_0123456789ab")) is False


def test_a_crash_keeps_its_kind_and_attempts(media_root, monkeypatch) -> None:
    """M7."""
    from engine.media.comfy import jobs
    from tests.comfy_stub import StubComfy

    def broken(files, kind):
        raise RuntimeError("a bug")

    monkeypatch.setattr(jobs, "_main_file", broken)
    done: list = []
    worker = _worker(StubComfy("ready", polls=0), done)
    worker.submit(_spec("x1", "photo"))
    _wait_until(lambda: done)
    _stop(worker)
    assert done[0].error.startswith("crash: RuntimeError") and done[0].attempts == 1, done[0]


# -- a resumed run's resubmission (v0.22.0 T19) --------------------------------


def test_a_resubmission_of_a_queued_job_goes_to_the_newer_run(media_root) -> None:
    """A resume resubmits a job this process still holds: queued once, handed to the NEWER build of the run."""
    import dataclasses

    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker
    from tests.comfy_stub import StubComfy

    stub, handed = StubComfy("ready", polls=1), []
    worker = MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test", transport=stub.transport),
                            on_done=lambda spec, result: handed.append((spec, result)), sleep=lambda s: None,
                            start=False)
    old = _spec("x1", "photo")
    assert worker.submit(old)
    assert worker.submit(dataclasses.replace(old, session_id="sess-2", epoch=2))
    assert worker.pending() == 1                                    # not queued twice
    worker.start()
    _wait_until(lambda: handed)
    _stop(worker)
    spec, result = handed[0]
    assert result.status == "ready" and (spec.session_id, spec.epoch) == ("sess-2", 2)


def test_a_resubmission_of_the_running_job_goes_to_the_newer_run(media_root) -> None:
    """The same, for the job RUNNING when the resume resubmits it (between its polls)."""
    import dataclasses

    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker
    from tests.comfy_stub import StubComfy

    stub, handed, box = StubComfy("ready", polls=2), [], {}
    old = _spec("x1", "photo")
    newer = dataclasses.replace(old, session_id="sess-2", epoch=2)

    def poll_sleep(_seconds: float) -> None:                        # called while the job is running
        if "again" not in box:
            box["again"] = box["worker"].submit(newer)

    worker = MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test", transport=stub.transport),
                            on_done=lambda spec, result: handed.append((spec, result)), sleep=poll_sleep, start=False)
    box["worker"] = worker
    assert worker.submit(old)
    worker.start()
    _wait_until(lambda: handed)
    _stop(worker)
    spec, result = handed[0]
    assert box["again"] is True and worker.pending() == 0 and len(handed) == 1
    assert result.status == "ready" and (spec.session_id, spec.epoch) == ("sess-2", 2)


def test_a_different_request_under_a_reused_mid_never_reaches_the_newer_run(media_root) -> None:
    """
    T19 review I1: run A (epoch 1) queued x5; a resumed run B (epoch 2), whose
    save predates A's unsaved row, makes ITS own x5 -- a different request.
    The two are two jobs: B is handed only its own values, A's job keeps A's
    run (and is dropped by the hand-off's liveness), and the files differ.
    """
    import dataclasses
    import json

    from engine.media.comfy.client import ComfyClient
    from engine.media.comfy.jobs import MediaJobWorker
    from tests.comfy_stub import StubComfy

    stub, handed = StubComfy("ready", polls=0), []
    worker = MediaJobWorker(client_factory=lambda: ComfyClient("http://comfy.test", transport=stub.transport),
                            on_done=lambda spec, result: handed.append((spec, result)), sleep=lambda s: None,
                            start=False)
    old = _spec("x5", "photo", values={"positive": "a photo of Kai"})
    new = dataclasses.replace(old, session_id="sess-2", epoch=2, values={"positive": "a portrait of Sam"})
    assert worker.submit(old) and worker.submit(new)
    assert worker.pending() == 2                                    # two requests: two jobs
    worker.start()
    _wait_until(lambda: len(handed) == 2)
    _stop(worker)
    for spec, result in handed:
        assert result.status == "ready"
        if spec.epoch == 2:
            assert spec.values == {"positive": "a portrait of Sam"}  # the old values never reach the new run
        else:
            assert spec.values == {"positive": "a photo of Kai"} and spec.session_id == "sess-1"
    assert len({result.path for _, result in handed}) == 2           # neither file written over the other
    posted = [json.loads(r.content)["prompt"] for r in stub.requests if r.url.path == "/prompt"]
    assert len(posted) == 2
