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

-- Serialize the explicit-ID inserts and sequence repair with ordinary writers.
LOCK TABLE "user_t", "subscription" IN ACCESS EXCLUSIVE MODE;

-- Legacy user tables remain supported after the subscription-only migration.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_partitioned_table WHERE partrelid = 'public.user_t'::regclass) THEN
        PERFORM public.ensure_user_day_partition(CURRENT_DATE - 2);
        PERFORM public.ensure_user_day_partition(CURRENT_DATE - 1);
        PERFORM public.ensure_user_day_partition(CURRENT_DATE);
    END IF;
END;
$$;

INSERT INTO public.user_t (id, username, password, email, created_on)
SELECT seed.id, seed.username, seed.password, seed.email, seed.created_on
FROM (VALUES
    (1000, $p$populator-user-1000$p$, $p$populator-password$p$, $p$populator-user-1000@example.com$p$, (CURRENT_DATE - 2)::TIMESTAMP),
    (1001, $p$populator-user-1001$p$, $p$populator-password$p$, $p$populator-user-1001@example.com$p$, (CURRENT_DATE - 1)::TIMESTAMP),
    (1002, $p$populator-user-1002$p$, $p$populator-password$p$, $p$populator-user-1002@example.com$p$, CURRENT_DATE::TIMESTAMP)
) AS seed(id, username, password, email, created_on)
WHERE NOT EXISTS (
    SELECT 1 FROM public.user_t u
    WHERE u.id = seed.id OR u.username = seed.username OR u.email = seed.email
);

INSERT INTO "subscription" (id, type, active, user_id)
SELECT seed.id, seed.type, seed.active, seed.user_id FROM (VALUES
    (1001, $p$populator-1001$p$, 1, 1000),
    (1002, $p$populator-1002$p$, 0, 1000),
    (1003, $p$populator-1003$p$, 0, 1000),
    (1004, $p$populator-1004$p$, 1, 1002)
) AS seed(id, type, active, user_id)
WHERE NOT EXISTS (SELECT 1 FROM subscription s WHERE s.id = seed.id OR s.type = seed.type);

SELECT setval(
    pg_get_serial_sequence($p$"user_t"$p$, $p$id$p$),
    GREATEST((SELECT MAX(id) FROM "user_t"), (SELECT last_value FROM user_t_id_seq), 1)
);
SELECT setval(
    pg_get_serial_sequence($p$"subscription"$p$, $p$id$p$),
    GREATEST((SELECT MAX(id) FROM "subscription"), (SELECT last_value FROM subscription_id_seq), 1)
);

COMMIT;
SQL
