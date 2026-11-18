-- Run explicitly with psql -v ON_ERROR_STOP=1 during a write-free maintenance window.
-- This migration is for the original unpartitioned schema, not a fresh installation.
BEGIN;
LOCK TABLE subscription IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF (SELECT relkind FROM pg_class WHERE oid = 'subscription'::regclass) <> 'r' THEN
        RAISE EXCEPTION 'subscription is not an unpartitioned table';
    END IF;
    IF EXISTS (SELECT id FROM subscription GROUP BY id HAVING count(*) > 1)
       OR EXISTS (SELECT type FROM subscription GROUP BY type HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM subscription WHERE id IS NULL OR type IS NULL
                   OR active IS NULL OR user_id IS NULL) THEN
        RAISE EXCEPTION 'subscription contains duplicate or null values';
    END IF;
    -- Incoming foreign keys and views would continue to reference the retained old table.
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE confrelid = 'subscription'::regclass AND contype = 'f')
       OR EXISTS (SELECT 1 FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid
                  WHERE d.refobjid = 'subscription'::regclass AND r.ev_class <> d.refobjid) THEN
        RAISE EXCEPTION 'subscription has dependent foreign keys or views; plan their migration first';
    END IF;
    IF (SELECT count(*) FROM pg_constraint WHERE conrelid = 'subscription'::regclass) <> 2
       OR NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'subscription'::regclass
                      AND contype = 'p' AND pg_get_constraintdef(oid) = 'PRIMARY KEY (id)')
       OR NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'subscription'::regclass
                      AND contype = 'u' AND pg_get_constraintdef(oid) = 'UNIQUE (type)')
       OR EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'subscription'::regclass AND NOT tgisinternal)
       OR EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = 'subscription'::regclass
                  AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid))
       OR (SELECT relacl IS NOT NULL OR relrowsecurity FROM pg_class WHERE oid = 'subscription'::regclass) THEN
        RAISE EXCEPTION 'subscription has custom constraints, indexes, triggers or grants; plan their migration first';
    END IF;
    IF pg_get_serial_sequence('subscription', 'id') IS DISTINCT FROM
       format('%I.%I', current_schema(), 'subscription_id_seq') THEN
        RAISE EXCEPTION 'unexpected subscription ID sequence; investigate before migration';
    END IF;
END;
$$;

ALTER TABLE subscription RENAME TO subscription_legacy;
CREATE TABLE subscription (
    id INT NOT NULL DEFAULT nextval('subscription_id_seq'),
    type VARCHAR(50) NOT NULL,
    active INT NOT NULL,
    user_id INT NOT NULL,
    CONSTRAINT subscription_partitioned_pkey PRIMARY KEY (id)
) PARTITION BY HASH (id);
CREATE TABLE subscription_p0 PARTITION OF subscription FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE subscription_p1 PARTITION OF subscription FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE subscription_p2 PARTITION OF subscription FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE subscription_p3 PARTITION OF subscription FOR VALUES WITH (MODULUS 4, REMAINDER 3);
CREATE INDEX subscription_user_id_idx ON subscription (user_id);
CREATE TABLE subscription_type_registry (
    type VARCHAR(50) PRIMARY KEY,
    subscription_id INT NOT NULL UNIQUE,
    UNIQUE (type, subscription_id),
    FOREIGN KEY (subscription_id) REFERENCES subscription(id) DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE subscription ADD CONSTRAINT subscription_type_registry_fk
    FOREIGN KEY (type, id) REFERENCES subscription_type_registry(type, subscription_id)
    DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION sync_subscription_type_registry() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        DELETE FROM subscription_type_registry WHERE subscription_id = OLD.id;
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        INSERT INTO subscription_type_registry (type, subscription_id) VALUES (NEW.type, NEW.id);
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER subscription_type_guard AFTER INSERT OR DELETE OR UPDATE OF id, type ON subscription
    FOR EACH ROW EXECUTE FUNCTION sync_subscription_type_registry();

INSERT INTO subscription (id, type, active, user_id)
    SELECT id, type, active, user_id FROM subscription_legacy;
DO $$
BEGIN
    IF (SELECT count(*) FROM subscription) <> (SELECT count(*) FROM subscription_legacy)
       OR EXISTS ((SELECT * FROM subscription EXCEPT SELECT * FROM subscription_legacy)
                  UNION ALL (SELECT * FROM subscription_legacy EXCEPT SELECT * FROM subscription)) THEN
        RAISE EXCEPTION 'subscription copy validation failed';
    END IF;
END;
$$;
ALTER TABLE subscription_legacy ALTER COLUMN id DROP DEFAULT;
ALTER SEQUENCE subscription_id_seq OWNED BY subscription.id;
SELECT setval('subscription_id_seq', GREATEST((SELECT last_value FROM subscription_id_seq), max(id)), true)
    FROM subscription HAVING max(id) IS NOT NULL AND max(id) >= (SELECT last_value FROM subscription_id_seq);
SET CONSTRAINTS ALL IMMEDIATE;
COMMIT;
