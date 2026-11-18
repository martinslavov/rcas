-- Local/non-production workload; do not run against production databases.
\set ON_ERROR_STOP on
SELECT pg_advisory_lock(840175);

SELECT public.ensure_user_day_partition(CURRENT_DATE - 2);
SELECT public.ensure_user_day_partition(CURRENT_DATE - 1);
SELECT public.ensure_user_day_partition(CURRENT_DATE);

INSERT INTO public.user_t (username, password, email, created_on)
SELECT
    'performance-user-' || lpad(user_number::TEXT, 5, '0'),
    'synthetic-password',
    'performance-user-' || lpad(user_number::TEXT, 5, '0') || '@example.test',
    (CURRENT_DATE - ((user_number - 1) % 3))::TIMESTAMP
FROM generate_series(1, 30000) AS series(user_number)
WHERE NOT EXISTS (
    SELECT 1 FROM public.user_identity ui
    WHERE ui.username = 'performance-user-' || lpad(user_number::TEXT, 5, '0')
);

UPDATE public.user_t
SET last_login = COALESCE(last_login, TIMESTAMP '2000-01-01') + INTERVAL '1 second'
WHERE username ~ '^performance-user-[0-9]{5}$' AND email = username || '@example.test';

DELETE FROM public.user_t
WHERE username ~ '^performance-user-[0-9]{5}$'
  AND email = username || '@example.test'
  AND right(username, 5)::INTEGER % 10 = 0;

ANALYZE public.user_t;
SELECT tableoid::REGCLASS AS partition_name, count(*) AS live_performance_users
FROM public.user_t
WHERE username ~ '^performance-user-[0-9]{5}$' AND email = username || '@example.test'
GROUP BY tableoid ORDER BY partition_name;

SELECT pg_advisory_unlock(840175);
