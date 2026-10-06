"""
gunicorn's configuration for hosted mode (spec §7.1, v0.20.0 T13).

One file for every process the supervisor runs under gunicorn: the front
door and each story's worker. The supervisor starts each as

    python -m gunicorn -c deploy/gunicorn.conf.py <role's wsgi module>:app

(``engine/hosting/supervisor/process.py``) and sets ``CLOCKWORK_BUS_ROLE``,
which picks the bind below. Run it by hand only to read what it does: a
process without the supervisor's bus refuses to boot.

- ONE gthread worker. Flask-SocketIO's threading mode runs under gunicorn
  with one threaded worker, WebSocket through simple-websocket; a second
  worker would split the in-memory sessions, buckets and lanes (spec §5.1);
- ``threads`` is ``hosting.threads``: the front door's long holds (every
  relayed WebSocket, polling GET and HTTP turn) are ``threads - 4``, the
  rest kept for login and the static files (``engine/hosting/limits.py``);
- ``bind``: the front door, ``scene.clockwork.host``/``port`` (an explicit
  port 0 means one the OS picks, as the test suite binds it); a worker,
  ``127.0.0.1:0``, the port the OS picks, reported to the supervisor by
  ``post_worker_init`` (``engine.hosting.boot.report_ready``);
- NO FORWARDED HEADER IS TRUSTED BY GUNICORN (fix round 1, I2):
  ``forwarded_allow_ips`` is empty and ``secure_scheme_headers`` too, so
  gunicorn never sets the scheme (or ``SCRIPT_NAME``) from a header -- its
  default trusts any loopback peer. The one trust decision is the engine's
  (spec §7.3): ``hosting.trusted_proxies``' ``ProxyFix`` at the front door,
  the proxy token at a worker;
- ``timeout`` 120: gunicorn's worker heartbeat, not a request limit (turns
  stream over the socket). The bus lives in gunicorn's WORKER, so a worker
  gunicorn restarts itself closes the bus link: the supervisor takes that as
  the child down, stops this master and starts it again with a fresh token,
  and a respawned worker's ``hello`` is refused (single-use tokens);
- ``graceful_timeout`` 30; no access log (the engine logs every operation);
  ``max_requests`` 0 (a worker gunicorn recycles would cost its bus link).

WHAT OVERRIDES THIS FILE (fix round 1, I3, M4). gunicorn applies, in order,
its defaults (``WEB_CONCURRENCY`` is only the default for ``workers``, which
this file sets), this file, then ``GUNICORN_CMD_ARGS``, then the command
line. The supervisor strips ``GUNICORN_CMD_ARGS`` (and ``WEB_CONCURRENCY``)
from every child's environment and passes nothing on the command line but
this file and the app, and ``on_starting`` refuses to start when anything
has changed what is set here anyway: the worker count, the worker class,
``max_requests``, the forwarded-header trust, and the bind -- a worker on
anything but loopback, or the front door off its configured address.

This file imports nothing from gunicorn, and from the engine only its config
(``engine.config``), at import; ``post_worker_init`` imports the boot module
when it runs, in the worker.
"""

import ipaddress
import os

from engine.config import get_config

#: Spec §5.1: one worker process per server.
WORKERS = 1

#: The worker class (gunicorn's threaded worker).
WORKER_CLASS = "gthread"

#: Where a story's worker listens (``engine.hosting.boot.WORKER_HOST``).
WORKER_BIND = "127.0.0.1:0"


def _role() -> str:
    return str(os.environ.get("CLOCKWORK_BUS_ROLE", "") or "worker").strip()


def _frontdoor_bind() -> str:
    cfg = get_config()
    host = str(cfg.get("scene.clockwork.host"))
    port = int(cfg.get("scene.clockwork.port"))
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def _loopback(address: str) -> bool:
    """Whether a gunicorn bind (``host:port``, ``[v6]:port``) is on loopback."""
    host = str(address).rsplit(":", 1)[0].strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


workers = WORKERS
worker_class = WORKER_CLASS
threads = int(get_config().get("hosting.threads"))
bind = [_frontdoor_bind() if _role() == "frontdoor" else WORKER_BIND]
forwarded_allow_ips = ""
secure_scheme_headers = {}
max_requests = 0
timeout = 120
graceful_timeout = 30
accesslog = None
errorlog = "-"
preload_app = False


def overrides(cfg, role: str) -> list:  # noqa: ANN001 -- gunicorn's Config
    """What in gunicorn's resolved ``cfg`` differs from this file (see the docstring)."""
    found = []
    if int(cfg.workers) != WORKERS:
        found.append(f"{int(cfg.workers)} workers (exactly one per process, spec §5.1)")
    if str(getattr(cfg, "worker_class_str", WORKER_CLASS)) != WORKER_CLASS:
        found.append(f"worker class {cfg.worker_class_str} (gthread)")
    if int(getattr(cfg, "max_requests", 0) or 0) != 0:
        found.append(f"max_requests {cfg.max_requests} (0: a recycled worker loses its bus link)")
    if list(getattr(cfg, "forwarded_allow_ips", []) or []):
        found.append("forwarded_allow_ips (the engine alone decides which forwarded headers to trust)")
    if dict(getattr(cfg, "secure_scheme_headers", {}) or {}):
        found.append("secure_scheme_headers (the engine alone decides which forwarded headers to trust)")
    binds = [str(b) for b in (getattr(cfg, "bind", []) or [])]
    if role == "frontdoor":
        if binds != [_frontdoor_bind()]:
            found.append(f"bind {binds} (the front door's is scene.clockwork.host/port)")
    elif not binds or not all(_loopback(b) for b in binds):
        found.append(f"bind {binds} (a story's worker listens on loopback only)")
    return found


def on_starting(server):  # noqa: ANN001 -- gunicorn's hook signature
    """Refuse to start when anything overrode this file (see the module docstring)."""
    changed = overrides(server.cfg, _role())
    if changed:
        raise RuntimeError(
            "hosted mode runs gunicorn exactly as deploy/gunicorn.conf.py sets it, and something "
            "(GUNICORN_CMD_ARGS or the command line) changed: " + "; ".join(changed)
        )


def post_worker_init(worker):  # noqa: ANN001 -- gunicorn's hook signature
    """Tell the supervisor the port gunicorn bound, from inside the worker that holds the bus."""
    from engine.hosting.boot import report_ready

    port = int(worker.sockets[0].getsockname()[1])
    report_ready(worker.wsgi, port, master_pid=int(worker.ppid))
