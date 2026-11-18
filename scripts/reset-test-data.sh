#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD="${COMPOSE:-docker compose}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${RCAS_BASE_URL:-http://localhost:8080/app}"

if ! [[ "$BASE_URL" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?(/.*)?$ ]]; then
    if [[ "${RCAS_ALLOW_REMOTE_RESET:-0}" != "1" ]]; then
        echo "Skipping local test-data reset for non-local RCAS_BASE_URL=$BASE_URL"
        exit 0
    fi
fi

# Reset persistent stores first, then restart RCAS so its in-memory cache starts clean too.
bash -lc "$COMPOSE_CMD exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
TRUNCATE TABLE rcas.subscription, rcas.user_t, rcas.subscription_type_registry, rcas.user_identity RESTART IDENTITY CASCADE;

INSERT INTO rcas.user_identity (id, username, email, created_on)
VALUES
    (1, 'martin', 'slavoff.martin@gmail.com', TIMESTAMP '2024-01-01 00:00:00'),
    (2, 'test1', 'test1.test1@gmail.com', TIMESTAMP '2024-01-01 00:00:00'),
    (3, 'test2', 'test2.test2@gmail.com', TIMESTAMP '2024-01-01 00:00:00');

INSERT INTO rcas.user_t (id, username, password, email, created_on, last_login)
VALUES
    (1, 'martin', 'password', 'slavoff.martin@gmail.com', TIMESTAMP '2024-01-01 00:00:00', NULL),
    (2, 'test1', 'password', 'test1.test1@gmail.com', TIMESTAMP '2024-01-01 00:00:00', NULL),
    (3, 'test2', 'password', 'test2.test2@gmail.com', TIMESTAMP '2024-01-01 00:00:00', NULL);

INSERT INTO rcas.subscription_type_registry (type, subscription_id)
VALUES ('1', 1), ('2', 2), ('3', 3);

INSERT INTO rcas.subscription (id, type, active, user_id)
VALUES
    (1, '1', 1, 1),
    (2, '2', 0, 1),
    (3, '3', 0, 1);

SELECT setval('rcas.user_t_id_seq', (SELECT MAX(id) FROM rcas.user_t));
SELECT setval('rcas.subscription_id_seq', (SELECT MAX(id) FROM rcas.subscription));
COMMIT;
SQL"

bash -lc "$COMPOSE_CMD exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 -tAc \"SELECT COUNT(*) FROM rcas.user_t\" | grep -qx '3'"
bash -lc "$COMPOSE_CMD exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 -tAc \"SELECT COUNT(*) FROM rcas.subscription\" | grep -qx '3'"
bash -lc "$COMPOSE_CMD exec -T redis redis-cli FLUSHALL SYNC | grep -q '^OK$'"
bash -lc "$COMPOSE_CMD --profile app restart rcas"

COMPOSE="$COMPOSE_CMD" "$SCRIPT_DIR/wait-for-stack-ready.sh"

echo "Deterministic test data reset completed"
