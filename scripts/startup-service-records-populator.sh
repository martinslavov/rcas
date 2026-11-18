#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir/.."

read -r -a compose_command <<< "${COMPOSE:-docker compose}"

if ! "${compose_command[@]}" exec -T postgres-coordinator pg_isready -U test -d testdb >/dev/null 2>&1; then
    printf "%s\n" "PostgreSQL is not running or is not ready. Start the stack first (for example, make monitoring-up)." >&2
    exit 1
fi

"${compose_command[@]}" exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 <<\SQL
BEGIN;

-- Serialize the explicit-ID inserts and sequence repair with ordinary writers.
LOCK TABLE rcas.user_t, rcas.subscription IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    PERFORM rcas.ensure_user_day_partition(CURRENT_DATE - 2);
    PERFORM rcas.ensure_user_day_partition(CURRENT_DATE - 1);
    PERFORM rcas.ensure_user_day_partition(CURRENT_DATE);
END;
$$;

INSERT INTO rcas.user_identity (id, username, email, created_on)
SELECT seed.id, seed.username, seed.email, seed.created_on
FROM (VALUES
    (1000, $p$populator-user-1000$p$, $p$populator-user-1000@example.com$p$, (CURRENT_DATE - 2)::TIMESTAMP),
    (1001, $p$populator-user-1001$p$, $p$populator-user-1001@example.com$p$, (CURRENT_DATE - 1)::TIMESTAMP),
    (1002, $p$populator-user-1002$p$, $p$populator-user-1002@example.com$p$, CURRENT_DATE::TIMESTAMP)
) AS seed(id, username, email, created_on)
ON CONFLICT DO NOTHING;

INSERT INTO rcas.user_t (id, username, password, email, created_on)
SELECT seed.id, seed.username, seed.password, seed.email, seed.created_on
FROM (VALUES
    (1000, $p$populator-user-1000$p$, $p$populator-password$p$, $p$populator-user-1000@example.com$p$, (CURRENT_DATE - 2)::TIMESTAMP),
    (1001, $p$populator-user-1001$p$, $p$populator-password$p$, $p$populator-user-1001@example.com$p$, (CURRENT_DATE - 1)::TIMESTAMP),
    (1002, $p$populator-user-1002$p$, $p$populator-password$p$, $p$populator-user-1002@example.com$p$, CURRENT_DATE::TIMESTAMP)
) AS seed(id, username, password, email, created_on)
JOIN rcas.user_identity i
    ON i.id = seed.id AND i.username = seed.username AND i.email = seed.email AND i.created_on = seed.created_on
ON CONFLICT DO NOTHING;

INSERT INTO rcas.subscription_type_registry (type, subscription_id)
SELECT seed.type, seed.id FROM (VALUES
    (1001, $p$populator-1001$p$),
    (1002, $p$populator-1002$p$),
    (1003, $p$populator-1003$p$),
    (1004, $p$populator-1004$p$)
) AS seed(id, type)
ON CONFLICT DO NOTHING;

INSERT INTO rcas.subscription (id, type, active, user_id)
SELECT seed.id, seed.type, seed.active, seed.user_id FROM (VALUES
    (1001, $p$populator-1001$p$, 1, 1000),
    (1002, $p$populator-1002$p$, 0, 1000),
    (1003, $p$populator-1003$p$, 0, 1000),
    (1004, $p$populator-1004$p$, 1, 1002)
) AS seed(id, type, active, user_id)
JOIN rcas.subscription_type_registry r ON r.subscription_id = seed.id AND r.type = seed.type
ON CONFLICT DO NOTHING;

SELECT setval(
    'rcas.user_t_id_seq',
    GREATEST((SELECT MAX(id) FROM rcas.user_t), (SELECT last_value FROM rcas.user_t_id_seq), 1)
);
SELECT setval(
    'rcas.subscription_id_seq',
    GREATEST((SELECT MAX(id) FROM rcas.subscription), (SELECT last_value FROM rcas.subscription_id_seq), 1)
);

COMMIT;
SQL
