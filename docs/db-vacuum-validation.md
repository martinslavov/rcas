# Database vacuum validation evidence

This document records issue #263 validation from a non-production environment. The evidence and commands below are
historical: they were collected against the original PostgreSQL Compose stack before the Citus conversion. They are not
reproducible against the current Citus Compose schema, which uses the `rcas` schema and does not mount the old
autovacuum-tuning script.

## Environment

- Stack: original local Docker Compose (`postgres`, `postgres-exporter`, Prometheus, Grafana)
- Database: `testdb`
- Date: 2026-11-18

## Commands used

```bash
make monitoring-up
docker compose exec -T postgres psql -U test -d testdb -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/04-autovacuum-tuning.sql

docker compose exec -T postgres psql -U test -d testdb -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO public."subscription" (id, type, active, user_id)
SELECT gs, 'bulk-' || gs::text, 1, 1
FROM generate_series(1000, 1300) gs
ON CONFLICT (id) DO NOTHING;

UPDATE public."subscription"
SET active = CASE WHEN active = 0 THEN 1 ELSE 0 END
WHERE id BETWEEN 1000 AND 1300;

DELETE FROM public."subscription"
WHERE id BETWEEN 1201 AND 1300;

ANALYZE public."subscription";
SQL

make vacuum-snapshot OUT=build/reports/vacuum-before.txt

docker compose exec -T postgres psql -U test -d testdb -v ON_ERROR_STOP=1 -c 'VACUUM (ANALYZE) public."subscription";'

make vacuum-snapshot OUT=build/reports/vacuum-after.txt
```

## Before snapshot (summary)

Source: `build/reports/vacuum-before.txt`

- `autovacuum=on`, `autovacuum_naptime=30s`, `autovacuum_vacuum_scale_factor=0.05`, `autovacuum_analyze_scale_factor=0.02`.
- Table-level reloptions were active for both `user_t` and `subscription`.
- `subscription` showed churn and bloat indicator values:
  - `n_live_tup=405`
  - `n_dead_tup=401`
  - `dead_tuple_ratio_percent=49.75`

## After snapshot (summary)

Source: `build/reports/vacuum-after.txt`

- After manual `VACUUM (ANALYZE)` on `subscription`:
  - `n_live_tup=204`
  - `n_dead_tup=0`
  - `dead_tuple_ratio_percent=0.00`
- Snapshot still reported global settings and table-level reloptions.
- `longest_tx_seconds=0.00` during the validation window.

## Notes

- This validation is non-production only.
- If PostgreSQL data volume already exists, apply the tuning SQL once (as shown) before taking snapshots.
