#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080/app}"
USER_IDS="${USER_IDS:-1000,1001,1002}"
CONCURRENCY_LEVELS="${CONCURRENCY_LEVELS:-1 8}"
REQUESTS_PER_WORKER="${REQUESTS_PER_WORKER:-100}"
REQUEST_DELAY="${REQUEST_DELAY:-0.5}"

case "$BASE_URL" in
    http://localhost|http://localhost:*|http://127.0.0.1|http://127.0.0.1:*) ;;
    *)
        echo "BASE_URL must target localhost or 127.0.0.1" >&2
        exit 2
        ;;
esac

if ! [[ "$REQUESTS_PER_WORKER" =~ ^[1-9][0-9]*$ ]]; then
    echo "REQUESTS_PER_WORKER must be a positive integer" >&2
    exit 2
fi
if ((REQUESTS_PER_WORKER > 1000)); then
    echo "REQUESTS_PER_WORKER is limited to 1000" >&2
    exit 2
fi
if ! [[ "$REQUEST_DELAY" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "REQUEST_DELAY must be a non-negative number of seconds" >&2
    exit 2
fi

IFS=',' read -r -a user_ids <<< "$USER_IDS"
if [[ "${#user_ids[@]}" -eq 0 ]]; then
    echo "USER_IDS must contain at least one comma-separated user id" >&2
    exit 2
fi
for user_id in "${user_ids[@]}"; do
    if ! [[ "$user_id" =~ ^[1-9][0-9]*$ ]]; then
        echo "USER_IDS must contain positive numeric IDs" >&2
        exit 2
    fi
done

run_worker() {
    local worker="$1"
    local request
    local id_index
    local user_id

    for ((request = 0; request < REQUESTS_PER_WORKER; request++)); do
        id_index=$(((worker + request) % ${#user_ids[@]}))
        user_id="${user_ids[$id_index]}"
        curl --silent --show-error --fail --connect-timeout 5 --max-time 30 --output /dev/null \
            "$BASE_URL/user/$user_id"
        sleep "$REQUEST_DELAY"
    done
}

for workers in $CONCURRENCY_LEVELS; do
    if ! [[ "$workers" =~ ^[1-9][0-9]*$ ]]; then
        echo "CONCURRENCY_LEVELS must contain positive integers" >&2
        exit 2
    fi
    if ((workers > 32)); then
        echo "CONCURRENCY_LEVELS is limited to 32 workers" >&2
        exit 2
    fi

    start_time="$(date +%s)"
    echo "Running $workers concurrent workers x $REQUESTS_PER_WORKER GET requests"
    pids=()
    for ((worker = 0; worker < workers; worker++)); do
        run_worker "$worker" &
        pids+=("$!")
    done
    failed=0
    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            failed=1
        fi
    done
    if ((failed)); then
        echo "Load phase failed: at least one worker could not complete its requests" >&2
        exit 1
    fi
    elapsed=$(( $(date +%s) - start_time ))
    echo "Completed $((workers * REQUESTS_PER_WORKER)) reads in ${elapsed}s at concurrency=$workers"
done
