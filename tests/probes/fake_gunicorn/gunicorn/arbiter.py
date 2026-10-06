"""The fake gunicorn's server module: importable, so ``gunicorn_runs_here`` answers yes (see ``__init__``)."""


class Arbiter:
    """Nothing: the fake's master is ``gunicorn/__main__.py``."""
