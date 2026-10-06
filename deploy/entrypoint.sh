#!/bin/sh
# The Docker image's entrypoint (v0.20.0 T18, spec §8.1). POSIX sh.
#
# 1. Proves the data directory ($CLOCKWORK_DATA_DIR, /data) is writable by
#    this user (uid 10001), and stops with the fix if it is not: a fresh named
#    volume is (the image chowns /data before VOLUME), but a host bind mount
#    is root-owned until the operator chowns it.
# 2. Makes the operator's config file empty if it is absent -- only the
#    image's own default, $CLOCKWORK_DATA_DIR/config.yaml -- so the engine's
#    "CLOCKWORK_CONFIG names a file that is not there" error (spec §2.1)
#    fires only for a path the operator actually set wrong.
# 3. execs its arguments (the supervisor, by default), so the supervisor
#    receives the container's signals itself and its gunicorn children are
#    its own. Docker's init (compose's `init: true`) is PID 1 above it and
#    reaps any orphan.
#
# Nothing here reads, prints or writes a secret.

set -eu

data="${CLOCKWORK_DATA_DIR:-/data}"

if [ ! -d "$data" ]; then
    echo "clockwork: the data directory $data does not exist; mount a volume there" >&2
    exit 1
fi

probe="$data/.entrypoint-probe.$$"
if ! ( : > "$probe" ) 2>/dev/null; then
    echo "clockwork: $data is not writable by uid $(id -u) (gid $(id -g))." >&2
    echo "clockwork: a host bind mount is owned by root unless you chown it:" >&2
    echo "clockwork:     sudo chown -R 10001:10001 <the host directory>" >&2
    echo "clockwork: (docs/HOSTING.md, /data ownership). A named volume needs nothing." >&2
    exit 1
fi
rm -f "$probe"

if [ "${CLOCKWORK_CONFIG:-}" = "$data/config.yaml" ] && [ ! -e "$data/config.yaml" ]; then
    : > "$data/config.yaml"
    echo "clockwork: made an empty $data/config.yaml (your settings go there)"
fi

if [ "$$" = "1" ]; then
    echo "clockwork: WARNING: no init: the supervisor will be PID 1 and nothing reaps an orphaned" >&2
    echo "clockwork: gunicorn worker. Run with 'docker run --init', or compose's 'init: true'." >&2
fi

exec "$@"
