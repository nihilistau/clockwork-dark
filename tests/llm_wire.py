"""
The one wire seam every mocked model-server test goes through.

WHY ONE SEAM, AND WHY THIS ONE. The engine reaches the model server three
ways: through ``httpx.Client`` INSTANCES (``LMSClient``, ``NativeClient``),
through the module-level ``httpx.get`` / ``httpx.post`` (discovery, the stack
probe, the doctor's diagnostic post), and through ``Client.stream`` (both
streaming transports). Patching any one of those left the others reaching the
real server -- ``tests/test_lmstudio_health.py`` opened by saying "Everything
here is mocked" while seven of its tests talked to LM Studio. All three ways end
in ``httpx.HTTPTransport.handle_request``, so that is the one place patched
here, and no client grows a transport argument for testing.

WHAT IT DOES. :func:`wire` patches ``handle_request`` for the length of a
``with`` block and

  * captures every request as ``{method, url, headers, body}`` -- the body as
    canonical JSON text (``sort_keys``, no whitespace) when it parses, else as
    text -- and
  * answers each one, in order, from a list of canned answers, raising when a
    request arrives with none left.

That raise can be swallowed: the engine forgives a failed model call on
purpose (the planner treats a raise as a silent agent, discovery logs and
returns ``[]``). So a request that found no answer is also recorded on
:attr:`Wire.unanswered`, and the ``with`` block asserts on it at exit, where
nothing is left to catch it -- the reason ``tests/conftest.py``'s socket guard
asserts at teardown.

A CANNED ANSWER is a plain dict, so a list of them is a JSON fixture:

  ``{"status": 200, "json": {...}}``
      a JSON body (``content-type: application/json``);
  ``{"status": 200, "sse": [{"event": "chat.start", "data": {...}}, ...]}``
      a server-sent-event stream. A frame with an ``event`` renders as an
      ``event:`` line and a ``data:`` line (LM Studio's native stream); a frame
      without one renders as the ``data:`` line alone (the OpenAI-compatible
      stream). ``data`` may be the string ``"[DONE]"``;
  ``{"status": 400, "text": "..."}``
      a plain-text body;
  ``{"raise": "ConnectError", "message": "..."}``
      no response at all: the named ``httpx`` exception is raised, as a closed
      port raises it.

``headers`` on any of the first three is merged over the default
``content-type``.

THE RENDERING IS PART OF THE LM STUDIO GOLDEN'S CONTRACT. The golden replays
its recorded answers through :func:`build_response` and :func:`render_sse`, so
changing the bytes either produces changes what the golden serves without
touching a fixture -- it re-baselines the golden, and is not allowed.
``tests/test_llm_golden_lmstudio.py::test_the_seam_renders_the_recorded_answers_unchanged``
pins those bytes. A backend with a different framing gets its own renderer.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, Iterator, Optional

import httpx
import pytest


def canonical_json(value: Any) -> str:
    """``value`` as canonical JSON text: sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_body(raw: bytes) -> str:
    """
    A request body as canonical JSON text when it parses, else as text.

    Canonical rather than as sent, so a later change that only reorders keys
    in a payload dict is not a wire difference; a changed key, value or type is.
    """
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    try:
        return canonical_json(json.loads(text))
    except ValueError:
        return text


def capture(request: httpx.Request) -> dict[str, Any]:
    """
    One request as ``{method, url, headers, body}``.

    Headers are recorded whole -- ``Authorization`` included -- as a mapping
    keyed by lower-cased name and sorted, so the capture compares by content
    rather than by the order a client happened to assemble them in.
    """
    body = request.read()
    headers: dict[str, str] = {}
    for name, value in request.headers.multi_items():
        key = name.lower()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value
    return {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(sorted(headers.items())),
        "body": canonical_body(body),
    }


def render_sse(frames: list[dict[str, Any]]) -> str:
    """Render canned SSE frames as the server would write them."""
    out: list[str] = []
    for frame in frames:
        data = frame.get("data")
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        if frame.get("event"):
            out.append(f"event: {frame['event']}")
        out.append(f"data: {payload}")
        out.append("")
    return "\n".join(out) + "\n"


def build_response(answer: dict[str, Any], request: httpx.Request) -> httpx.Response:
    """Turn one canned answer into an ``httpx.Response`` (or raise its error)."""
    if "raise" in answer:
        error = getattr(httpx, str(answer["raise"]))
        raise error(str(answer.get("message") or answer["raise"]), request=request)

    status = int(answer.get("status", 200))
    if "json" in answer:
        content = json.dumps(answer["json"], ensure_ascii=False).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    elif "sse" in answer:
        content = render_sse(list(answer["sse"])).encode("utf-8")
        content_type = "text/event-stream"
    else:
        content = str(answer.get("text", "")).encode("utf-8")
        content_type = "text/plain; charset=utf-8"
    headers = {"content-type": content_type}
    headers.update({str(k).lower(): str(v) for k, v in (answer.get("headers") or {}).items()})
    return httpx.Response(status, headers=headers, content=content, request=request)


class Wire:
    """The requests one ``with wire(...)`` block saw, and what it had left."""

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.unanswered: list[str] = []
        self._pending: list[dict[str, Any]] = list(answers)

    @property
    def remaining(self) -> int:
        """Canned answers no request has used yet."""
        return len(self._pending)

    def handle(self, request: httpx.Request) -> httpx.Response:
        captured = capture(request)
        self.requests.append(captured)
        if not self._pending:
            line = f"{captured['method']} {captured['url']}"
            self.unanswered.append(line)
            raise AssertionError(
                f"the wire seam got a request it has no canned answer for: {line}"
            )
        return build_response(self._pending.pop(0), request)


@contextlib.contextmanager
def wire(
    answers: Optional[list[dict[str, Any]]] = None,
    *,
    exhaust: bool = False,
) -> Iterator[Wire]:
    """
    Patch ``httpx.HTTPTransport.handle_request`` for the block, and answer from
    ``answers`` in order.

    Args:
        answers: Canned answers, in the order the requests will arrive.
        exhaust: Also fail at exit if an answer was left unused.

    Raises:
        AssertionError: At exit, if a request found no answer left (or, with
            ``exhaust``, if an answer found no request).
    """
    seam = Wire(list(answers or []))
    patch = pytest.MonkeyPatch()
    patch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: seam.handle(request),
    )
    try:
        yield seam
    finally:
        patch.undo()
    assert not seam.unanswered, (
        f"requests reached the wire seam with no canned answer left: {seam.unanswered}"
    )
    if exhaust:
        assert not seam.remaining, f"{seam.remaining} canned answer(s) were never asked for"


__all__ = [
    "Wire",
    "build_response",
    "canonical_body",
    "canonical_json",
    "capture",
    "render_sse",
    "wire",
]
