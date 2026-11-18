#!/usr/bin/env bash
set -euo pipefail

COMPOSE_CMD="${COMPOSE:-docker compose}"
DB_USER="${DB_USER:-test}"
DB_NAME="${DB_NAME:-testdb}"
OUT_FILE="${1:-}"

SQL_PAYLOAD=$(cat <<'SQL'
\pset pager off
\echo [settings]
SHOW autovacuum;
SHOW autovacuum_naptime;
SHOW autovacuum_vacuum_scale_factor;
SHOW autovacuum_analyze_scale_factor;
SHOW autovacuum_vacuum_cost_limit;
SHOW autovacuum_vacuum_cost_delay;
SHOW log_autovacuum_min_duration;

\echo [table_options]
SELECT
  c.relname AS table,
  COALESCE(array_to_string(c.reloptions, ', '), '(default)') AS reloptions
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('user_t', 'subscription')
ORDER BY c.relname;

\echo [dead_tuples]
SELECT
  schemaname,
  relname,
  n_live_tup,
  n_dead_tup,
  ROUND(CASE WHEN (n_live_tup + n_dead_tup) = 0 THEN 0 ELSE (n_dead_tup::numeric * 100) / (n_live_tup + n_dead_tup) END, 2) AS dead_tuple_ratio_percent,
  last_autovacuum,
  last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('user_t', 'subscription')
ORDER BY relname;

\echo [long_running_transactions]
SELECT
  COALESCE(MAX(EXTRACT(EPOCH FROM (clock_timestamp() - xact_start))), 0)::numeric(12,2) AS longest_tx_seconds
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND state <> 'idle';

\echo [vacuum_progress]
SELECT
  a.datname,
  c.relname,
  p.phase,
  EXTRACT(EPOCH FROM (clock_timestamp() - a.query_start))::numeric(12,2) AS duration_seconds
FROM pg_stat_progress_vacuum p
JOIN pg_stat_activity a ON a.pid = p.pid
JOIN pg_class c ON c.oid = p.relid
ORDER BY duration_seconds DESC;
SQL
)

CMD="$COMPOSE_CMD exec -T postgres psql -U $DB_USER -d $DB_NAME -v ON_ERROR_STOP=1"

if [[ -n "$OUT_FILE" ]]; then
  printf '%s\n' "$SQL_PAYLOAD" | bash -lc "$CMD" | tee "$OUT_FILE"
else
  printf '%s\n' "$SQL_PAYLOAD" | bash -lc "$CMD"
fi


