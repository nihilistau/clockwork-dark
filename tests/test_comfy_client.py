"""
The ComfyUI client and workflows (v0.22.0 T17, spec §13.4).

Every route is answered by an in-process ``httpx.MockTransport``: nothing here
binds a port or reaches a server, so the file runs in the parallel phase.
T18 grows the handlers into ``tests/comfy_stub.py``.

The fixed reference for the ``photo`` template is v0.21.1's in-code graph,
recorded verbatim in ``tests/fixtures/comfy_reference.py``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import pytest

from engine.config import get_config
from engine.media.comfy.client import ComfyClient, ComfyError
from engine.media.providers.base import ImageRequest

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8188"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


# -- helpers -----------------------------------------------------------------


def _image_request(subject_id: str, *, kind: str = "location") -> ImageRequest:
    return ImageRequest(subject_id=subject_id, kind=kind)


@pytest.fixture(autouse=True)
def _restore_the_overlay() -> Any:
    """Every ``_with_config`` of a test is undone at its end (the overlay it found)."""
    from engine.config import overlay, set_overlay

    saved = overlay()
    try:
        yield
    finally:
        set_overlay(saved)


def _with_config(monkeypatch: pytest.MonkeyPatch, values: dict[str, Any]) -> None:
    """
    Set dotted config keys for this test only, through the supported route:
    merged into the current config overlay (``set_overlay``), which
    ``_restore_the_overlay`` puts back. ``monkeypatch`` is kept in the
    signature so call sites read as the test-scoped change they are.
    """
    from engine.config import deep_merge, overlay, set_overlay

    nested: dict[str, Any] = {}
    for dotted, value in values.items():
        node = nested
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    set_overlay(deep_merge(overlay(), nested))


def _config_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    bindings: Optional[dict[str, list[str]]] = None,
    output: Optional[dict[str, Any]] = None,
    template: Optional[dict[str, Any]] = None,
) -> None:
    """``comfyui.workflows.photo`` replaced by a copy with the given parts swapped."""
    spec = json.loads(json.dumps(get_config().get("comfyui.workflows.photo")))
    if template is not None:
        path = tmp_path / "template.json"
        path.write_text(json.dumps(template), encoding="utf-8")
        spec["template"] = str(path)
    if bindings is not None:
        spec["bindings"] = bindings
    if output is not None:
        spec["output"] = output
    _with_config(monkeypatch, {"comfyui.workflows.photo": spec})


Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, **kwargs: Any) -> ComfyClient:
    return ComfyClient(BASE, transport=httpx.MockTransport(handler), **kwargs)


def _routes(table: dict[tuple[str, str], Handler], seen: Optional[list[httpx.Request]] = None) -> Handler:
    """A handler answering ``(method, path)`` from ``table``; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        route = table.get((request.method, request.url.path))
        return route(request) if route else httpx.Response(404)

    return handler


# -- the photo workflow ------------------------------------------------------


def test_the_bound_photo_graph_equals_the_old_literal() -> None:
    from engine.media.comfy.workflows import bind, load_workflow
    from tests.fixtures.comfy_reference import build_workflow_v021  # the old function, copied verbatim

    request = _image_request("forest_clearing", kind="scene")
    old = build_workflow_v021(
        request,
        checkpoint="sd_xl_base_1.0.safetensors",
        steps=28,
        cfg_scale=6.5,
        sampler="dpmpp_2m",
        scheduler="karras",
        seed=1234,
    )
    wf = load_workflow("photo")
    new = bind(
        wf,
        {
            "checkpoint": "sd_xl_base_1.0.safetensors",
            "positive": old["2"]["inputs"]["text"],
            "width": old["4"]["inputs"]["width"],
            "height": old["4"]["inputs"]["height"],
            "seed": 1234,
            "steps": 28,
            "cfg_scale": 6.5,
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
            "filename_prefix": old["7"]["inputs"]["filename_prefix"],
        },
    )
    assert new == old
    assert wf.output_node == "7" and wf.output_kind == "image"
    assert wf.size == {"width": 832, "height": 1216}


def test_the_art_provider_binds_the_same_graph_the_old_code_built() -> None:
    """The live provider path, not only ``bind``: its graph is v0.21.1's, seed included."""
    from engine.media.providers.comfy import ComfyProvider
    from tests.fixtures.comfy_reference import build_workflow_v021

    provider = ComfyProvider()
    for request in (_image_request("forest_clearing"), _image_request("bent_nail", kind="item")):
        old = build_workflow_v021(
            request,
            checkpoint=provider.checkpoint,
            steps=provider.steps,
            cfg_scale=provider.cfg_scale,
            sampler=provider.sampler,
            scheduler=provider.scheduler,
            seed=provider._seed_for(request),
        )
        assert provider.graph_for(request) == old, request.kind


def test_the_portrait_workflow_loads_with_its_own_size() -> None:
    from engine.media.comfy.workflows import load_workflow

    wf = load_workflow("portrait")
    assert wf.size == {"width": 896, "height": 1152}
    assert wf.bindings == load_workflow("photo").bindings


def test_a_binding_to_a_missing_node_is_a_load_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.media.comfy import workflows

    _config_workflow(monkeypatch, tmp_path, bindings={"seed": ["99", "seed"]})
    with pytest.raises(workflows.BindingError, match="node 99"):
        workflows.load_workflow("photo")


def test_a_binding_to_a_missing_input_is_a_load_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.media.comfy import workflows

    _config_workflow(monkeypatch, tmp_path, bindings={"seed": ["5", "sead"]})
    with pytest.raises(workflows.BindingError, match=r"comfyui\.workflows\.photo\.bindings\.seed: node 5 .*'sead'"):
        workflows.load_workflow("photo")


def test_a_missing_output_node_or_template_or_workflow_is_a_load_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from engine.media.comfy import workflows

    with pytest.raises(workflows.BindingError, match="no such workflow"):
        workflows.load_workflow("no_such_thing")

    _config_workflow(monkeypatch, tmp_path, output={"node": "42", "kind": "image"})
    with pytest.raises(workflows.BindingError, match=r"output\.node: node 42"):
        workflows.load_workflow("photo")

    _config_workflow(monkeypatch, tmp_path, output={"node": "7", "kind": "hologram"})
    with pytest.raises(workflows.BindingError, match=r"output\.kind"):
        workflows.load_workflow("photo")

    _config_workflow(monkeypatch, tmp_path, output={"node": "7", "kind": "image"}, template={"1": {"class_type": "X"}})
    with pytest.raises(workflows.BindingError, match="no inputs object"):
        workflows.load_workflow("photo")


def test_bind_copies_sets_every_bound_value_and_ignores_unbound_ones() -> None:
    from engine.media.comfy.workflows import bind, load_workflow

    wf = load_workflow("photo")
    before = json.dumps(wf.graph, sort_keys=True)
    graph = bind(wf, {"seed": 7, "positive": "a quiet street", "reference_image": "face.png"})
    assert graph["5"]["inputs"]["seed"] == 7
    assert graph["2"]["inputs"]["text"] == "a quiet street"
    assert "reference_image" not in json.dumps(graph)
    assert graph["3"]["inputs"]["text"] == "", "the negative encode stays empty (v0.15.1)"
    assert json.dumps(wf.graph, sort_keys=True) == before, "bind must not touch the loaded template"


def test_the_shipped_template_carries_no_negative_words() -> None:
    """Rule 12 / v0.15.1: the KSampler's negative conditioning encodes an empty string."""
    graph = json.loads((ROOT / "config" / "comfyui" / "photo_sdxl.json").read_text(encoding="utf-8"))
    encodes = [node for node in graph.values() if node["class_type"] == "CLIPTextEncode"]
    assert len(encodes) == 2
    assert all(node["inputs"]["text"] == "" for node in encodes), "placeholders only; nothing pre-written"
    assert graph["5"]["inputs"]["negative"] == ["3", 0]


#: Spec §13.4's `video` row: the values the engine binds into a video workflow.
VIDEO_BINDINGS = ("positive", "seed", "width", "height", "frames", "filename_prefix")


def test_the_video_template_binds_every_declared_input() -> None:
    """T20 (spec §13.8): `comfyui.workflows.video` loads, and every binding names a node and input of its template."""
    from engine.config import get_config
    from engine.media.comfy.workflows import bind, load_workflow

    wf = load_workflow("video")                                   # raises nothing
    declared = get_config().get("comfyui.workflows.video")
    template = ROOT / declared["template"]
    assert template.name == "video_wan.json"
    graph = json.loads(template.read_text(encoding="utf-8"))
    assert set(wf.bindings) == set(VIDEO_BINDINGS)
    for name, (node_id, input_name) in wf.bindings.items():
        assert node_id in graph and input_name in graph[node_id]["inputs"], name
    assert wf.output_kind == "video" and wf.output_node in graph
    assert "filename_prefix" in graph[wf.output_node]["inputs"]   # the bound save node is the declared output
    assert wf.bindings["filename_prefix"][0] == wf.output_node
    # A 2-4 s clip at 480p (spec §13.8): the frames a latent of Wan's 4n+1 lengths takes at the save's fps.
    assert sorted((wf.size["width"], wf.size["height"])) == [480, 832] and (wf.size["frames"] - 1) % 4 == 0
    assert 2.0 <= wf.size["frames"] / float(graph[wf.output_node]["inputs"]["fps"]) <= 4.0
    bound = bind(wf, {"positive": "a walk in the park", "seed": 11, "width": 480, "height": 832, "frames": 49,
                      "filename_prefix": "phone/x1"})
    assert bound[wf.bindings["positive"][0]]["inputs"]["text"] == "a walk in the park"
    assert bound[wf.bindings["frames"][0]]["inputs"][wf.bindings["frames"][1]] == 49


def test_the_video_template_carries_no_negative_words() -> None:
    """Rule 12 / v0.15.1: the video's negative conditioning encodes an empty string, bound to nothing."""
    from engine.media.comfy.workflows import load_workflow

    graph = json.loads((ROOT / "config" / "comfyui" / "video_wan.json").read_text(encoding="utf-8"))
    encodes = {node_id: node for node_id, node in graph.items() if node["class_type"] == "CLIPTextEncode"}
    assert all(node["inputs"]["text"] == "" for node in encodes.values()), "placeholders only; nothing pre-written"
    sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
    negative = sampler["inputs"]["negative"][0]
    assert negative in encodes and negative != load_workflow("video").bindings["positive"][0]
    assert all(node_id != negative for node_id, _ in load_workflow("video").bindings.values())


# -- the in-turn queue retired -----------------------------------------------

STORYTELLER_REPLY = """
Mist clings to the birch trunks.

```json
{
  "tool_calls": [],
  "narration": "Mist clings to the birch trunks. Edgewood's smoke is a thin grey thread ahead.",
  "choices": [
    {"id": "a", "text": "Walk toward the smoke"},
    {"id": "b", "text": "Forage the clearing"}
  ],
  "npc_voices": [],
  "stat_changes": {},
  "items_gained": [],
  "items_lost": [],
  "skill_check": null,
  "tags_inline": "[IMAGE:forest_clearing_dawn]"
}
```
"""


def _run_one_stub_turn() -> Any:
    """One flagship storyteller turn with a stub llm_fn whose reply carries an [IMAGE:] tag."""
    from engine.agents.storyteller import StorytellerAgent
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state
    from engine.media.queue import reset_media_queue

    reset_media_queue()
    agent = StorytellerAgent(GameEngine(new_game_state(seed=42)), llm_fn=lambda _messages: STORYTELLER_REPLY)
    result = agent.run_turn("The player looks toward the village smoke.")
    assert result.media.get("images"), "the turn queued its still"
    return result


def test_a_flagship_turn_under_comfyui_enabled_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.games import registry

    seen: list = []
    monkeypatch.setattr(
        httpx.Client, "send", lambda self, req, **k: seen.append(req.url) or pytest.fail(f"request to {req.url}")
    )
    registry.activate("clockwork-dark")  # activation rebuilds the config: set the switch after it
    _with_config(monkeypatch, {"comfyui.enabled": True})
    try:
        assert get_config().get("comfyui.enabled") is True
        result = _run_one_stub_turn()  # run_turn with a stub llm_fn whose narration carries an [IMAGE:...] tag
    finally:
        registry.deactivate()
    assert seen == []
    assert all(job["status"] != "submitted" for job in result.media["images"]), result.media["images"]


def test_the_in_turn_queue_answers_a_placeholder_whatever_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.game.engine import GameEngine
    from engine.game.procgen import new_game_state
    from engine.media.comfyui import ComfyUIClient
    from engine.media.queue import reset_media_queue

    jobs = {}
    for enabled in (False, True):
        _with_config(monkeypatch, {"comfyui.enabled": enabled})
        reset_media_queue()
        state = GameEngine(new_game_state(seed=42)).state
        job = ComfyUIClient().enqueue_image("edgewood_square_noon", state)
        jobs[enabled] = (job.status, job.url, job.prompt, job.payload)
    assert jobs[True] == jobs[False]
    assert jobs[True][0] == "placeholder"
    assert not hasattr(ComfyUIClient, "_submit_prompt")


# -- the client ----------------------------------------------------------------


def test_auth_header_carries_the_key() -> None:
    seen: list[httpx.Request] = []
    stats = {("GET", "/system_stats"): lambda r: httpx.Response(200, json={"system": {}})}

    with _client(_routes(stats, seen), api_key="sekrit") as client:
        assert client.system_stats() == {"system": {}}
    assert seen[-1].headers["Authorization"] == "Bearer sekrit"

    with _client(_routes(stats, seen), api_key="sekrit", auth_header="X-API-Key") as client:
        client.system_stats()
    assert seen[-1].headers["X-API-Key"] == "sekrit"
    assert "Authorization" not in seen[-1].headers

    with _client(_routes(stats, seen)) as client:
        client.system_stats()
    assert "Authorization" not in seen[-1].headers, "no key, no header"


def test_from_config_reads_the_connection_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setenv("CLOCKWORK_COMFYUI_API_KEY", "from-env")
    _with_config(
        monkeypatch,
        {
            "comfyui.api_key": "${env:CLOCKWORK_COMFYUI_API_KEY}",
            "comfyui.base_url": "https://comfy.example.invalid/api/",
            "comfyui.auth_header": "X-Comfy-Key",
            "comfyui.max_bytes": 1234,
        },
    )
    handler = _routes({("GET", "/api/system_stats"): lambda r: httpx.Response(200, json={})}, seen)
    with ComfyClient.from_config(httpx.MockTransport(handler)) as client:
        assert client.base_url == "https://comfy.example.invalid/api"
        assert client.max_bytes == 1234
        client.system_stats()
    assert seen[-1].headers["X-Comfy-Key"] == "from-env"
    assert str(seen[-1].url) == "https://comfy.example.invalid/api/system_stats"


def test_a_refused_key_is_auth_and_an_outage_is_unreachable_or_timeout() -> None:
    with _client(lambda r: httpx.Response(401)) as client:
        with pytest.raises(ComfyError) as caught:
            client.submit({}, "job")
    assert caught.value.kind == "auth"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(refuse) as client:
        with pytest.raises(ComfyError) as caught:
            client.system_stats()
    assert caught.value.kind == "unreachable"

    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with _client(stall) as client:
        with pytest.raises(ComfyError) as caught:
            client.history("p1")
    assert caught.value.kind == "timeout"


def test_submit_posts_the_graph_and_returns_the_prompt_id() -> None:
    seen: list[httpx.Request] = []
    table = {("POST", "/prompt"): lambda r: httpx.Response(200, json={"prompt_id": "p-1", "number": 3})}
    with _client(_routes(table, seen)) as client:
        assert client.submit({"1": {"class_type": "X", "inputs": {}}}, "job-key") == "p-1"
    body = json.loads(seen[-1].content)
    assert body == {"prompt": {"1": {"class_type": "X", "inputs": {}}}, "client_id": "job-key"}

    table = {("POST", "/prompt"): lambda r: httpx.Response(200, json={})}
    with _client(_routes(table)) as client:
        with pytest.raises(ComfyError, match="no prompt_id") as caught:
            client.submit({}, "job")
    assert caught.value.kind == "http"


def test_node_errors_are_failed_and_kept() -> None:
    node_errors = {"1": {"errors": [{"type": "value_not_in_list", "details": "ckpt_name: 'missing.safetensors'"}]}}
    table = {
        ("POST", "/prompt"): lambda r: httpx.Response(
            400, json={"error": {"type": "prompt_outputs_failed_validation"}, "node_errors": node_errors}
        )
    }
    with _client(_routes(table)) as client:
        with pytest.raises(ComfyError) as caught:
            client.submit({}, "job")
    assert caught.value.kind == "node_errors"
    assert json.loads(caught.value.detail) == node_errors, "the server's errors are kept whole"


def test_an_execution_error_raises_execution() -> None:
    messages = [["execution_error", {"node_id": "5", "exception_message": "CUDA out of memory"}]]
    table = {
        ("GET", "/history/p-1"): lambda r: httpx.Response(
            200, json={"p-1": {"status": {"status_str": "error", "completed": False, "messages": messages}}}
        )
    }
    with _client(_routes(table)) as client:
        with pytest.raises(ComfyError) as caught:
            client.history("p-1")
    assert caught.value.kind == "execution"
    assert "CUDA out of memory" in caught.value.detail


def test_history_is_none_until_done_then_the_entry() -> None:
    answers = iter(
        [
            {},
            {"p-1": {"status": {"status_str": "success", "completed": False}, "outputs": {}}},
            {"p-1": {"status": {"status_str": "success", "completed": True}, "outputs": {"7": {"images": []}}}},
        ]
    )
    table = {("GET", "/history/p-1"): lambda r: httpx.Response(200, json=next(answers))}
    with _client(_routes(table)) as client:
        assert client.history("p-1") is None
        assert client.history("p-1") is None
        assert client.history("p-1")["status"]["completed"] is True


def test_a_job_past_its_timeout_interrupts_and_raises() -> None:
    seen: list[httpx.Request] = []
    table = {
        ("GET", "/history/p-1"): lambda r: httpx.Response(200, json={}),
        ("POST", "/interrupt"): lambda r: httpx.Response(200),
    }
    clock = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += 400.0  # each poll jumps the clock

    with _client(_routes(table, seen)) as client:
        with pytest.raises(ComfyError) as caught:
            client.wait("p-1", poll_seconds=1.5, timeout=600, sleep=sleep, now=lambda: clock[0])
    assert caught.value.kind == "timeout"
    assert sleeps == [1.5, 1.5], "polled every poll_seconds until past the deadline, then stopped"
    assert [(r.method, r.url.path) for r in seen][-1] == ("POST", "/interrupt")
    assert sum(1 for r in seen if r.url.path == "/interrupt") == 1


def test_an_interrupt_that_fails_still_raises_the_timeout() -> None:
    table = {("GET", "/history/p-1"): lambda r: httpx.Response(200, json={})}  # /interrupt answers 404
    with _client(_routes(table)) as client:
        with pytest.raises(ComfyError) as caught:
            client.wait("p-1", poll_seconds=0, timeout=0, sleep=lambda s: None)
    assert caught.value.kind == "timeout"


def test_outputs_collects_every_file_key_of_the_declared_node() -> None:
    entry = {
        "outputs": {
            "7": {
                "images": [{"filename": "a.png", "subfolder": "x", "type": "output"}],
                "gifs": [{"filename": "b.webm", "subfolder": "", "type": "output"}],
            },
            "9": {"images": [{"filename": "other.png"}]},
        }
    }
    files = ComfyClient.outputs(entry, "7")
    assert [(f["filename"], f["key"]) for f in files] == [("a.png", "images"), ("b.webm", "gifs")]
    assert ComfyClient.outputs(entry, "8") == []


def test_an_oversized_view_is_refused() -> None:
    def view(size: int) -> Handler:
        return _routes({("GET", "/view"): lambda r: httpx.Response(200, content=b"x" * size)})

    ref = {"filename": "a.png", "subfolder": "", "type": "output"}
    with _client(view(64), max_bytes=64) as client:
        assert client.fetch(ref) == b"x" * 64
    with _client(view(65), max_bytes=64) as client:
        with pytest.raises(ComfyError) as caught:
            client.fetch(ref)
    assert caught.value.kind == "oversized"


def test_fetch_passes_the_file_reference_and_maps_a_refusal() -> None:
    seen: list[httpx.Request] = []
    with _client(_routes({("GET", "/view"): lambda r: httpx.Response(200, content=PNG)}, seen)) as client:
        assert client.fetch({"filename": "a.png", "subfolder": "sub", "type": "temp"}) == PNG
    assert dict(seen[-1].url.params) == {"filename": "a.png", "subfolder": "sub", "type": "temp"}

    with _client(lambda r: httpx.Response(403)) as client:
        with pytest.raises(ComfyError) as caught:
            client.fetch({"filename": "a.png"})
    assert caught.value.kind == "auth"


def test_upload_image_returns_the_stored_name() -> None:
    seen: list[httpx.Request] = []
    table = {("POST", "/upload/image"): lambda r: httpx.Response(200, json={"name": "face (1).png"})}
    with _client(_routes(table, seen)) as client:
        assert client.upload_image(PNG, "face.png") == "face (1).png"
    assert b'name="image"; filename="face.png"' in seen[-1].content


def test_an_oversized_api_reply_is_refused() -> None:
    """M3: a status, history or submit body past ``max_json_bytes`` is never held whole."""
    big = {"p-1": {"status": {"completed": True}, "outputs": {"7": {"images": []}}, "pad": "x" * 4096}}
    table = {("GET", "/history/p-1"): lambda r: httpx.Response(200, json=big)}
    with _client(_routes(table), max_json_bytes=1024) as client:
        with pytest.raises(ComfyError) as caught:
            client.history("p-1")
    assert caught.value.kind == "oversized"
    with _client(_routes(table), max_json_bytes=8192) as client:
        assert client.history("p-1")["status"]["completed"] is True


def test_a_prompt_id_is_quoted_into_the_path() -> None:
    """M6: a prompt id from the server cannot steer the request to another route."""
    seen: list[httpx.Request] = []
    with _client(_routes({}, seen)) as client:
        with pytest.raises(ComfyError):
            client.history("../system_stats?x=1")
    assert seen[-1].url.raw_path == b"/history/..%2Fsystem_stats%3Fx%3D1"


def test_an_unknown_error_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        ComfyError("oops", "")


# -- the art provider on the client ------------------------------------------


def _happy_server(seen: list[httpx.Request]) -> Handler:
    polls = iter([{}, {"p-1": {"status": {"completed": True}, "outputs": {"7": {"images": [{"filename": "o.png"}]}}}}])
    return _routes(
        {
            ("GET", "/system_stats"): lambda r: httpx.Response(200, json={}),
            ("POST", "/prompt"): lambda r: httpx.Response(200, json={"prompt_id": "p-1"}),
            ("GET", "/history/p-1"): lambda r: httpx.Response(200, json=next(polls)),
            ("GET", "/view"): lambda r: httpx.Response(200, content=PNG),
        },
        seen,
    )


def test_the_art_provider_generates_through_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.media.providers.comfy import ComfyProvider

    _with_config(monkeypatch, {"comfyui.enabled": True, "comfyui.poll_seconds": 0})
    seen: list[httpx.Request] = []
    provider = ComfyProvider(transport=httpx.MockTransport(_happy_server(seen)))
    assert provider.available() is True
    request = _image_request("bent_nail", kind="item")
    result = provider.generate(request)
    assert result.status == "ready", result.detail
    assert Path(result.path).read_bytes() == PNG
    submitted = next(r for r in seen if r.url.path == "/prompt")
    assert json.loads(submitted.content)["prompt"] == provider.graph_for(request)
    assert json.loads(submitted.content)["client_id"] == request.cache_key()


def test_the_art_provider_turns_every_failure_into_a_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.media.providers.comfy import ComfyProvider

    _with_config(monkeypatch, {"comfyui.enabled": True})
    provider = ComfyProvider(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert provider.available() is False
    result = provider.generate(_image_request("bent_nail", kind="item"))
    assert result.status == "failed" and result.detail.startswith("auth")

    _with_config(monkeypatch, {"comfyui.enabled": False})
    assert ComfyProvider(transport=httpx.MockTransport(_happy_server([]))).available() is False


# -- I2: the phone's switch is its own -----------------------------------------


def test_phone_media_never_reads_comfyui_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.media.comfy.workflows import phone_media_provider

    _with_config(monkeypatch, {"comfyui.enabled": False, "phone_media.provider": "comfyui"})
    assert phone_media_provider() == "comfyui"
    _with_config(monkeypatch, {"comfyui.enabled": True, "phone_media.provider": "procedural"})
    assert phone_media_provider() == "procedural"
    _with_config(monkeypatch, {"phone_media.provider": "stub"})
    assert phone_media_provider() == "stub"

    files = sorted((ROOT / "engine" / "media" / "comfy").glob("*.py"))
    social_media = ROOT / "engine" / "social" / "media.py"
    if social_media.exists():
        files.append(social_media)
    assert files, "the scan found nothing to read"
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "comfyui.enabled" not in source, f"{path.relative_to(ROOT)} names the art pipeline's switch"
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "enabled" not in node.value or "comfyui" not in node.value, (
                    f"{path.relative_to(ROOT)}:{node.lineno} builds the art pipeline's switch key"
                )


def test_an_unknown_phone_media_provider_is_off_and_warned_once_per_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from engine.media.comfy import workflows

    monkeypatch.setattr(workflows, "_WARNED_PROVIDERS", set())
    caplog.set_level("WARNING", logger="engine.media.comfy.workflows")
    _with_config(monkeypatch, {"phone_media.provider": "dall-e"})
    assert [workflows.phone_media_provider() for _ in range(5)] == ["procedural"] * 5, "an unknown name is off"
    _with_config(monkeypatch, {"phone_media.provider": "midjourney"})
    assert workflows.phone_media_provider() == "procedural"
    warned = [r.getMessage() for r in caplog.records if "Unknown phone media provider" in r.getMessage()]
    assert len(warned) == 2 and "dall-e" in warned[0] and "midjourney" in warned[1], warned


def test_the_default_phone_media_provider_is_off() -> None:
    from engine.media.comfy.workflows import phone_media_provider

    assert get_config().get("phone_media.provider") == "procedural"
    assert phone_media_provider() == "procedural"
    assert get_config().get("comfyui.enabled") is False
