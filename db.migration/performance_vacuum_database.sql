-- Local/non-production workload; do not run against production databases.
\set ON_ERROR_STOP on
SELECT pg_advisory_lock(840175);

SET citus.multi_shard_modify_mode TO 'sequential';

SELECT rcas.ensure_user_day_partition(CURRENT_DATE - 2);
SELECT rcas.ensure_user_day_partition(CURRENT_DATE - 1);
SELECT rcas.ensure_user_day_partition(CURRENT_DATE);

INSERT INTO rcas.user_identity (id, username, email, created_on)
SELECT
    nextval('rcas.user_t_id_seq'),
    'performance-user-' || lpad(user_number::TEXT, 5, '0'),
    'performance-user-' || lpad(user_number::TEXT, 5, '0') || '@example.test',
    (CURRENT_DATE - ((user_number - 1) % 3))::TIMESTAMP
FROM generate_series(1, 30000) AS series(user_number)
ON CONFLICT DO NOTHING;

INSERT INTO rcas.user_t (id, username, password, email, created_on)
SELECT id, username, 'synthetic-password', email, created_on
FROM rcas.user_identity
WHERE username ~ '^performance-user-[0-9]{5}$'
ON CONFLICT DO NOTHING;

UPDATE rcas.user_t u
SET last_login = COALESCE(last_login, TIMESTAMP '2000-01-01') + INTERVAL '1 second'
FROM rcas.user_identity i
WHERE u.id = i.id AND i.username ~ '^performance-user-[0-9]{5}$'
  AND i.email = i.username || '@example.test';

DELETE FROM rcas.user_t u
USING rcas.user_identity i
WHERE u.id = i.id AND i.username ~ '^performance-user-[0-9]{5}$'
  AND i.email = i.username || '@example.test'
  AND right(i.username, 5)::INTEGER % 10 = 0;

DELETE FROM rcas.user_identity
WHERE username ~ '^performance-user-[0-9]{5}$'
  AND email = username || '@example.test'
  AND right(username, 5)::INTEGER % 10 = 0;

ANALYZE rcas.user_t;
SELECT tableoid::REGCLASS AS partition_name, count(*) AS live_performance_users
FROM rcas.user_t
WHERE username ~ '^performance-user-[0-9]{5}$' AND email = username || '@example.test'
GROUP BY tableoid ORDER BY partition_name;

SELECT pg_advisory_unlock(840175);
