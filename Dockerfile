# The Clockwork Dark -- the hosted server's image (v0.20.0 T18, spec §8.1).
#
#     docker build -t clockwork-dark .
#     docker compose up -d game          # docker-compose.yml: the volume, init, the stop grace
#
# One container runs the supervisor (python -m engine.hosting.supervisor),
# which starts the front door on 5573 and one gunicorn worker per story named
# in hosting.stories, on the container's loopback (docs/HOSTING.md § Docker).
#
# No secret is baked in: CLOCKWORK_SECRET_KEY and CLOCKWORK_LLM_API_KEY reach
# a container through its environment, or as files on /data. The operator's
# settings are /data/config.yaml (made empty on first start by
# deploy/entrypoint.sh). tests/test_deploy_files.py holds this file to its
# shape.

# -- the dependencies ------------------------------------------------------------
# The base the owner develops on and T4's Linux run proved, pinned by digest.
FROM python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b AS deps

# 1 adds faster-whisper (CPU) for push-to-talk in the container; its model is
# downloaded on first use into HF_HOME on the volume, never into a layer.
ARG WITH_WHISPER=0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements-server.txt constraints.txt ./
# The server's requirements under the pins the suite was proven green on
# (requirements-server.txt opens with -c constraints.txt as well): the core of
# requirements.txt plus gunicorn, without faster-whisper, fastmcp or pytest.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/python -m pip install -r requirements-server.txt -c constraints.txt \
 && if [ "$WITH_WHISPER" = "1" ]; then \
        /opt/venv/bin/python -m pip install faster-whisper -c constraints.txt; \
    fi

# -- the image -------------------------------------------------------------------
FROM python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The user every process runs as: uid and gid 10001, no login, no home of its own.
RUN groupadd --system --gid 10001 clockwork \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin clockwork

WORKDIR /app
COPY --from=deps /opt/venv /opt/venv

# What the server runs, and nothing else (.dockerignore is the second fence).
COPY engine/ engine/
COPY games/ games/
COPY content/ content/
COPY deploy/ deploy/
COPY config/default.yaml config/docker.yaml config/
COPY constraints.txt launcher.py ./
COPY scripts/users.py scripts/doctor.py scripts/seed_lore.py scripts/

# Every shipped story's lore index, built into the image (spec §4.1: a derived
# index of shipped content, read-only at run time), and the bytecode compiled
# once, since the running user cannot write /app.
RUN set -eu; \
    for manifest in games/*/game.yaml; do \
        slug="$(basename "$(dirname "$manifest")")"; \
        if grep -q '^  lore_db:' "$manifest"; then \
            CLOCKWORK_GAME="$slug" python scripts/seed_lore.py; \
        fi; \
    done; \
    python -m compileall -q engine games scripts deploy launcher.py; \
    chmod 0755 deploy/entrypoint.sh

# The data volume: accounts, the cookie key, saves, media, logs, metrics and
# the operator's config.yaml. Made and given to the user BEFORE the VOLUME
# line, so a fresh named volume starts writable by uid 10001.
RUN mkdir -p /data && chown 10001:10001 /data && chmod 0750 /data
VOLUME /data

# PYTHONPATH: `python -m engine...` finds the engine whatever working
# directory a `docker run -w` gives it; the paths below are absolute for the
# same reason.
ENV CLOCKWORK_ENV=docker \
    CLOCKWORK_DATA_DIR=/data \
    CLOCKWORK_CONFIG=/data/config.yaml \
    HF_HOME=/data/cache/hf \
    PYTHONPATH=/app

USER 10001:10001

# The front door. Workers listen on the container's loopback, never published.
EXPOSE 5573

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "/app/deploy/healthcheck.py"]

# A plain `docker run` needs `--init` (compose sets `init: true`): without an
# init the supervisor is PID 1 and nothing reaps an orphaned worker; the
# entrypoint says so.
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["python", "-m", "engine.hosting.supervisor"]
