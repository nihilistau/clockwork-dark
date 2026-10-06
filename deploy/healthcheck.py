"""
The Docker image's ``HEALTHCHECK`` (v0.20.0 T18, spec §8.1).

``GET /api/health`` on the front door, AT THE ADDRESS IT BINDS
(``scene.clockwork.host``/``port``): healthy while the front door answers
200, which it does while its bus link to the supervisor is up
(``engine/hosting/frontdoor``). Exit 0 healthy, 1 not.

The published port reaches the front door only through the container's own
network interface, so (fix round 1, I1) in the image
(``CLOCKWORK_ENV=docker``) a front door bound to the container's LOOPBACK is
unhealthy whatever it answers there: nothing published can reach it, and a
check that asked ``127.0.0.1`` would report a dead deployment healthy. A
front door on every interface (``0.0.0.0``, ``::``, the image's) is asked on
loopback, which every-interface covers; one on a named address is asked at
that address.

Standard library and the engine's config only; nothing is written, and no
other host is asked.

    python /app/deploy/healthcheck.py
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: Seconds the whole check may take (the HEALTHCHECK's own timeout is longer).
TIMEOUT_SECONDS = 4.0

#: Bind addresses meaning every interface.
WILDCARDS = frozenset({"", "0.0.0.0", "::", "[::]"})

#: What a loopback front door in the image is told.
LOOPBACK_IN_IMAGE = (
    "the front door binds the container's loopback (scene.clockwork.host {host}): "
    "the published port reaches nothing. Leave scene.clockwork.host unset in the image; "
    "publish 127.0.0.1:5573:5573 instead (docs/HOSTING.md § Docker)"
)


def health_url() -> tuple[Optional[str], str]:
    """
    ``(url, "")`` to ask, or ``(None, why)`` when the front door cannot be
    reached through the published port at all.
    """
    from engine.scenes.spec import is_loopback, scene_host, scene_port

    host = str(scene_host() or "").strip()
    port = scene_port()
    if os.environ.get("CLOCKWORK_ENV", "").strip() == "docker" and host not in WILDCARDS and is_loopback(host):
        return None, LOOPBACK_IN_IMAGE.format(host=host)
    if host in WILDCARDS:
        target = "[::1]" if host in ("::", "[::]") else "127.0.0.1"
    else:
        bare = host.strip("[]")
        target = f"[{bare}]" if ":" in bare else bare
    return f"http://{target}:{port}/api/health", ""


def main() -> int:
    url, why = health_url()
    if url is None:
        print(f"unhealthy: {why}", file=sys.stderr)
        return 1
    try:
        # An opener with no proxy handler: http_proxy / HTTP_PROXY must never
        # carry a loopback health request to a proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=TIMEOUT_SECONDS) as answer:  # noqa: S310 - the bind's own address
            status = int(answer.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except (OSError, ValueError) as exc:
        print(f"unhealthy: {url}: {type(exc).__name__}", file=sys.stderr)
        return 1
    if status != 200:
        print(f"unhealthy: {url}: HTTP {status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
