#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD="${COMPOSE:-docker compose}"
BASE_URL="${RCAS_BASE_URL:-http://localhost:8080/app}"
TIMEOUT_SECONDS="${WAIT_READY_TIMEOUT:-180}"
SLEEP_SECONDS="${WAIT_READY_INTERVAL:-2}"
HEALTH_STABLE_SUCCESSES="${WAIT_READY_STABLE_SUCCESSES:-3}"

if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WAIT_READY_TIMEOUT must be a positive integer number of seconds" >&2
    exit 2
fi
if ! [[ "$SLEEP_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WAIT_READY_INTERVAL must be a positive integer number of seconds" >&2
    exit 2
fi
if ! [[ "$HEALTH_STABLE_SUCCESSES" =~ ^[1-9][0-9]*$ ]]; then
    echo "WAIT_READY_STABLE_SUCCESSES must be a positive integer" >&2
    exit 2
fi

assert_health_is_up() {
    local url="$1"
    python3 - "$url" <<'PY'
import json
import sys
import urllib.request
import urllib.error

url = sys.argv[1] + "/actuator/health"
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(1)
        payload = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
    raise SystemExit(1)

if payload.get("status") != "UP":
    raise SystemExit(1)

components = payload.get("components", {})
for dependency in ("r2dbc", "redis"):
    if components.get(dependency, {}).get("status") != "UP":
        raise SystemExit(1)
PY
}

assert_health_is_up_remote() {
    local url="$1"
    python3 - "$url" <<'PY'
import json
import sys
import urllib.request
import urllib.error

url = sys.argv[1] + "/actuator/health"
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(1)
        payload = json.loads(response.read().decode("utf-8"))
except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
    raise SystemExit(1)

if payload.get("status") != "UP":
    raise SystemExit(1)
PY
}

wait_for_command() {
    local description="$1"
    shift
    local start_epoch
    start_epoch="$(date +%s)"

    while true; do
        if "$@" >/dev/null 2>&1; then
            echo "$description is ready"
            return 0
        fi

        local now
        now="$(date +%s)"
        if (( now - start_epoch >= TIMEOUT_SECONDS )); then
            echo "Timed out waiting for $description after ${TIMEOUT_SECONDS}s" >&2
            return 1
        fi

        sleep "$SLEEP_SECONDS"
    done
}

if [[ "$BASE_URL" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]]; then
    wait_for_command "PostgreSQL container" bash -lc "$COMPOSE_CMD ps --status running postgres | grep -q postgres"
    wait_for_command "Redis container" bash -lc "$COMPOSE_CMD ps --status running redis | grep -q redis"
    wait_for_command "RCAS container" bash -lc "$COMPOSE_CMD ps --status running rcas | grep -q rcas"
    wait_for_command "PostgreSQL" bash -lc "$COMPOSE_CMD exec -T postgres pg_isready -U test -d testdb"
    wait_for_command "Redis" bash -lc "$COMPOSE_CMD exec -T redis redis-cli ping | grep -q '^PONG$'"
    health_start_epoch="$(date +%s)"
    stable_hits=0
    while true; do
        if assert_health_is_up "$BASE_URL"; then
            stable_hits=$((stable_hits + 1))
            if (( stable_hits >= HEALTH_STABLE_SUCCESSES )); then
                echo "RCAS health endpoint is stable (${HEALTH_STABLE_SUCCESSES} consecutive checks)"
                break
            fi
        else
            stable_hits=0
        fi

        now="$(date +%s)"
        if (( now - health_start_epoch >= TIMEOUT_SECONDS )); then
            echo "Timed out waiting for RCAS health stability after ${TIMEOUT_SECONDS}s" >&2
            exit 1
        fi

        sleep "$SLEEP_SECONDS"
    done
else
    wait_for_command "RCAS health endpoint" assert_health_is_up_remote "$BASE_URL"
fi

echo "Stack is ready for component and sanity tests"


