CREATE EXTENSION IF NOT EXISTS citus;
SELECT citus_version();

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

DROP SCHEMA IF EXISTS citus_poc CASCADE;
CREATE SCHEMA citus_poc;
CREATE SEQUENCE citus_poc.user_t_id_seq;
CREATE SEQUENCE citus_poc.subscription_id_seq;

CREATE TABLE citus_poc.user_identity (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_on TIMESTAMP NOT NULL,
    UNIQUE (id, username, email, created_on)
);
SELECT create_reference_table('citus_poc.user_identity');

CREATE TABLE citus_poc.subscription_type_registry (
    type VARCHAR(50) PRIMARY KEY,
    subscription_id INTEGER NOT NULL UNIQUE,
    UNIQUE (type, subscription_id)
);
SELECT create_reference_table('citus_poc.subscription_type_registry');

CREATE TABLE citus_poc.user_t (
    id INTEGER NOT NULL DEFAULT nextval('citus_poc.user_t_id_seq'::REGCLASS),
    username VARCHAR(50) NOT NULL,
    password VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_on TIMESTAMP NOT NULL,
    last_login TIMESTAMP,
    CONSTRAINT user_t_pkey PRIMARY KEY (created_on, id),
    CONSTRAINT user_t_identity_fk
        FOREIGN KEY (id, username, email, created_on)
        REFERENCES citus_poc.user_identity (id, username, email, created_on)
) PARTITION BY RANGE (created_on);
ALTER SEQUENCE citus_poc.user_t_id_seq OWNED BY citus_poc.user_t.id;

CREATE TABLE citus_poc.user_t_default
    PARTITION OF citus_poc.user_t DEFAULT;

CREATE FUNCTION citus_poc.ensure_user_day_partition(partition_date DATE)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    partition_name TEXT := format('user_t_%s', to_char(partition_date, 'YYYYMMDD'));
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS citus_poc.%I PARTITION OF citus_poc.user_t '
        'FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        partition_date::TIMESTAMP,
        (partition_date + 1)::TIMESTAMP
    );
END
$$;

SELECT citus_poc.ensure_user_day_partition(CURRENT_DATE - 2);
SELECT citus_poc.ensure_user_day_partition(CURRENT_DATE - 1);
SELECT citus_poc.ensure_user_day_partition(CURRENT_DATE);

CREATE INDEX user_t_id_idx ON citus_poc.user_t (id);

SELECT create_distributed_table('citus_poc.user_t', 'id', colocate_with => 'none');

SELECT citus_poc.ensure_user_day_partition(CURRENT_DATE + 1);

CREATE TABLE citus_poc.subscription (
    id INTEGER NOT NULL DEFAULT nextval('citus_poc.subscription_id_seq'::REGCLASS),
    type VARCHAR(50) NOT NULL,
    active INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    CONSTRAINT subscription_pkey PRIMARY KEY (user_id, id),
    CONSTRAINT subscription_type_registry_fk
        FOREIGN KEY (type, id)
        REFERENCES citus_poc.subscription_type_registry (type, subscription_id)
) PARTITION BY HASH (id);
ALTER SEQUENCE citus_poc.subscription_id_seq OWNED BY citus_poc.subscription.id;

CREATE TABLE citus_poc.subscription_p0 PARTITION OF citus_poc.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE citus_poc.subscription_p1 PARTITION OF citus_poc.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE citus_poc.subscription_p2 PARTITION OF citus_poc.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE citus_poc.subscription_p3 PARTITION OF citus_poc.subscription
    FOR VALUES WITH (MODULUS 4, REMAINDER 3);

CREATE INDEX subscription_user_id_idx ON citus_poc.subscription (user_id);
SELECT create_distributed_table(
    'citus_poc.subscription',
    'user_id',
    colocate_with => 'citus_poc.user_t'
);

INSERT INTO citus_poc.user_identity (id, username, email, created_on)
VALUES
    (1, 'user-1', 'user-1@example.test', CURRENT_DATE - 2),
    (2, 'user-2', 'user-2@example.test', CURRENT_DATE - 1),
    (3, 'user-3', 'user-3@example.test', CURRENT_DATE),
    (4, 'user-4', 'user-4@example.test', CURRENT_DATE + 1);

INSERT INTO citus_poc.subscription_type_registry (type, subscription_id)
VALUES ('type-1', 1001), ('type-2', 1002), ('type-3', 1003);

INSERT INTO citus_poc.user_t (id, username, password, email, created_on)
VALUES
    (1, 'user-1', 'password', 'user-1@example.test', CURRENT_DATE - 2),
    (2, 'user-2', 'password', 'user-2@example.test', CURRENT_DATE - 1),
    (3, 'user-3', 'password', 'user-3@example.test', CURRENT_DATE),
    (4, 'user-4', 'password', 'user-4@example.test', CURRENT_DATE + 1);

INSERT INTO citus_poc.subscription (id, type, active, user_id)
VALUES
    (1001, 'type-1', 1, 1),
    (1002, 'type-2', 0, 1),
    (1003, 'type-3', 1, 4);

INSERT INTO citus_poc.user_identity (id, username, email, created_on)
VALUES (5, 'user-5', 'user-5@example.test', CURRENT_DATE + 1);
SELECT setval('citus_poc.user_t_id_seq', 4, true);
INSERT INTO citus_poc.user_t (username, password, email, created_on)
VALUES ( 'user-5', 'password', 'user-5@example.test', CURRENT_DATE + 1);

INSERT INTO citus_poc.subscription_type_registry (type, subscription_id)
VALUES ('type-4', 1004);
SELECT setval('citus_poc.subscription_id_seq', 1003, true);
INSERT INTO citus_poc.subscription (type, active, user_id)
VALUES ('type-4', 1, 4);

DO $$
BEGIN
    IF (
        SELECT count(DISTINCT tableoid)
        FROM citus_poc.user_t
        WHERE id BETWEEN 1 AND 4
    ) <> 4 THEN
        RAISE EXCEPTION 'Expected four user rows in four daily partitions';
    END IF;

    IF (
        SELECT count(*)
        FROM citus_poc.user_t
        WHERE id = 4 AND created_on::DATE = CURRENT_DATE + 1
    ) <> 1 THEN
        RAISE EXCEPTION 'The newly-created daily partition did not accept its user row';
    END IF;

    IF (
        SELECT count(*)
        FROM citus_poc.subscription
        WHERE user_id = 1
    ) <> 2 THEN
        RAISE EXCEPTION 'Expected both subscriptions for user 1 on its colocated shard';
    END IF;

    IF (
        SELECT id FROM citus_poc.user_t WHERE username = 'user-5'
    ) <> 5 THEN
        RAISE EXCEPTION 'The distributed user table did not generate the expected ID';
    END IF;

    IF (
        SELECT id FROM citus_poc.subscription WHERE type = 'type-4'
    ) <> 1004 THEN
        RAISE EXCEPTION 'The distributed subscription table did not generate the expected ID';
    END IF;

    IF (
        SELECT colocationid
        FROM pg_dist_partition
        WHERE logicalrelid = 'citus_poc.user_t'::REGCLASS
    ) IS DISTINCT FROM (
        SELECT colocationid
        FROM pg_dist_partition
        WHERE logicalrelid = 'citus_poc.subscription'::REGCLASS
    ) THEN
        RAISE EXCEPTION 'Users and subscriptions are not in the same Citus colocation group';
    END IF;

    BEGIN
        INSERT INTO citus_poc.user_identity (id, username, email, created_on)
        VALUES (5, 'user-1', 'duplicate@example.test', CURRENT_DATE + 1);
        RAISE EXCEPTION 'The reference table allowed a duplicate username';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO citus_poc.user_identity (id, username, email, created_on)
        VALUES (5, 'duplicate-user', 'user-1@example.test', CURRENT_DATE + 1);
        RAISE EXCEPTION 'The reference table allowed a duplicate email';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO citus_poc.user_identity (id, username, email, created_on)
        VALUES (1, 'duplicate-user', 'duplicate@example.test', CURRENT_DATE + 1);
        RAISE EXCEPTION 'The reference table allowed a duplicate user ID';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO citus_poc.subscription_type_registry (type, subscription_id)
        VALUES ('duplicate-type', 1001);
        RAISE EXCEPTION 'The reference table allowed a duplicate subscription ID';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO citus_poc.subscription_type_registry (type, subscription_id)
        VALUES ('type-1', 1004);
        RAISE EXCEPTION 'The reference table allowed a duplicate subscription type';
    EXCEPTION
        WHEN unique_violation THEN NULL;
    END;
END
$$;

SELECT count(*) AS user_rows FROM citus_poc.user_t;
SELECT count(DISTINCT tableoid) AS daily_partitions_with_users FROM citus_poc.user_t;
SELECT count(*) AS subscription_rows FROM citus_poc.subscription;
SELECT nodename, nodeport, isactive FROM pg_dist_node ORDER BY nodename;
EXPLAIN (COSTS OFF)
SELECT * FROM citus_poc.user_t WHERE id = 1;
EXPLAIN (COSTS OFF)
SELECT * FROM citus_poc.user_t
WHERE id = 4 AND created_on >= CURRENT_DATE + 1
    AND created_on < CURRENT_DATE + 2;
EXPLAIN (COSTS OFF)
SELECT * FROM citus_poc.subscription WHERE user_id = 1;
