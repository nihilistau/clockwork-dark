"""
The CI workflow's shape (v0.20.0 T5; spec §3.8).

``.github/workflows/ci.yml`` runs only once it is pushed, and nothing is
pushed without the owner's word, so this file is what holds it to the spec in
the meantime: parsed as YAML, never run here. Two jobs on ``ubuntu-latest``
-- ``suite`` (Python 3.11, installed under ``constraints.txt``, full history
for the dist-freshness test, 150 minutes) and ``client`` (Node 24: install,
test, build, and a diff against the committed build) -- on pushes to
``main`` and ``release/**`` and on pull requests. No secret, no model server,
and no image pushed anywhere: the ``image`` job (v0.20.0 T18) builds the
Dockerfile, starts it with a throwaway cookie key made on the runner, asks
``GET /api/health`` and stops it.

The client's diff needs the committed ``dist/index.html`` to be what a Linux
build writes: it held a Windows checkout's CRLF (and one ``\\r\\r\\n``), read
by Vite from a CRLF ``ui/index.html``. Both are LF now, by ``.gitattributes``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
DIST_INDEX = REPO / "content" / "scenes" / "clockwork" / "static" / "dist" / "index.html"


def _workflow() -> dict[str, Any]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _triggers(doc: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 (PyYAML) reads a bare `on` key as the boolean True.
    triggers = doc.get("on", doc.get(True))
    assert isinstance(triggers, dict), triggers
    return triggers


def _steps(doc: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return list(doc["jobs"][job]["steps"])


def _runs(doc: dict[str, Any], job: str) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(doc, job))


def _uses(doc: dict[str, Any], job: str, action: str) -> dict[str, Any]:
    found = [s for s in _steps(doc, job) if str(s.get("uses", "")).startswith(action + "@")]
    assert len(found) == 1, (job, action, found)
    return dict(found[0].get("with") or {})


def _walk(node: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[tuple[Any, ...], Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield path + (key,), value
            yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (index,))


def test_the_jobs() -> None:
    doc = _workflow()
    assert set(doc["jobs"]) == {"suite", "client", "image"}
    for job in doc["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"


def test_the_triggers() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"push", "pull_request"}
    assert triggers["push"]["branches"] == ["main", "release/**"]


def test_a_newer_push_cancels_the_run_in_progress() -> None:
    concurrency = _workflow()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "github.ref" in concurrency["group"]


def test_the_actions_are_on_their_node24_majors() -> None:
    """checkout, setup-python and setup-node v7 (chosen 2026-10-01): the node20
    action runtime they replace is being retired by GitHub."""
    doc = _workflow()
    for job in doc["jobs"]:
        for step in _steps(doc, job):
            uses = str(step.get("uses", ""))
            if uses.startswith("actions/"):
                assert uses.endswith("@v7"), uses


def test_the_suite_job() -> None:
    doc = _workflow()
    suite = doc["jobs"]["suite"]
    assert suite["timeout-minutes"] == 150
    assert _uses(doc, "suite", "actions/checkout")["fetch-depth"] == 0
    assert str(_uses(doc, "suite", "actions/setup-python")["python-version"]) == "3.11"
    runs = _runs(doc, "suite")
    assert "pip install -r requirements.txt -c constraints.txt" in runs
    assert "--upgrade pip" not in runs  # the installer is the runner's, not upgraded
    # Every tier, said outright (`full`), as the hybrid run on 2 workers (the
    # runner's vCPUs), not left to a bare pytest's fast tier.
    assert "python scripts/run_tests.py full --workers 2" in runs
    reqs = (REPO / "requirements.txt").read_text(encoding="utf-8")
    assert "pytest-xdist" in reqs and "pytest-timeout" in reqs  # installed above


def test_the_suite_job_installs_the_server_requirements_so_gunicorn_serves_its_hosted_tests() -> None:
    """v0.20.0 T13: every pushed run exercises the front door's sockets under gunicorn."""
    doc = _workflow()
    runs = _runs(doc, "suite")
    assert "pip install -r requirements-server.txt -c constraints.txt" in runs
    assert runs.index("requirements-server.txt") < runs.index("run_tests.py")
    cached = str(_uses(doc, "suite", "actions/setup-python")["cache-dependency-path"])
    assert "requirements-server.txt" in cached
    server = (REPO / "requirements-server.txt").read_text(encoding="utf-8").splitlines()
    assert server[0] == "-c constraints.txt"
    names = {line.split(">=")[0].strip() for line in server if line and not line.startswith(("#", "-"))}
    assert "gunicorn" in names and not {"faster-whisper", "fastmcp", "pytest"} & names


def test_the_client_job() -> None:
    doc = _workflow()
    assert str(_uses(doc, "client", "actions/setup-node")["node-version"]) == "24"
    runs = _runs(doc, "client")
    order = ["npm ci --prefix ui", "npm test --prefix ui", "npm run build --prefix ui",
             "git diff --exit-code -- content/scenes/clockwork/static/dist"]
    positions = [runs.find(command) for command in order]
    assert all(p >= 0 for p in positions) and positions == sorted(positions), positions


def test_no_image_is_pushed_and_no_secret_or_model_server_is_used() -> None:
    doc = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")
    pushes = [
        path for path, value in _walk(doc["jobs"]) if path[-1] == "push" and value not in (None, False)
    ]
    assert pushes == []
    assert "docker push" not in text and "docker/build-push-action" not in text
    assert "secrets." not in text
    for needle in ("CLOCKWORK_LIVE_LLM", "lms ", "ollama", "vllm", "llama-server", "doctor.py"):
        assert needle not in _runs(doc, "suite") + _runs(doc, "client"), needle


def test_the_image_job_builds_runs_and_asks_for_health_without_pushing() -> None:
    """v0.20.0 T18 (spec §3.8): build, run with a throwaway key, GET /api/health."""
    doc = _workflow()
    job = doc["jobs"]["image"]
    assert job["runs-on"] == "ubuntu-latest" and int(job["timeout-minutes"]) <= 60
    runs = _runs(doc, "image")
    order = ["docker build", "docker run", "/api/health", "docker stop"]
    positions = [runs.find(command) for command in order]
    assert all(p >= 0 for p in positions) and positions == sorted(positions), positions
    build = next(line for line in runs.splitlines() if "docker build" in line)
    assert build.strip().endswith(" .") and "--push" not in build
    # The key is made on the runner for this run, never a stored secret or a literal.
    assert "openssl rand" in runs and 'CLOCKWORK_SECRET_KEY="$key"' in runs
    assert "--init" in runs  # as compose's init: true
    assert "127.0.0.1:5573:5573" in runs  # published to the runner's loopback only
    for step in _steps(doc, "image"):
        uses = str(step.get("uses", ""))
        assert not uses.startswith(("docker/login-action", "docker/build-push-action")), uses
    stop = [s for s in _steps(doc, "image") if "docker stop" in str(s.get("run", ""))]
    assert stop
    # The stop is ASSERTED (fix round 1, M8): exit 0, drained, nothing killed.
    script = str(stop[0]["run"])
    assert "|| true" not in script.split("docker stop", 1)[1].splitlines()[0]
    assert "{{.State.ExitCode}}" in script and '= "0"' in script
    assert "Shut down (operation=shutdown)" in script
    assert "did not drain|Terminating |Killing " in script
    remove = [s for s in _steps(doc, "image") if "docker rm -f" in str(s.get("run", ""))]
    assert remove and remove[-1].get("if") == "always()"
    # The stop waits out the compose file's grace, not Docker's 10 s default.
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    grace = str(compose["services"]["game"]["stop_grace_period"])
    assert grace.endswith("s") and f"--time {int(grace[:-1])}" in str(stop[0]["run"])


def test_the_committed_client_entry_is_lf_so_a_linux_build_matches_it() -> None:
    """The client job's diff compares a Linux build with the committed one."""
    assert b"\r" not in (REPO / "ui" / "index.html").read_bytes()
    assert b"\r" not in DIST_INDEX.read_bytes()
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "ui/index.html text eol=lf" in rules
    assert "content/scenes/clockwork/static/dist/index.html text eol=lf" in rules
