"""
Engine Net: one HTTP client per process for the engine's one-shot requests
=========================================================================

WHY (v0.21.1 T3b). ``httpx.get`` and ``httpx.post`` build a whole new
``httpx.Client`` for every request, and every client builds a new SSL context
and reloads the certifi CA bundle -- even for a plain ``http://`` URL, where it
is never used. On the owner's Windows PC that costs about 0.21 s a request.
Model discovery makes up to five requests a refresh, so live play paid about a
second per discovery refresh and ``tests/test_llm_ollama.py`` spent most of
each test on it.

WHAT. :func:`get` and :func:`post` take ``httpx.get``'s and ``httpx.post``'s
REQUEST arguments (not their client ones -- ``verify``, ``cert``, ``proxy``,
``trust_env`` -- which ``Client.get`` refuses) and answer the same way, through ONE lazily built,
process-wide ``httpx.Client`` (thread-safe for requests). Every engine site
that used the module-level functions uses these. :func:`ssl_context` is the
one SSL context that client verifies with, built once; the engine's own
long-lived clients (``LMSClient``, ``NativeClient``, ``OllamaClient``) and its
per-call media clients pass it as ``verify=`` so they stop building one each.

THE SAME REQUEST AS BEFORE. Each request carries its own timeout, headers and
body exactly as it did; and the shared client is built as ``httpx.get``'s
throwaway one is (``verify=True`` -- the same context ``httpx`` builds for it,
built by ``httpx.create_ssl_context`` itself -- ``trust_env=True``, no
redirects followed, httpx's default headers and timeout), with two
differences that keep a SHARED client behaving like a throwaway one:

* **No cookie is kept.** A throwaway client's jar dies with it; a shared jar
  would carry one server's ``Set-Cookie`` into the next request. The jar here
  refuses every cookie (:class:`_NoCookies`).
* **No connection is kept alive** (``max_keepalive_connections=0``): each
  request opens its own connection and closes it when the response is read,
  as before. Opening a connection is not what cost the time, and a pooled
  connection would let a later request skip ``connect`` -- the test suite's
  socket guard (``tests/conftest.py::_no_live_model_calls``) sees every
  request because every request still connects, and a forked child can
  inherit no open connection.

What changed is WHEN the environment is read: ``trust_env``'s proxy variables
(``HTTP_PROXY``, ``NO_PROXY``, ...; on Windows the system proxy settings in the
registry too, through ``urllib.request.getproxies``) and
``SSL_CERT_FILE``/``SSL_CERT_DIR`` are read once, at first use (the first
request, not import), not per request: a system-proxy change made while the
game runs is seen at its next start. :func:`close` drops the client, so the
next request re-reads the proxies, but KEEPS the SSL context: a process that
changes ``SSL_CERT_FILE``/``SSL_CERT_DIR`` after its first request also has
to drop ``_ssl_context``. Nothing in the repository does either.

PER PROCESS. A forked child drops both (``os.register_at_fork``) and builds
its own on first use; the lock is renewed (``engine/locks.py``). The client is
closed at exit.

Version: v0.1.1 [2026-10-07]
"""

from __future__ import annotations

import atexit
import http.cookiejar
import os
import ssl
import threading
from typing import Any, Optional

import httpx

from engine.locks import renew_after_fork

_client: Optional[httpx.Client] = None
_ssl_context: Optional[ssl.SSLContext] = None
#: Guards building ``_client`` and ``_ssl_context`` (engine/locks.py: #26).
#: Its holder builds them and takes no other lock.
_lock = threading.Lock()
renew_after_fork(globals(), _lock=threading.Lock)


class _NoCookies(http.cookiejar.DefaultCookiePolicy):
    """A cookie policy that neither stores nor sends any cookie."""

    def set_ok(self, cookie: Any, request: Any) -> bool:  # noqa: D102
        return False

    def return_ok(self, cookie: Any, request: Any) -> bool:  # noqa: D102
        return False

    def domain_return_ok(self, domain: str, request: Any) -> bool:  # noqa: D102
        return False

    def path_return_ok(self, path: str, request: Any) -> bool:  # noqa: D102
        return False


def ssl_context() -> ssl.SSLContext:
    """
    The process's one SSL context: what ``httpx`` builds for ``verify=True``
    (certifi's bundle, or ``SSL_CERT_FILE``/``SSL_CERT_DIR``), built once.
    Double-checked: no lock once built.

    It is SHARED and mutable: httpcore sets its ALPN protocols on every https
    connect (the same ``["http/1.1"]`` for every client here). Never give it to
    an ``http2=True`` client or load a client certificate into it; build a
    private context for those.
    """
    global _ssl_context
    context = _ssl_context
    if context is not None:
        return context
    with _lock:
        if _ssl_context is None:
            _ssl_context = httpx.create_ssl_context(verify=True, trust_env=True)
        return _ssl_context


def client() -> httpx.Client:
    """The process's one shared client (double-checked: no lock once built)."""
    global _client
    built = _client
    if built is not None:
        return built
    context = ssl_context()
    with _lock:
        if _client is None:
            _client = httpx.Client(
                verify=context,
                trust_env=True,
                follow_redirects=False,
                cookies=http.cookiejar.CookieJar(policy=_NoCookies()),
                limits=httpx.Limits(max_keepalive_connections=0),
            )
        return _client


def get(url: Any, **kwargs: Any) -> httpx.Response:
    """``httpx.get(url, **kwargs)`` (its request arguments), through the shared client."""
    return client().get(url, **kwargs)


def post(url: Any, **kwargs: Any) -> httpx.Response:
    """``httpx.post(url, **kwargs)`` (its request arguments), through the shared client."""
    return client().post(url, **kwargs)


def close() -> None:
    """
    Close and drop the shared client (at exit; tests). The next use builds one.

    The SSL context is kept (see the module docstring). At interpreter exit a
    daemon thread still mid-request may then get httpx's ``RuntimeError`` (the
    client has been closed), which the call sites' ``except httpx.HTTPError``
    does not catch: a shutdown-time traceback at most, accepted.
    """
    global _client
    with _lock:
        old, _client = _client, None
    if old is not None:
        old.close()


def _forget_in_child() -> None:
    """A forked child builds its own client and context: never its parent's."""
    global _client, _ssl_context
    _client = None
    _ssl_context = None


if hasattr(os, "register_at_fork"):  # POSIX only
    os.register_at_fork(after_in_child=_forget_in_child)
atexit.register(close)


__all__ = ["client", "close", "get", "post", "ssl_context"]
