"""The fake gunicorn's master and worker (see ``__init__``'s docstring)."""

from __future__ import annotations

import importlib
import json
import os
import runpy
import shlex
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

#: gunicorn's ``Arbiter.WORKER_BOOT_ERROR``.
WORKER_BOOT_ERROR = 3

#: The master's own pid, handed to its worker (``worker.ppid``): under a
#: Windows venv the worker's parent is the venv launcher, not the master.
MASTER_PID_ENV = "FAKE_GUNICORN_MASTER_PID"


def _process_name() -> str:
    role = os.environ.get("CLOCKWORK_BUS_ROLE", "worker")
    return "frontdoor" if role == "frontdoor" else f"worker-{os.environ.get('CLOCKWORK_GAME', '')}"


def _control() -> Optional[Path]:
    value = os.environ.get("CLOCKWORK_FAKE_WORKER_DIR", "")
    return Path(value) if value else None


def _spawn(conf: str, app: str) -> subprocess.Popen:
    env = dict(os.environ)
    env[MASTER_PID_ENV] = str(os.getpid())
    return subprocess.Popen(  # noqa: S603 -- sys.executable and -m, no shell
        [sys.executable, "-u", "-m", "gunicorn", "--fake-worker", conf, app],
        env=env,
        stdin=subprocess.DEVNULL,
    )


#: ``GUNICORN_CMD_ARGS`` options the fake understands: flag -> (setting, type).
_CMD_ARGS = {
    "-w": ("workers", int),
    "--workers": ("workers", int),
    "-b": ("bind", "list"),
    "--bind": ("bind", "list"),
    "-k": ("worker_class_str", str),
    "--worker-class": ("worker_class_str", str),
    "--max-requests": ("max_requests", int),
    "--forwarded-allow-ips": ("forwarded_allow_ips", "csv"),
}


def resolved(conf: dict[str, Any]) -> SimpleNamespace:
    """
    gunicorn's precedence, for the settings the conf's ``on_starting`` reads:
    the defaults (``WEB_CONCURRENCY`` is only ``workers``' default), then the
    config file, then ``GUNICORN_CMD_ARGS`` (which overrides the file).
    """
    cfg = {
        "workers": int(os.environ.get("WEB_CONCURRENCY") or 1),
        "worker_class_str": "sync",
        "max_requests": 0,
        "forwarded_allow_ips": ["127.0.0.1", "::1"],
        "secure_scheme_headers": {"X-FORWARDED-PROTO": "https"},
        "bind": ["127.0.0.1:8000"],
    }
    for key, setting in (("workers", "workers"), ("worker_class", "worker_class_str"), ("max_requests", "max_requests"),
                         ("bind", "bind"), ("secure_scheme_headers", "secure_scheme_headers")):
        if key in conf:
            cfg[setting] = conf[key]
    if "forwarded_allow_ips" in conf:
        cfg["forwarded_allow_ips"] = [p for p in str(conf["forwarded_allow_ips"]).split(",") if p.strip()]
    args = shlex.split(os.environ.get("GUNICORN_CMD_ARGS", ""))
    while args:
        flag = args.pop(0)
        if flag not in _CMD_ARGS or not args:
            continue
        setting, kind = _CMD_ARGS[flag]
        value = args.pop(0)
        if kind == "list":
            cfg[setting] = [value]
        elif kind == "csv":
            cfg[setting] = [p for p in value.split(",") if p.strip()]
        else:
            cfg[setting] = kind(value)
    return SimpleNamespace(**cfg)


def master(conf_path: str, app: str) -> int:
    conf = runpy.run_path(conf_path)
    cfg = resolved(conf)
    try:
        conf["on_starting"](SimpleNamespace(cfg=cfg))
    except RuntimeError as exc:
        print(f"\nError: {exc}\n", file=sys.stderr, flush=True)
        return 1
    control = _control()
    name = _process_name()
    if control is not None:
        from tests.process_identity import report as identity_report

        (control / f"gunicorn-master-{os.getpid()}.json").write_text(json.dumps(identity_report()), encoding="utf-8")
    print(f"[fake gunicorn] Starting master (pid {os.getpid()}) for {app}", flush=True)
    children: list[subprocess.Popen] = []
    stop = threading.Event()

    def end(_signum: int, _frame: Any) -> None:
        stop.set()

    if os.name == "posix":
        signal.signal(signal.SIGTERM, end)
        signal.signal(signal.SIGINT, end)
    worker = _spawn(conf_path, app)
    children.append(worker)
    replaced = False
    try:
        while not stop.wait(0.05):
            if not replaced and control is not None and (control / f"{name}.gunicorn_restart").exists():
                (control / f"{name}.gunicorn_restart").unlink()
                second = _spawn(conf_path, app)
                children.append(second)
                code = second.wait(60)
                (control / f"{name}.second_hello").write_text(str(code), encoding="ascii")
                worker.kill()
                worker.wait(10)
                replaced = True  # gunicorn's worker is gone; the master runs on
                continue
            if replaced:
                continue
            code = worker.poll()
            if code is None:
                continue
            if code == WORKER_BOOT_ERROR:
                print("[fake gunicorn] Worker failed to boot.", flush=True)
                return WORKER_BOOT_ERROR
            print(f"[fake gunicorn] Worker exited ({code}); booting a new one", flush=True)
            worker = _spawn(conf_path, app)
            children.append(worker)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                try:
                    child.wait(10)
                except subprocess.TimeoutExpired:
                    pass
    return 0


def worker_main(conf_path: str, app: str) -> int:
    from werkzeug.serving import make_server

    conf = runpy.run_path(conf_path)
    module_name, _, attr = app.partition(":")
    try:
        loaded = getattr(importlib.import_module(module_name), attr)
    except BaseException:  # noqa: BLE001 -- gunicorn's "Exception in worker process"
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(WORKER_BOOT_ERROR)
    host, _, port = str(resolved(conf).bind[0]).rpartition(":")
    server = make_server(host.strip("[]"), int(port), loaded, threaded=True)
    worker = SimpleNamespace(
        sockets=[server.socket],
        wsgi=loaded,
        ppid=int(os.environ.get(MASTER_PID_ENV) or os.getppid()),
    )
    conf["post_worker_init"](worker)
    server.serve_forever()
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--fake-worker"]:
        return worker_main(argv[1], argv[2])
    conf, app = "", ""
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item == "-c":
            conf = rest.pop(0)
        else:
            app = item
    if not conf or not app:
        print("usage: python -m gunicorn -c <conf> <module>:<attr>", file=sys.stderr)
        return 2
    return master(conf, app)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
