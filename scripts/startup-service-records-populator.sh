#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir/.."

read -r -a compose_command <<< "${COMPOSE:-docker compose}"

if ! "${compose_command[@]}" exec -T postgres pg_isready -U test -d testdb >/dev/null 2>&1; then
    printf "%s\n" "PostgreSQL is not running or is not ready. Start the stack first (for example, make monitoring-up)." >&2
    exit 1
fi

"${compose_command[@]}" exec -T postgres psql -U test -d testdb -v ON_ERROR_STOP=1 <<\SQL
BEGIN;

INSERT INTO "user_t" (id, username, password, email, created_on)
VALUES
    (1000, $p$populator-user-1000$p$, $p$populator-password$p$, $p$populator-user-1000@example.com$p$, now()),
    (1001, $p$populator-user-1001$p$, $p$populator-password$p$, $p$populator-user-1001@example.com$p$, now()),
    (1002, $p$populator-user-1002$p$, $p$populator-password$p$, $p$populator-user-1002@example.com$p$, now())
ON CONFLICT DO NOTHING;

INSERT INTO "subscription" (id, type, active, user_id)
VALUES
    (1001, $p$populator-1001$p$, 1, 1000),
    (1002, $p$populator-1002$p$, 0, 1000),
    (1003, $p$populator-1003$p$, 0, 1000),
    (1004, $p$populator-1004$p$, 1, 1002)
ON CONFLICT DO NOTHING;

SELECT setval(
    pg_get_serial_sequence($p$"user_t"$p$, $p$id$p$),
    GREATEST((SELECT MAX(id) FROM "user_t"), 1)
);
SELECT setval(
    pg_get_serial_sequence($p$"subscription"$p$, $p$id$p$),
    GREATEST((SELECT MAX(id) FROM "subscription"), 1)
);

COMMIT;
SQL
