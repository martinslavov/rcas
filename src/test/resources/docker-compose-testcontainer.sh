#!/usr/bin/env bash
set -euo pipefail
# Adapter for the populator's `compose exec -T postgres-coordinator ...` calls.
[[ "$1" == exec && "$2" == -T && "$3" == postgres-coordinator ]]
shift 3
exec docker exec -i "$TEST_POSTGRES_CONTAINER" "$@"
