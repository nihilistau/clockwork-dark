"""
A FAKE gunicorn, for the supervisor's tests (v0.20.0 T13). Never installed:
a test puts ``tests/probes/fake_gunicorn`` first on a child's ``PYTHONPATH``
(or on ``sys.path`` in-process), so ``import gunicorn`` and
``gunicorn.arbiter`` succeed where the real one cannot run (Windows), and the
supervisor takes its gunicorn branch (``process.gunicorn_runs_here``).

``python -m gunicorn -c <conf> <module>:<attr>`` (``__main__.py``) behaves
like gunicorn's master in the ways the supervisor relies on:

- it executes the conf file and calls its ``on_starting(server)`` with
  ``server.cfg`` resolved as gunicorn resolves it -- its defaults
  (``WEB_CONCURRENCY`` only ``workers``' default), then the conf, then
  ``GUNICORN_CMD_ARGS`` over it;
  a ``RuntimeError`` there prints ``Error: ...`` and exits 1, as gunicorn's
  does;
- it starts ONE worker process with its own environment -- the bus token
  included, as a forked gunicorn worker inherits it -- which imports the app,
  binds the conf's ``bind`` with Werkzeug and calls the conf's
  ``post_worker_init(worker)`` (``worker.sockets``, ``worker.wsgi``,
  ``worker.ppid``) before serving;
- a worker that exits 3 (gunicorn's ``WORKER_BOOT_ERROR``, which the
  engine's lifeline exit code also is) ends the master with 3; any other exit
  starts a new worker, with the same environment;
- on command (a ``<process>.gunicorn_restart`` file in
  ``CLOCKWORK_FAKE_WORKER_DIR``) it plays gunicorn replacing its worker: it
  starts a second worker -- whose ``hello`` presents the token already used --
  waits for it to end, writes its exit code to ``<process>.second_hello``,
  kills the first, and then waits, still running, for whatever comes (the
  supervisor terminating it).

It writes ``gunicorn-master-<pid>.json`` to the control directory, so the
instance's orphan check covers it.
"""

__version__ = "0.0-fake"
