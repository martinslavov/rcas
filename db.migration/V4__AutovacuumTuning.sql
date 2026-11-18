-- Tune autovacuum for high-churn RCAS tables.
-- These settings are table-local and safe to apply repeatedly.

ALTER TABLE IF EXISTS public."user_t"
    SET (
        autovacuum_enabled = true,
        autovacuum_vacuum_threshold = 50,
        autovacuum_vacuum_scale_factor = 0.02,
        autovacuum_analyze_threshold = 50,
        autovacuum_analyze_scale_factor = 0.01,
        autovacuum_vacuum_cost_limit = 800
    );

ALTER TABLE IF EXISTS public."subscription"
    SET (
        autovacuum_enabled = true,
        autovacuum_vacuum_threshold = 100,
        autovacuum_vacuum_scale_factor = 0.02,
        autovacuum_analyze_threshold = 50,
        autovacuum_analyze_scale_factor = 0.01,
        autovacuum_vacuum_cost_limit = 1200
    );

