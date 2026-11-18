CREATE TABLE public.user_identity (
    id INT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_on TIMESTAMP NOT NULL,
    UNIQUE (id, username, email, created_on)
);
CREATE TABLE "user_t" (
    id SERIAL,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_on TIMESTAMP NOT NULL,
    last_login TIMESTAMP,
    PRIMARY KEY (created_on, id),
    FOREIGN KEY (id, username, email, created_on)
        REFERENCES public.user_identity (id, username, email, created_on)
        DEFERRABLE INITIALLY DEFERRED
) PARTITION BY RANGE (created_on);
CREATE INDEX user_t_id_idx ON public.user_t (id);
CREATE TABLE public.user_t_default PARTITION OF public.user_t DEFAULT;
ALTER TABLE public.user_identity ADD CONSTRAINT user_identity_user_t_fk
    FOREIGN KEY (created_on, id) REFERENCES public.user_t (created_on, id)
    DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION public.sync_user_identity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR TG_OP = 'UPDATE' THEN
        DELETE FROM public.user_identity WHERE id = OLD.id;
    END IF;
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        INSERT INTO public.user_identity (id, username, email, created_on)
        VALUES (NEW.id, NEW.username, NEW.email, NEW.created_on);
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER user_identity_guard
    AFTER INSERT OR DELETE OR UPDATE OF id, username, email, created_on ON public.user_t
    FOR EACH ROW EXECUTE FUNCTION public.sync_user_identity();
CREATE FUNCTION public.apply_user_partition_autovacuum() RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    partition_table REGCLASS;
BEGIN
    FOR partition_table IN
        SELECT inhrelid::regclass FROM pg_inherits WHERE inhparent = 'public.user_t'::regclass
    LOOP
        EXECUTE format(
            'ALTER TABLE %s SET (autovacuum_enabled = true, autovacuum_vacuum_threshold = 50, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_threshold = 50, autovacuum_analyze_scale_factor = 0.01, autovacuum_vacuum_cost_limit = 800)',
            partition_table
        );
    END LOOP;
END;
$$;
CREATE FUNCTION public.ensure_user_day_partition(partition_date DATE) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF partition_date IS NULL OR NOT isfinite(partition_date) THEN
        RAISE EXCEPTION 'partition_date must be a finite date';
    END IF;
    LOCK TABLE public.user_t IN ACCESS EXCLUSIVE MODE;
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.user_t FOR VALUES FROM (%L) TO (%L)',
        'user_t_' || to_char(partition_date, 'YYYYMMDD'),
        partition_date::TIMESTAMP,
        (partition_date + 1)::TIMESTAMP
    );
    PERFORM public.apply_user_partition_autovacuum();
END;
$$;
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
