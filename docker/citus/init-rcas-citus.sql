CREATE EXTENSION IF NOT EXISTS citus;

SELECT citus_update_node(nodeid, 'postgresql-node1', 5432)
FROM pg_dist_node
WHERE nodename = 'citus-worker-1' AND nodeport = 5432;
SELECT citus_update_node(nodeid, 'postgresql-node2', 5432)
FROM pg_dist_node
WHERE nodename = 'citus-worker-2' AND nodeport = 5432;

SELECT citus_add_node('postgresql-node1', 5432)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_node
    WHERE nodename = 'postgresql-node1' AND nodeport = 5432
);
SELECT citus_add_node('postgresql-node2', 5432)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_node
    WHERE nodename = 'postgresql-node2' AND nodeport = 5432
);

SET citus.multi_shard_modify_mode TO 'sequential';

CREATE SCHEMA IF NOT EXISTS rcas;
ALTER ROLE test SET search_path TO rcas, public;

CREATE SEQUENCE IF NOT EXISTS rcas.user_t_id_seq;
CREATE SEQUENCE IF NOT EXISTS rcas.subscription_id_seq;

CREATE TABLE IF NOT EXISTS rcas.user_identity (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_on TIMESTAMP NOT NULL,
    UNIQUE (id, username, email, created_on)
);

SELECT create_reference_table('rcas.user_identity')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_partition
    WHERE logicalrelid = 'rcas.user_identity'::REGCLASS
);

CREATE TABLE IF NOT EXISTS rcas.subscription_type_registry (
    type VARCHAR(50) PRIMARY KEY,
    subscription_id INTEGER NOT NULL UNIQUE,
    UNIQUE (type, subscription_id)
);

SELECT create_reference_table('rcas.subscription_type_registry')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_partition
    WHERE logicalrelid = 'rcas.subscription_type_registry'::REGCLASS
);

CREATE TABLE IF NOT EXISTS rcas.user_t (
    id INTEGER NOT NULL DEFAULT nextval('rcas.user_t_id_seq'::REGCLASS),
    username VARCHAR(50) NOT NULL,
    password VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_on TIMESTAMP NOT NULL,
    last_login TIMESTAMP,
    CONSTRAINT user_t_pkey PRIMARY KEY (created_on, id),
    CONSTRAINT user_t_identity_fk
        FOREIGN KEY (id, username, email, created_on)
        REFERENCES rcas.user_identity (id, username, email, created_on)
) PARTITION BY RANGE (created_on);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_attribute a
        JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'rcas.user_t'::REGCLASS
          AND a.attname = 'id'
          AND pg_get_expr(d.adbin, d.adrelid) LIKE '%user_t_id_seq%'
    ) THEN
        RAISE EXCEPTION 'rcas.user_t.id must default to rcas.user_t_id_seq; recreate the local Citus volumes to apply this schema change';
    END IF;
END
$$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_dist_partition
        WHERE logicalrelid = 'rcas.user_t'::REGCLASS
    ) THEN
        ALTER SEQUENCE rcas.user_t_id_seq OWNED BY rcas.user_t.id;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS rcas.user_t_default
    PARTITION OF rcas.user_t DEFAULT;

CREATE OR REPLACE FUNCTION rcas.ensure_user_day_partition(partition_date DATE)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    partition_name TEXT := format('user_t_%s', to_char(partition_date, 'YYYYMMDD'));
BEGIN
    IF partition_date IS NULL OR NOT isfinite(partition_date) THEN
        RAISE EXCEPTION 'partition_date must be a finite date';
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS rcas.%I PARTITION OF rcas.user_t '
        'FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        partition_date::TIMESTAMP,
        (partition_date + 1)::TIMESTAMP
    );
END
$$;

SELECT rcas.ensure_user_day_partition(CURRENT_DATE - 2);
SELECT rcas.ensure_user_day_partition(CURRENT_DATE - 1);
SELECT rcas.ensure_user_day_partition(CURRENT_DATE);

CREATE INDEX IF NOT EXISTS user_t_id_idx ON rcas.user_t (id);

SELECT create_distributed_table('rcas.user_t', 'id', colocate_with => 'none')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_partition
    WHERE logicalrelid = 'rcas.user_t'::REGCLASS
);

SELECT rcas.ensure_user_day_partition(CURRENT_DATE + 1);

CREATE TABLE IF NOT EXISTS rcas.subscription (
    id INTEGER NOT NULL DEFAULT nextval('rcas.subscription_id_seq'::REGCLASS),
    type VARCHAR(50) NOT NULL,
    active INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    CONSTRAINT subscription_pkey PRIMARY KEY (user_id, id),
    CONSTRAINT subscription_type_registry_fk
        FOREIGN KEY (type, id)
        REFERENCES rcas.subscription_type_registry (type, subscription_id)
) PARTITION BY HASH (id);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_attribute a
        JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'rcas.subscription'::REGCLASS
          AND a.attname = 'id'
          AND pg_get_expr(d.adbin, d.adrelid) LIKE '%subscription_id_seq%'
    ) THEN
        RAISE EXCEPTION 'rcas.subscription.id must default to rcas.subscription_id_seq; recreate the local Citus volumes to apply this schema change';
    END IF;
END
$$;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_dist_partition
        WHERE logicalrelid = 'rcas.subscription'::REGCLASS
    ) THEN
        ALTER SEQUENCE rcas.subscription_id_seq OWNED BY rcas.subscription.id;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS rcas.subscription_p0 PARTITION OF rcas.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE IF NOT EXISTS rcas.subscription_p1 PARTITION OF rcas.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE IF NOT EXISTS rcas.subscription_p2 PARTITION OF rcas.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE IF NOT EXISTS rcas.subscription_p3 PARTITION OF rcas.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 3);

CREATE INDEX IF NOT EXISTS subscription_user_id_idx ON rcas.subscription (user_id);

SELECT create_distributed_table(
    'rcas.subscription',
    'user_id',
    colocate_with => 'rcas.user_t'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_dist_partition
    WHERE logicalrelid = 'rcas.subscription'::REGCLASS
);

INSERT INTO rcas.user_identity (id, username, email, created_on)
VALUES
    (1, 'martin', 'slavoff.martin@gmail.com', CURRENT_DATE - 2),
    (2, 'test1', 'test1.test1@gmail.com', CURRENT_DATE - 1),
    (3, 'test2', 'test2.test2@gmail.com', CURRENT_DATE)
ON CONFLICT DO NOTHING;

INSERT INTO rcas.user_t (id, username, password, email, created_on)
SELECT id, username, 'password', email, created_on
FROM rcas.user_identity
WHERE id IN (1, 2, 3)
ON CONFLICT (created_on, id) DO NOTHING;

INSERT INTO rcas.subscription_type_registry (type, subscription_id)
VALUES ('1', 1), ('2', 2), ('3', 3)
ON CONFLICT DO NOTHING;

INSERT INTO rcas.subscription (id, type, active, user_id)
VALUES
    (1, '1', 1, 1),
    (2, '2', 0, 1),
    (3, '3', 0, 1)
ON CONFLICT DO NOTHING;

SELECT setval(
    'rcas.user_t_id_seq',
    GREATEST((SELECT last_value FROM rcas.user_t_id_seq), COALESCE((SELECT MAX(id) FROM rcas.user_t), 1)),
    true
);
SELECT setval(
    'rcas.subscription_id_seq',
    GREATEST((SELECT last_value FROM rcas.subscription_id_seq), COALESCE((SELECT MAX(id) FROM rcas.subscription), 1)),
    true
);
