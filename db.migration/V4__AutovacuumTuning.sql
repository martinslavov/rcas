-- Partitioned parents have no storage: tune their leaf tables, not the parents.
-- Include ordinary tables so existing unpartitioned installations remain supported.
DO $$
DECLARE
    target RECORD;
BEGIN
    FOR target IN
        SELECT tree.relid, root.name
        FROM (VALUES ('user_t'), ('subscription')) AS root(name)
        CROSS JOIN LATERAL pg_partition_tree(format('public.%I', root.name)::regclass) tree
        WHERE tree.isleaf
        UNION ALL
        SELECT c.oid, c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname IN ('user_t', 'subscription') AND c.relkind = 'r'
    LOOP
        EXECUTE format(
            'ALTER TABLE %s SET (autovacuum_enabled = true, autovacuum_vacuum_threshold = %s, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_threshold = 50, autovacuum_analyze_scale_factor = 0.01, autovacuum_vacuum_cost_limit = %s)',
            target.relid::regclass,
            CASE WHEN target.name = 'user_t' THEN 50 ELSE 100 END,
            CASE WHEN target.name = 'user_t' THEN 800 ELSE 1200 END
        );
    END LOOP;
END;
$$;
