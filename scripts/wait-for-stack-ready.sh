#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD="${COMPOSE:-docker compose}"
BASE_URL="${RCAS_BASE_URL:-http://localhost:8080/app}"
TIMEOUT_SECONDS="${WAIT_READY_TIMEOUT:-180}"
SLEEP_SECONDS="${WAIT_READY_INTERVAL:-2}"

if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WAIT_READY_TIMEOUT must be a positive integer number of seconds" >&2
    exit 2
fi
if ! [[ "$SLEEP_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "WAIT_READY_INTERVAL must be a positive integer number of seconds" >&2
    exit 2
fi

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
    wait_for_command "PostgreSQL" bash -lc "$COMPOSE_CMD exec -T postgres pg_isready -U test -d testdb"
    wait_for_command "Redis" bash -lc "$COMPOSE_CMD exec -T redis redis-cli ping | grep -q '^PONG$'"
    wait_for_command "RCAS health endpoint" bash -lc "
response=\$(curl --silent --show-error --fail --max-time 5 \"$BASE_URL/actuator/health\") || exit 1
printf '%s' \"\$response\" | grep -q '\"status\"[[:space:]]*:[[:space:]]*\"UP\"' || exit 1
printf '%s' \"\$response\" | grep -q '\"r2dbc\".*\"status\"[[:space:]]*:[[:space:]]*\"UP\"' || exit 1
printf '%s' \"\$response\" | grep -q '\"redis\".*\"status\"[[:space:]]*:[[:space:]]*\"UP\"' || exit 1
"
else
    wait_for_command "RCAS health endpoint" bash -lc "
response=\$(curl --silent --show-error --fail --max-time 5 \"$BASE_URL/actuator/health\") || exit 1
printf '%s' \"\$response\" | grep -q '\"status\"[[:space:]]*:[[:space:]]*\"UP\"' || exit 1
"
fi

echo "Stack is ready for component and sanity tests"


