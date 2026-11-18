CREATE TABLE "user_t" (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(50) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_on TIMESTAMP NOT NULL,
    last_login TIMESTAMP
);
CREATE TABLE subscription (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL,
    active INT NOT NULL,
    user_id INT NOT NULL
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
