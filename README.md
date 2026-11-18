# RCAS – Reactive Cache Service

> Reactive cache service with Caffeine (L1), Redis (L2) and PostgreSQL over R2DBC, built on Spring Boot WebFlux

**RCAS** (Reactive Cache Service) is a reactive caching service built with Spring Boot WebFlux. It serves user and subscription data without blocking threads and puts a two-level cache in front of the database:

1. **Caffeine**: a fast in-memory (L1) cache inside the application.
2. **Redis**: a shared (L2) reactive cache, accessed through reactive Redis operations.
3. **PostgreSQL**: the source of truth, accessed through non-blocking R2DBC.

A read goes through the caches first and only falls back to the database on a miss, so repeated requests are served without hitting PostgreSQL. All layers are non-blocking, which keeps the service responsive under load with a small number of threads.

Cache entries in Caffeine and Redis expire after access. Configure the shared expiration with `cache.expiration.hours` (24 hours by default).

Every cache lookup is logged at `INFO` as `HIT` or `MISS` per layer (Caffeine, then Redis). Cache writes are logged at `DEBUG` by the dedicated logger `com.gbp.rcas.cache.write`, so they are off by default; enable them with `logging.level.com.gbp.rcas.cache.write=DEBUG` (or the env var `LOGGING_LEVEL_COM_GBP_RCAS_CACHE_WRITE=DEBUG`).

## Tech stack

- Java 25
- Spring Boot 4.1.2 (WebFlux, Data R2DBC, Data Redis Reactive, Actuator, Cache)
- PostgreSQL 15 and Redis 7
- Gradle 9.8.2 (wrapper)
- Docker / Docker Compose

## Prerequisites

- JDK 25 (`JAVA_HOME` must point to it)
- Docker with Docker Compose
- Access to the Docker Hardened Images registry (`docker login dhi.io`), needed to build the Docker image

## Parallel Copilot sessions with Git worktrees

On macOS, `.github/scripts/worktree-session.sh` creates an isolated worktree and `session/<name>` branch next to the
repository, then opens it in IntelliJ IDEA. Set `JETBRAINS_APP` to your installed JetBrains application name when it is
not `IntelliJ IDEA`. Configure the IDE to open projects in a new window if you want one window per Copilot session.

Start a session with a unique lowercase name:

```bash
./.github/scripts/worktree-session.sh start cache-fix
```

The worktree is created at `../rcas-sessions/cache-fix`. To create it without opening the IDE, add `--no-open`.
Start another session with a different name to get a separate folder and branch.

After you have committed and merged the session branch into `origin/main`, archive the Copilot chat and clean up its
worktree:

```bash
./.github/scripts/worktree-session.sh cleanup cache-fix
```

Cleanup fetches `origin/main` and refuses to delete the worktree if it contains uncommitted or untracked files, or if its
branch has not been merged. It accepts `session/<name>` and branches renamed to `feature/<name>` or `hotfix/<name>`;
other branch names and detached HEADs are refused. On success it removes the worktree folder and the **local** branch; it never deletes a remote
branch. The removed folder also includes ignored/generated files such as local IDE settings and build output. Archiving a
Copilot chat does not trigger cleanup automatically, so run this command yourself.

## Build

```bash
./gradlew clean build        # compile + run all tests
./gradlew bootJar            # only build the executable jar (build/libs/rcas-0.0.1-SNAPSHOT.jar)
```

The tests use Testcontainers, so Docker must be running.

## Run

### Docker Compose profiles

`docker-compose.yml` defines the complete local stack. `postgres-coordinator` is the Citus coordinator, backed by
`postgresql-node1` and `postgresql-node2`; Redis, RCAS and monitoring remain on the existing `rcas-docker-network`
and their usual host ports. The legacy `postgres` network alias remains available for clients started outside Compose.

| Command | What starts |
|---------|-------------|
| `docker compose up -d` | Citus coordinator, two workers and Redis |
| `PGADMIN_PASSWORD="$(openssl rand -hex 24)" docker compose --profile db-ui up -d` | Infrastructure and pgAdmin 4 |
| `docker compose --profile app up -d` | Infrastructure and the `rcas` application |
| `make build && make monitoring-up` | Build and start the application and full monitoring stack |

`rcas` belongs to the `app` profile, so it is **not** started by default. This lets you run the dependencies in Docker and start the service yourself from the IDE.

To browse or execute SQL against the local database, start the `db-ui` profile with the command above and open <http://localhost:8081>. pgAdmin runs in local desktop mode without a web login; never expose this profile outside a trusted local machine. The random `PGADMIN_PASSWORD` is only a bootstrap requirement, not a password you need to remember. The UI port is bound to localhost only.

Expand **Servers → RCAS Citus Coordinator**, then open **Databases → testdb → Schemas → rcas → Tables**. The server connection is provisioned automatically; its host is `postgres-coordinator`, port `5432`, username `test`, and database `testdb`. Right-click the database and select **Query Tool** to execute SQL. pgAdmin settings persist in the `pgadmin-data` volume; `docker compose --profile db-ui down -v` removes that volume along with other stack volumes.

Stop everything (the `--profile app` flag is needed to also stop the service):

```bash
docker compose --profile app down        # stop and remove containers and network
docker compose --profile app down -v     # also remove volumes
```

### Option 1: everything in Docker

The image copies the jar from `build/libs`, so build it first:

```bash
./gradlew bootJar
docker compose --profile app up -d --build
```

### Option 2: dependencies in Docker, service from the IDE

```bash
docker compose up -d
```

Then run `com.gbp.rcas.RcasApplication` from the IDE (or `./gradlew bootRun`) with the Spring profile `dev`:

```bash
SPRING_PROFILES_ACTIVE=dev ./gradlew bootRun
```

The `dev` profile connects to PostgreSQL on `127.0.0.1:5432` (`testdb`, user and password `test`) and Redis on `localhost:6379`. Both ports are published by Compose.

## Published release images

Each stable release publishes the same multi-architecture image digest to `ghcr.io/martinslavov/rcas:vX.Y.Z` and `docker.io/martinslavov/rcas:vX.Y.Z`. Both registries' `latest` aliases point to the greatest stable SemVer release (numeric ordering), so rerunning an older release never moves either alias backwards. The release notes begin with both pull commands, the shared digest and links to both package pages. The workflow retains images for the newest two stable releases; older Docker Hub tags and GHCR image versions are deleted before their GitHub releases and Git tags. Historical releases can be backfilled by running **CI Release** with `workflow_dispatch` and an existing strict `vX.Y.Z` tag. After Docker Hub publishing is configured, backfill `v0.1.0` and `v0.1.1` to publish the historical images and update their release notes.

For example, start PostgreSQL and Redis from the Compose configuration, then run a published image on its network:

```bash
docker compose up -d
docker pull ghcr.io/martinslavov/rcas:v0.1.0
# Or use the matching Docker Hub image:
docker pull docker.io/martinslavov/rcas:v0.1.0
docker run --rm --name rcas --network rcas-docker-network -p 8080:8080 \
  -e SPRING_PROFILES_ACTIVE=dev \
  -e SPRING_R2DBC_URL=r2dbc:postgresql://postgres:5432/testdb \
  -e SPRING_R2DBC_USERNAME=test -e SPRING_R2DBC_PASSWORD=test \
  -e SPRING_DATA_REDIS_HOST=redis -e SPRING_DATA_REDIS_PORT=6379 \
  ghcr.io/martinslavov/rcas:v0.1.0
```

Then visit <http://localhost:8080/app/actuator/health>. `docker pull ghcr.io/martinslavov/rcas:latest` or `docker pull docker.io/martinslavov/rcas:latest` selects the newest stable release. The GHCR package and Docker Hub repository may initially be private: the owner must make each public in its registry settings for anonymous pulls. Release publication links the GHCR package to this repository through its OCI source label.

## Docker services

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `postgres-coordinator` | `citusdata/citus:13.2.0-pg15` | 5432 | Citus coordinator; initializes the `rcas` schema and registers both worker nodes |
| `postgresql-node1`, `postgresql-node2` | `citusdata/citus:13.2.0-pg15` | internal 5432 | Citus worker nodes storing distributed shards |
| `pgadmin` | `dpage/pgadmin4:9.19` | 8081 | profile `db-ui`; localhost-only pgAdmin 4 with a provisioned RCAS connection |
| `redis` | `redis:7` | 6379 | |
| `rcas` | built from `Dockerfile` | 8080 | profile `app` |

All containers share the `rcas-docker-network` network. The Compose project name is `rcas`. Coordinator and worker
volumes retain their existing names so changing service names does not discard local database data.

The Citus initializer runs at startup and updates existing Citus node metadata when worker service names change.
Do not use `docker compose down -v` unless you intend to delete local database data.

### Subscription partitioning and upgrades

New databases use four HASH partitions on `subscription.id`. This retains a database-enforced primary key on the
globally addressable ID, including support for foreign keys referencing that ID. The `user_id` lookup has an index on
each child, but cannot prune partitions. Four is an initial operational choice, not a performance guarantee; benchmark
representative data and plans before changing the modulus (repartitioning requires a planned rewrite).

PostgreSQL cannot enforce global `UNIQUE(type)` directly on an ID-partitioned table. The unpartitioned
`subscription_type_registry` has a unique type and ID; an AFTER row trigger maintains it and deferred foreign keys in
both directions enforce a matching pair at commit. Concurrent duplicate types fail with a unique violation. Keep the
trigger and both foreign keys enabled; do not write directly to children, disable triggers/constraints, detach partitions,
or modify the registry outside a controlled maintenance operation. `TRUNCATE subscription ... CASCADE` also truncates the
registry. `user_id` has no foreign key in the original schema; this upgrade does not add one or reject existing orphans.

**Existing databases:** Compose initialization is not a migration runner. Rehearse on a restored backup with the same
PostgreSQL version, schema, privileges, data volume and available disk space. Take and verify a restorable backup.
Inventory dependent views, foreign keys, custom indexes/constraints/triggers, grants, ownership, publications, policies,
and any other objects or clients bound to the old table; adapt and independently review the migration for such deployments.
The supplied migration rejects several common dependencies rather than silently leaving them on the old table. It expects
the original `subscription_id_seq` owned by `subscription.id` in the current schema. Audit ID/type duplicates, nulls,
sequence state and optional user orphans. Stop all application/read/write/sequence clients and scheduled jobs, clear or
restart caches, and keep the write freeze until validation finishes. Estimate lock/copy time and space for both copies and
indexes; set an appropriate maintenance window and lock/statement timeouts for the environment.

Apply **once**, as the schema owner, with `ON_ERROR_STOP`, against the original unpartitioned table:

```bash
docker compose exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 < db.migration/V4__PartitionSubscription.sql
```

The transactional migration locks the table, checks legacy data and supported dependencies, creates and fills the
partitioned table and registry, checks the copy, transfers sequence ownership without lowering its high-water mark, and
retains `subscription_legacy`. On error the DDL and data copy roll back; sequence `setval` is not transactional, but is
only advanced, never lowered. Verify counts, full row equality, registry equality, constraints, sequence ownership and
next ID, permissions and representative ID/user queries before resuming. Refresh planner statistics (`ANALYZE
subscription`) and restart/clear caches. Retain the old table and backup until validation and the agreed rollback window
end; then drop the old table only after confirming the authoritative new data and backup.

**Rollback:** Before new writes, the retained old rows can be restored by reversing the swap. After any new writes, the
old table is stale: stop all clients and freeze writes again, back up the authoritative partitioned table, and copy its
complete current contents into the legacy table under lock before swapping. Validate types/IDs, counts and sequence state;
never simply rename a stale copy. For the uncustomized schema, perform the following in one transaction while frozen,
after first validating on a restored copy:

```sql
BEGIN;
LOCK TABLE subscription, subscription_legacy IN ACCESS EXCLUSIVE MODE;
TRUNCATE subscription_legacy;
INSERT INTO subscription_legacy (id, type, active, user_id)
    SELECT id, type, active, user_id FROM subscription;
ALTER SEQUENCE subscription_id_seq OWNED BY subscription_legacy.id;
ALTER TABLE subscription_legacy ALTER COLUMN id SET DEFAULT nextval('subscription_id_seq');
SELECT setval('subscription_id_seq', GREATEST((SELECT last_value FROM subscription_id_seq), max(id)), true)
    FROM subscription_legacy HAVING max(id) IS NOT NULL AND max(id) >= (SELECT last_value FROM subscription_id_seq);
DROP TABLE subscription CASCADE;
DROP TABLE subscription_type_registry;
DROP FUNCTION sync_subscription_type_registry();
ALTER TABLE subscription_legacy RENAME TO subscription;
COMMIT;
```

Check row equality before the DROP, and check constraints, generated IDs and permissions before releasing the freeze;
rollback of a customized deployment requires a separately rehearsed dependency/privilege plan. If the retained table is
gone, restore from backup and reconcile all writes since the backup instead.

**Operations:** Monitor per-child size, index bloat, autovacuum and analyze activity, as well
as parent statistics and query plans; each child needs vacuum/analyze and index maintenance. HASH does not provide
time-based detach/drop retention, and more partitions increase catalog/planning overhead. Monitor the registry as a
central write/uniqueness bottleneck. Adding user foreign keys, partition rebalancing, retention policy and automated
migrations are follow-up work, not part of this upgrade.

### Daily user partitions

Fresh databases partition `user_t` by the timestamp column `created_on`. The startup SQL creates three daily
`user_t_YYYYMMDD` partitions and seeds users on those three dates. The optional startup populator also uses three dates
for users `1000`–`1002`, retains existing rows and never lowers either ID sequence.

In the original PostgreSQL schema, `user_identity` enforces globally unique IDs, usernames and emails with an AFTER row
trigger and deferred foreign keys in both directions. The Citus development schema below uses reference tables instead
and does not carry over those synchronization triggers or reverse foreign keys. The application still looks up users by
ID; a non-unique ID index on each partition supports those lookups, but an ID-only query cannot prune date partitions.
PostgreSQL no longer accepts new foreign keys referencing only `user_t.id`; any future reference must be designed
against the registry or the composite key.

Provision additional days before inserting their records:

```sql
SELECT rcas.ensure_user_day_partition(CURRENT_DATE + 1);
```

Dates without a dedicated partition route to `user_t_default`. Creating a partition fails explicitly if that day's rows
already exist in the default partition; move them under a separately planned write freeze before retrying.
Partition creation is explicit, not a daily scheduler. The original PostgreSQL migration applies user autovacuum
settings to new partitions; the Citus Compose schema does not apply the migration's per-table tuning.

### Citus stack

The main Compose stack runs PostgreSQL 15 with Citus 13.2.0: `postgres-coordinator` coordinates
`postgresql-node1` and `postgresql-node2`. It preserves the daily
range partitions of `user_t` by `created_on` while hash-distributing users by `id`; subscriptions are hash-partitioned
by `id` and distributed by `user_id` in the same colocation group as users. Small registry tables are replicated Citus
reference tables for globally unique user IDs, usernames, emails, subscription IDs and types. This is a local
development prototype, not a production-ready migration: the existing registry synchronization triggers and reverse
foreign keys are not carried over, so avoid writes that depend on those guarantees.
The cluster uses PostgreSQL `trust` authentication for worker communication on the private local Compose network;
the coordinator's published port is bound to localhost. Do not expose this configuration outside local development.

Build the RCAS image and start the main stack with monitoring:

```bash
make build && make monitoring-up
```

The app is at <http://localhost:8080/app/actuator/health>, Grafana at <http://localhost:3000>, Prometheus at
<http://localhost:9090>, and the Citus coordinator is published on port `5432`. Redis and the monitoring services use
their normal ports and `rcas-docker-network`. In Docker Desktop, the coordinator and both workers appear as services
in the same Compose project. The Postgres exporter scrapes the Citus coordinator; worker-specific PostgreSQL metrics
are not included.

To run the SQL feasibility test against the main stack, use `make citus-daily-partition-test`; it exercises creating a new daily
partition after distribution and checks reference-table uniqueness and user/subscription colocation. An ID-only user
lookup routes to one worker but scans that worker's daily partitions; a `created_on` predicate prunes the partitions.

Stop the stack and remove its local database data with:

```bash
make citus-down
```

**Existing databases:** Compose initializes the Citus schema only on a fresh coordinator/worker volume. Do not expect
restarting Compose to migrate an existing PostgreSQL database or copy its data into Citus. For disposable local data,
recreating the Citus volumes initializes the schema but deletes all database data. Keeping existing user data requires a
separately reviewed migration and rollback plan covering references, registry validation, sequences, grants and caches.
The Citus initializer rejects older distributed tables whose shard-key ID columns lack sequence defaults; Citus cannot
apply those defaults to an already-distributed shard key. Back up any data before recreating such local volumes.
The PostgreSQL migration and test-support scripts remain available for Testcontainers. Compose startup uses the Citus
initializer, while `make startup-service-records-populator` and `make performance-vacuum-database` use Citus-specific
scripts; the PostgreSQL versions remain unchanged for Testcontainers.

## Monitoring (profile `monitoring`)

An optional monitoring stack is available in the `monitoring` Compose profile. It is not started by `docker compose up`, `make up` or CI.

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `otel-collector` | `otel/opentelemetry-collector:0.116.1` | 4317 (gRPC), 4318 (HTTP) | receives OTLP; logs go to Loki, traces to the collector log (`debug` exporter) |
| `prometheus` | `prom/prometheus:v3.0.1` | 9090 | scrapes `rcas:8080/app/actuator/prometheus` and the collector |
| `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.15.0` | 9187 | exposes PostgreSQL vacuum, dead tuple, bloat ratio and long-transaction metrics via custom queries |
| `loki` | `grafana/loki:3.3.2` | 3100 | log storage (OTLP ingestion on `/otlp`) |
| `grafana` | `grafana/grafana:11.4.0` | 3000 | provisioned Prometheus and Loki datasources and dashboards (cache/database load plus PostgreSQL vacuum); anonymous admin access (local use only) |

```bash
make monitoring-up      # RCAS + dependencies + monitoring, OTLP export enabled in RCAS
make monitoring-down    # stop everything and remove volumes
```

To populate the running stack with additional predictable records for the user and subscription endpoints, run:

```bash
make build && make monitoring-up && make startup-service-records-populator
```

The populator adds users `1000`, `1001` and `1002` on three consecutive dates; user `1000` has subscriptions `1001`–`1003`, user `1001` has none,
and user `1002` has subscription `1004`. It is safe to run repeatedly and leaves existing rows unchanged. If you have
already requested these IDs before seeding, cached empty results may remain visible until the cache entries expire
(24 hours by default) or the service is restarted. Run the populator before testing the endpoints to avoid stale cache
entries.

To roll back the added records while keeping the rest of the database, delete subscriptions with the populator types and
their registry entries, then users and their identity entries (delete child rows first). For example:

```bash
docker compose exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 <<\SQL
BEGIN;
DELETE FROM rcas.subscription WHERE type IN ($p$populator-1001$p$, $p$populator-1002$p$, $p$populator-1003$p$, $p$populator-1004$p$);
DELETE FROM rcas.subscription_type_registry WHERE type IN ($p$populator-1001$p$, $p$populator-1002$p$, $p$populator-1003$p$, $p$populator-1004$p$);
DELETE FROM rcas.user_t WHERE username IN ($p$populator-user-1000$p$, $p$populator-user-1001$p$, $p$populator-user-1002$p$);
DELETE FROM rcas.user_identity WHERE username IN ($p$populator-user-1000$p$, $p$populator-user-1001$p$, $p$populator-user-1002$p$);
COMMIT;
SQL
```

Alternatively, `make monitoring-down` removes the development stack and its volumes, including all database data.

`make monitoring-up` passes `docker/monitoring/monitoring.env`, which switches RCAS to `log4j2-otel.yaml` (console plus the OpenTelemetry log appender) and enables OTLP trace and log export to the collector (traces are sampled at 100%). Without that file the OTLP export is off, so tests and the default stack need no collector. Configuration lives in `docker/monitoring/`.

Open the provisioned dashboards at <http://localhost:3000/d/rcas-cache-db-load/rcas-cache-database-load> (UID `rcas-cache-db-load`) and <http://localhost:3000/d/rcas-postgres-vacuum/rcas-postgresql-vacuum-monitoring> (UID `rcas-postgres-vacuum`). Grafana Explore is also available with datasource `Loki`, query `{service_name="rcas"}`, or `Prometheus`; Prometheus targets are at <http://localhost:9090/targets>. Dashboard JSON and provisioning are versioned under `docker/monitoring/grafana/provisioning/`, so Grafana re-creates dashboards when its container is replaced. The PostgreSQL vacuum dashboard includes top-level trends, dedicated panels for `subscription` and `user_t`, a firing-alert overview table, and timeline annotations from active PostgreSQL alerts. Prometheus also loads `docker/monitoring/prometheus-alerts.yml`, which defines vacuum/bloat alerts with operator actions.

### Cache and database metric semantics

The cache metrics use bounded `cache` (`cacheUser` / `cacheSubscription`), `operation` (`item` / `list`), `layer`, `outcome`, `source` and TTL `trigger` labels. They never include record IDs, raw request URLs, SQL or exception messages. The `application=rcas` common tag, scrape `job`, and `instance` labels are available as dashboard filters. HTTP request metrics group by Spring's templated `uri` route, not the request's raw path or IDs.

| Metric | What one observation represents |
|--------|---------------------------------|
| `rcas_cache_lookup_seconds_*` | One actual Caffeine lookup or Redis hash lookup plus deserialization. Outcomes are `hit`, `miss`, `error` or `cancelled`; a lookup error is never also a miss. Redis TTL work is excluded from lookup latency. |
| `rcas_database_read_seconds_*` | One repository publisher execution. A `Mono` with no row and a list read with no rows are `empty`. A `list` operation collects the repository `Flux` once, so it is one repository read regardless of row count. The metric counts repository calls, not every SQL statement. |
| `rcas_cache_logical_read_total` | One subscribed `CacheService` read. `source` is `caffeine`, `redis`, `database` or `none`; `outcome` is `success`, `empty`, `error` or `cancelled`. An empty cached/database list is an `empty` logical result with its actual cache/database source. A missing `Mono` result, error or cancellation is never counted as a successful served value. |
| `rcas_cache_write_seconds_*` | One Caffeine `put` or Redis serialization/hash write. Redis write errors remain visible even though the established cache-fallback behavior swallows them. |
| `rcas_cache_ttl_refresh_seconds_*` | One Redis `expire` operation, separately timed and tagged with trigger `caffeine_hit`, `redis_hit` or `write`. Even a Caffeine hit still refreshes Redis TTL; it does not perform a Redis lookup. Swallowed TTL errors remain visible. |
| `rcas_cache_redis_fallback_total` | A Redis lookup error followed by an actually invoked database retriever, not merely a Redis miss. |

These are different levels of work: one HTTP request can perform multiple logical cache reads, and each logical read can make zero or more cache-layer lookups plus at most one database repository read. The `/subscriptions/{ids}` HTTP route calls the item overload per ID, so those are separate `item` reads; a `list` read is one cached/repository list operation. The HTTP route panel counts requests by templated endpoint route. Three further panels show HTTP load by response status (`status` label of `http_server_requests_seconds_count`, actuator endpoints excluded): requests/second by status code, requests/second by status class (`SUCCESS`, `CLIENT_ERROR`, `SERVER_ERROR`) and the total per status code in the selected period. The two status-code panels prepopulate 200, 201, 204, 301, 302, 304, 400, 401, 403, 404, 500, 502 and 503 with zero while a matching target is up and exposing JVM metrics; other observed codes also appear. Dashboard hit ratios use only hits and misses; errors and cancellations are separate. A missing series/“No data” means the target or metric is unavailable, not zero traffic or a 100% hit ratio.

Timer histograms support average, p95 and p99. Caffeine's native `cache_size`, `cache_evictions_total` and cache hit/miss metrics are provided by Spring Boot's cache binder with Caffeine `recordStats`; the dashboard uses the custom lookup timers for layer ratios to avoid combining/double-counting native cache lookups.

### Reproducible read load

The dependency-free load driver uses `curl` against seeded, read-only user endpoints. From a cold local stack, reset and seed the development data, then run its defaults (100 requests per worker at concurrency 1 and 8, with a 0.5-second pause per request). Each phase lasts at least 50 seconds so multiple Prometheus scrapes capture each load level. **The reset command removes the local development database and Redis volumes; do not use it to reset a stack whose data you need to keep.**

```bash
make monitoring-down
make monitoring-up
make startup-service-records-populator
CONCURRENCY_LEVELS='1 8' REQUESTS_PER_WORKER=100 USER_IDS=1000,1001,1002 ./scripts/load-cache-db.sh
python3 scripts/check-monitoring-dashboard.py
```

To test the status-code PromQL queries, run `python3 scripts/test-monitoring-status-queries.py` with Docker available. It uses the `prom/prometheus:v3.0.1` image.

The first request for each seeded ID on a fresh stack sees Caffeine/Redis misses and a database read; subsequent reads become warm. Run the same command again without restarting to inspect warm Caffeine behavior. To isolate Redis hits with an empty Caffeine tier, restart only the app (Redis and PostgreSQL stay running) and immediately run the script:

```bash
docker compose --profile app restart rcas
CONCURRENCY_LEVELS='1 8' REQUESTS_PER_WORKER=100 USER_IDS=1000,1001,1002 ./scripts/load-cache-db.sh
```

The first worker at concurrency 1 reads Redis and promotes results to Caffeine; remaining requests exercise the warm tier. Prometheus scrapes every 15 seconds, so allow a scrape interval before inspecting the graphs. The helper accepts `BASE_URL`, `USER_IDS`, `CONCURRENCY_LEVELS`, `REQUESTS_PER_WORKER` and `REQUEST_DELAY` overrides; it does not write or seed application data.

## Database vacuum maintenance

RCAS uses PostgreSQL autovacuum as the primary cleanup strategy. The stack includes:

- global defaults in the `postgres` service command (`docker-compose.yml`)
- table-level overrides for high-churn tables in `db.migration/V4__AutovacuumTuning.sql`
- Prometheus alerting rules in `docker/monitoring/prometheus-alerts.yml`
- PostgreSQL metrics exported via `docker/monitoring/postgres-exporter-queries.yml`

### Active vacuum strategy

- Keep routine cleanup automatic (`autovacuum_enabled=true`).
- Lower per-table scale factors for `user_t` and `subscription` so cleanup starts earlier than the global threshold.
- Monitor dead tuples and time since last autovacuum, then intervene with manual `VACUUM (ANALYZE)` only when alerts or trend data justify it.

### Configured parameters

Global PostgreSQL runtime settings:

| Parameter | Value |
|-----------|-------|
| `autovacuum_naptime` | `30s` |
| `autovacuum_vacuum_scale_factor` | `0.05` |
| `autovacuum_analyze_scale_factor` | `0.02` |
| `autovacuum_vacuum_cost_limit` | `400` |
| `autovacuum_vacuum_cost_delay` | `5ms` |
| `log_autovacuum_min_duration` | `250ms` |

Table-level overrides (from `V4__AutovacuumTuning.sql`):

| Table | Key settings |
|-------|--------------|
| `user_t` | `autovacuum_vacuum_threshold=50`, `autovacuum_vacuum_scale_factor=0.02`, `autovacuum_analyze_scale_factor=0.01`, `autovacuum_vacuum_cost_limit=800` |
| `subscription` | `autovacuum_vacuum_threshold=100`, `autovacuum_vacuum_scale_factor=0.02`, `autovacuum_analyze_scale_factor=0.01`, `autovacuum_vacuum_cost_limit=1200` |

### Manual `VACUUM (ANALYZE)` guidance

Run manual `VACUUM (ANALYZE)` for specific tables when one of these persists after normal load settles:

- dead tuple ratio remains high (`>20%`) with increasing dead tuple count
- autovacuum is stalled or delayed for long periods
- bloat trend worsens while query latency regresses

Example command:

```bash
docker compose exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 -c 'VACUUM (ANALYZE) rcas."subscription";'
```

Avoid `VACUUM FULL` in normal operations. It rewrites the whole table, requires stronger locking, and can block application traffic. Reserve it for controlled maintenance windows with rollback and recovery planning.

### Synthetic partition/vacuum workload (non-production)

With the monitoring stack and the new user schema initialized, run:

```bash
make performance-vacuum-database
make vacuum-snapshot OUT=build/reports/vacuum-after-workload.txt
```

`docker/citus/performance-vacuum-database.sql` inserts 30,000 synthetic users across three days, updates their
`last_login`, deletes every tenth row and runs `ANALYZE`. It does not execute `VACUUM` or disable autovacuum.
Re-running it replenishes deleted synthetic users and creates more churn, leaving 27,000 synthetic users.
Use it only in disposable non-production databases. Autovacuum may clean dead tuples before a scrape; repeat the workload
and allow several 15-second Prometheus scrapes to observe trends in the PostgreSQL vacuum dashboard.
For manual before/after comparison, run `VACUUM (ANALYZE) rcas.user_t;` as a separate statement after the workload.

### Alert thresholds and operator actions

The default monitoring profile ships these alerts:

- `PostgresTableBloatGrowth`: dead tuple ratio `>20%` and dead tuples `>1000` for 15 minutes
- `PostgresAutovacuumStalled`: no autovacuum activity for over 2 hours (30-minute hold)
- `PostgresLongRunningTransaction`: longest open transaction `>900s` for 10 minutes
- `PostgresVacuumExecutionTooLong`: in-progress vacuum runtime over 30 minutes

Each rule includes operator actions in annotations (investigate blockers, coordinate session cancellation, and run targeted `VACUUM (ANALYZE)` when needed).

### Validation snapshots (non-production)

Capture before/after evidence from a local or staging stack with:

```bash
make monitoring-up
make vacuum-snapshot OUT=build/reports/vacuum-before.txt
# optional churn + manual maintenance step
docker compose exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 -c 'VACUUM (ANALYZE) rcas."subscription";'
make vacuum-snapshot OUT=build/reports/vacuum-after.txt
```

Issue #263 validation evidence and exact commands are tracked in `docs/db-vacuum-validation.md`.

## Configuring the JVM

The image is based on a hardened Temurin image that has no shell, so JVM options are passed through the `JDK_JAVA_OPTIONS` environment variable, which the `java` launcher reads itself. Separate multiple options with spaces:

```yaml
environment:
  JDK_JAVA_OPTIONS: "-XX:MaxRAMPercentage=75 -Dspring.profiles.active=prod"
```

Setting the variable replaces the default from the Dockerfile (`-XX:MaxRAMPercentage=75`), it does not append to it. Spring properties can also be set as environment variables, for example `SPRING_R2DBC_URL`.

## Health check

The image is single-stage on the hardened runtime (`dhi.io/eclipse-temurin:25`): no `RUN`, compiler, shell or `curl`, and it runs as `nonroot`.
The health check is a tiny Java class (`src/healthcheck/java/HealthCheck.java`, Gradle source set `healthcheck`) that `make build`
(`./gradlew bootJar healthCheckClass`, also part of `./gradlew build`) compiles to `build/healthcheck/HealthCheck.class`; the Dockerfile copies it next to the jar.

The Dockerfile defines `HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD ["java", "-cp", "/app", "HealthCheck"]`.
The class calls `http://127.0.0.1:8080/app/actuator/health` inside the container (an optional URL argument overrides it) and exits `0` only on HTTP 200,
with 2 s connect/read timeouts. The container becomes `unhealthy` after 3 consecutive failures once the 40 s start period is over.
`docker-compose.yml` reuses the image health check and only adds `start_interval: 2s` (with the same `start_period: 40s`, which Compose requires) so that `make up` turns `healthy` quickly.
`docker compose ps` shows `rcas` as `healthy` when it succeeds.

## Endpoints

All paths are under the `/app` base path.

| URL | Description |
|-----|-------------|
| `http://localhost:8080/app/user/{id}` | Get a user |
| `http://localhost:8080/app/user/{id}/subscription` | Get a user with the subscription |
| `http://localhost:8080/app/subscription/{id}` | Get a subscription |
| `http://localhost:8080/app/subscriptions/{ids}` | Get several subscriptions |
| `http://localhost:8080/app/actuator/health` | Health (includes PostgreSQL and Redis) |
| `http://localhost:8080/app/actuator/prometheus` | Prometheus metrics |
| `http://localhost:8080/app/swagger-ui-custom.html` | Swagger UI |
| `http://localhost:8080/app/v3/api-docs` | OpenAPI document |

The Docker database is seeded with three users (ids 1 to 3) and three subscriptions for user 1 (ids 1 to 3), so every endpoint returns data out of the box.

## Tests

```bash
./gradlew test
```

Integration tests start PostgreSQL through Testcontainers, so they need a running Docker daemon.

### Component tests

Component tests live in the separate Gradle subproject `component-tests`. They call the running service over HTTP, so they exercise the whole stack: the RCAS image, PostgreSQL and Redis. They do not depend on the application code and are not run by `./gradlew build` (it only compiles them).

```bash
make build             # build the jar used by the Docker image
make up                # build the image, start the stack and wait until it is healthy
make component-tests   # readiness check + deterministic DB/Redis reset + component test suite
make sanity-tests      # readiness check + deterministic DB/Redis reset + fast smoke tests (@Tag("sanity"))
make down              # stop the stack and remove containers, network and volumes
```

Both test targets reset PostgreSQL and Redis test data and restart RCAS before execution, so each run starts from the same
baseline and does not inherit stale cache state from earlier runs.

Set `RCAS_BASE_URL` to test a service running somewhere else. `make logs` prints the container logs.

### Logging

RCAS logs only to the console (stdout), so the container runtime collects the logs; no log files are written. Use `make logs` or `docker compose --profile app logs rcas` to read them.

#### Measuring execution time

Annotate a public method of a Spring bean with `@MeasureExecutionTime` (`com.gbp.rcas.aop`) to log `Class.method executed in N ms (success|error|cancelled)` at `INFO`. For `Mono`/`Flux` results the time runs from subscription to termination; other methods are timed synchronously. Arguments and results are never logged, and exceptions propagate unchanged. Only calls through the Spring proxy are measured (not self-invocation).

Both public `CacheServiceImpl.getCache` overloads (single item and list) use it, so every subscribed and terminated cache read logs one `CacheServiceImpl.getCache executed in N ms (...)` entry at `INFO`.

## CI/CD (GitHub Actions)

Workflows live in `.github/workflows`:

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci-unit-tests.yml` (CI Unit Tests) | pull request, push to `main`, manual | `./gradlew build` on JDK 25: compiles, runs unit and integration tests, uploads the test report and the JaCoCo `coverage-report`; `check` fails when LINE or BRANCH coverage drops below the minimums in `build.gradle` (45 % / 15 %; run `./gradlew jacocoTestReport`, report in `build/reports/jacoco/test/`) |
| `ci-component-tests.yml` (CI Component Tests) | pull request, push to `main`, manual | Builds the image, starts the stack with docker compose (`make up`), runs the component tests, collects the logs and tears everything down (`make down`) |
| `ci-sanity-tests.yml` (CI Sanity Tests) | pull request, push to `main`, manual | Starts the stack with docker compose and runs only the fast sanity tests (`make sanity-tests`) |
| `ci-static-review.yml` (CI Static Review) | pull request | Automatic static code review with Checkstyle (`.github/checkstyle/checkstyle.xml`, derived from `.github/docs/code-review-guidelines.md`); run locally with `./gradlew checkstyleMain checkstyleTest` |
| `ci-dependency-review.yml` (CI Dependency Review) | pull request | `dependency-review` job: fails the PR when it adds dependencies with known high or critical vulnerabilities |
| `ci-secret-scan.yml` (CI Secret Scan) | pull request, push to `main` | `secret-scan` job: gitleaks over the full history (`.gitleaks.toml`, allowlist entries need a documented reason) |
| `ci-tag.yml` (CI Tag) | merged PR into `main`; push fallback for fork PRs | Plans the tag in a read-only job from the `major` / `enhancement` labels, creates it in a minimal write job without checkout, then calls CI Release |
| `ci-release.yml` (CI Release) | push of a tag `v*`, reusable workflow call, manual backfill | Builds/tests the selected tag, publishes or verifies the same image digest in GHCR and Docker Hub before release creation, puts both pull commands and links at the top of release notes, advances both `latest` aliases to the highest stable SemVer, and prunes images before the two-release retention cleanup |
| `ci-artifact-roundtrip.yml` (CI Artifact Round Trip) | pull request changing `ci-release.yml` or this workflow, manual | Side-effect-free check of the CI Release `release-image-context` artifact contract: packs a generated fixture like the release `build` job, uploads it with the same pinned `upload-artifact`, downloads it with the same pinned `download-artifact` into `$RUNNER_TEMP/release-image-context`, restores it with the release `tar -xzf` command and verifies the path, listing, content and SHA-256 digests. Runs with `permissions: {}` and no secrets; never calls CI Release, uses tags, logs in to registries, publishes, edits releases or prunes |
| `ci-code-review.yml` (CodeQL) | pull request and push to `main`, weekly | Static security analysis, results appear in the Security tab |
| `ci-pr-issue-tracking.yml` (PR Issue Tracking) | pull request opened | Creates one tracking issue per PR (found again by a hidden marker, so it is never duplicated) and links it in a PR comment |
| `ci-agent-dispatch.yml` (Copilot Agent Dispatch) | `cloud-agent` label, architecture approval, agent status changes, failed required checks, every five minutes | Assigns the next repository custom agent to Copilot cloud agent through the GitHub API |
| `ci-agent-auto-merge.yml` (Agent PR Auto Merge) | agent status/check changes, PR comments/reviews, every five minutes | Merges only cloud-agent PRs with all required checks and agent statuses successful on the current head, no human PR comments/reviews, and no `needs-human-review` label |
| `.github/scripts/local_agent_worker.py` | Manually started; polls issues labeled `local-agent` | Runs local Copilot CLI agents in isolated worktrees, creates PRs, performs review/QA/CI gates and merges only when all checks pass |

Releases are created automatically for merged PRs into `main`: add the `major` label for a major bump or `enhancement` for a minor bump; otherwise the version receives a patch bump. The first automatic release is `v0.1.0`. A commit already carrying a stable `vX.Y.Z` tag is not tagged again. Fork PR merges are handled by a `main` push fallback that verifies the commit belongs to a merged PR from a fork. The mutating jobs (CI Tag `tag` and CI Release `publish`, `dockerhub`, `release`, `latest`, `dockerhub-latest` and `prune`) share one job-level concurrency group `release-tag` with `queue: max` and no cancellation, so automatic releases, image publication, latest alias movement and cleanup are serialized in one FIFO queue (pending jobs not replaced), and tag-reference creation retries against the latest tags to avoid losing a merge when concurrent releases choose the same next version. Manual `v*` tag pushes still create releases and apply the two-release retention policy. The **CI Release** `workflow_dispatch` input is restricted by workflow validation to an existing strict stable `vX.Y.Z` tag for backfills. Retention and `latest` selection consider stable versions in numeric SemVer order:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Recommended repository settings:

- Settings → Actions → General → Workflow permissions: allow workflows to create issues and pull request comments (the PR Issue Tracking workflow also declares its permissions in the YAML).
- Branch protection / rulesets for `main`: `Main protection` currently requires `unit-tests`, `Component Tests (make up && make component-tests)`, `Sanity Tests (make up && make sanity-tests)`, `Static Review (checkstyle)`, `QA Agent`, `analyze` (CodeQL), `dependency-review`, `secret-scan` and `PR Review`. `PR Review` must succeed on the current head SHA before QA or merge. **No agent may merge unless every ruleset-required check and the agent statuses (`PR Review`, `QA Agent`) are successful on the current head SHA** (pending, skipped, unknown or failed means do not merge). `Definition of Done` is manual only, stays visible on the PR and is not a required check.
- Security: secret scanning, push protection, Dependabot alerts and security updates enabled. The `Branch naming` ruleset excludes `dependabot/**` so Dependabot can create its branches.
- Repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (read-only): used for Docker Hardened Images (`dhi.io`) pulls by CI Component Tests, CI Sanity Tests and the release image build. Add a separate `DOCKERHUB_PUSH_TOKEN` Docker Hub PAT with Read, Write & Delete permissions for release publication, `latest` and retention pruning; the workflow fails with an actionable error if it is missing. The owner must make the GHCR package and Docker Hub repository public for anonymous pulls, then manually backfill `v0.1.0` and `v0.1.1` through CI Release.
- `COPILOT_AGENT_TOKEN`: a user-to-server fine-grained token for Copilot issue assignment; configure it as a repository Actions secret with the permissions in [Agent automation](.github/docs/agent-automation.md). Copilot cloud agent must be enabled for the repository.
- Code scanning must be available for the repository to see the CodeQL results.

PRs from forks get a read-only token, so PR Issue Tracking cannot create issues for them.

See [Security and permissions](.github/docs/security.md) for per-workflow permissions, SHA pinning and Dependabot, fork PR behaviour, token scopes (`PROJECT_TOKEN`, read-only `DOCKERHUB_TOKEN`, and write/delete `DOCKERHUB_PUSH_TOKEN`) and per-agent permissions.

## Branch workflow

Commits (and pushes) from `main`/`master` are blocked by the versioned hooks in `.githooks`. Enable them once per clone and work in a branch:

```bash
git config core.hooksPath .githooks
git checkout -b feature/my-change
```

For real enforcement on GitHub also enable branch protection for `main` (see Settings → Rules).

## Agents and task workflow

Custom agents live in `.github/agents/`:

| Agent | Role |
|-------|------|
| `product-owner-agent` | Senior Product Owner: analyzes the input and creates a GitHub issue with acceptance criteria |
| `architect-agent` | Senior Software Architect: posts a design note or an auditable skip, and gates high-risk changes on explicit user approval |
| `senior-java-software-engineer` | Senior Java Software Engineer: implements and pushes the issue branch; PR creation is handled by the task coordinator, local worker or guarded cloud workflow |
| `pr-review-agent` | Independent PR Reviewer: reads the issue and full diff, posts severity-ranked findings and sets `PR Review`; never changes code |
| `senior-qa-engineer` | Senior QA Engineer: starts after current-head `PR Review` success, tests the PR, reports bugs and sets `QA Agent` |
| `dod-validator-agent` | Definition of Done Validator: **manual only** (no flow starts it; run it explicitly), maps every acceptance criterion to behaviour-verifying evidence, posts the AC → evidence table and sets `Definition of Done`; never changes code |

Reusable procedures such as `/create-pr-cloud` (commit → push → PR → PR Review → QA → merge; DoD is manual only and not run by the skill) live in `.github/skills/`; see [Skills](.github/docs/skills.md).

Give a task with `TASK-NAME:<name>` on the first line. Optional metadata lines are `DEVELOPMENT: low|medium|high` and
`TAG: cloud-agent,local-agent,skip-architect,skip-product-owner` (any supported subset; do not combine `cloud-agent` and
`local-agent`), followed by `DESCRIPTION: <description>` or
free-form description text. `DEVELOPMENT` becomes a `development:<level>` issue label. The Product Owner consumes the
metadata, creates the issue with the selected labels and keeps control lines out of the issue title/body. `skip-product-owner`
instead has the main agent create the task issue directly; `skip-architect` starts Engineer directly and explicitly bypasses
architecture comments and approval, including `architecture-approval-required`. With `cloud-agent`, the trusted cloud workflow
dispatches Architect unless `skip-architect` is set, then creates/reuses an eligible `feature/<issue>-<task-slug>` PR and
hands off to PR Review → QA → automatic merge. `local-agent` instead opts an owner-authored issue into the local worker below:
the current session reports the issue URL and stops after intake, regardless of the skip tags. The separately started worker
handles all later stages; it does not start automatically with the issue.
The five-minute cloud poll recovers a missed PR/intake. For backward compatibility,
a first-line TAG followed by the task-name line is still accepted. `LABEL:BACKLOG,TASK-NAME:<name>` also remains supported,
with optional metadata after the task name. See [Agent automation](.github/docs/agent-automation.md).

The interactive workflow for tasks without `local-agent` is Product Owner (unless `skip-product-owner`) → Architect (unless `skip-architect`) →
explicit user approval when required → Engineer → (cloud PR workflow for `cloud-agent` tasks or `/create-pr-cloud` manually) → PR Review → QA → merge → elapsed time recorded on the issue and PR
(`.github/scripts/post_task_elapsed.sh`). For architecture changes (new module/layer/component or cache
topology), database schema/migrations, messaging/Kafka, public HTTP API or security changes, the Architect applies
`architecture-approval-required`; the orchestrator must wait for the user's explicit approval recorded on the issue as
`<!-- architecture-approved -->` before the Engineer creates a branch or starts implementation, unless the user explicitly
selected `skip-architect`. The Engineer reads the design note before implementation unless that opt-out is present. Architect
skips only docs-only changes (per the QA definition below) or small changes that touch none of the listed risk areas,
configuration, dependencies, architecture or cache topology; every Architect skip has an issue comment with
`<!-- architect-skipped -->` and `skipped: <reason>`.

### Workflow orchestrator

Inspect or seed an issue state with `python3 .github/scripts/orchestrator.py state <issue>` or `python3 .github/scripts/orchestrator.py init <issue> --agent <id> [--state <state>]` (only when the issue has no record yet; `init` seeds only `backlog` or `todo` for any agent, including `human`, and refuses any other `--state` before any GitHub call; later states are reached only through `transition`, which enforces the owner and edge table). If a transition reports that projection failed, run `python3 .github/scripts/orchestrator.py reconcile <issue>`: it idempotently re-projects the canonical state to the single `state:*` label and the board Status without changing the record. Every workflow stage change goes through `python3 .github/scripts/orchestrator.py transition <issue> <to> --agent <id>` (add `--head-sha <sha>` for the current PR head or `--dry-run` to validate without writing); each agent uses its own id, and human-only transitions use `--agent human`. Rollout starts in report mode: report an orchestrator failure and do not bypass it silently. Migrating in-flight tasks to later states is out of scope for #101; it is a separate, human-performed rollout step to be designed later (for example, the remaining EPIC #107 work can add a verified migration).

The PR Review Agent independently reads the issue, the complete diff and surrounding code, then posts findings using severity
`blocker`, `major`, `minor` or `nit`, including file and line where known. Blocker/major findings fail `PR Review` and return the
PR to the engineer; minor/nit findings are reported but do not block QA. QA starts only after `PR Review` is `success` on the
current head SHA. The engineer sets `PR Review` and `QA Agent` to `pending` (plus the informational `Definition of Done`) immediately after opening the PR and after every
push. After each fix push, PR Review must succeed on the new head before QA resumes.

The DoD Validator is manual only: no workflow, orchestrator stage or agent starts it, and it is not a merge gate. When you run it explicitly, it reads the issue linked by `Closes #N`, maps every acceptance criterion
to concrete evidence (a test asserting the behaviour, not merely the existence of a class — e.g. cache expiry needs a test asserting
expiration after the TTL; for docs/process criteria a `file:line` or verified command output), posts the AC → evidence table
(`<!-- dod-validation sha:<head-sha> -->`, verdicts `met`/`weak`/`missing`) as a PR comment and sets `Definition of Done`
(`success` only if every criterion is `met`). The PR template has a matching "Acceptance criteria → evidence" section. A DoD failure
is reported to you and does not dispatch the Engineer.

Both review loops are bounded at five failure rounds. Each PR Review report includes `<!-- pr-review-round:N -->`; round numbers
are derived from all such PR comment markers, not agent memory. On round-5 failure the agent applies `needs-human-review`,
mentions `@martinslavov`, and stops. Only a human removing that label resumes automated work; markers remain the source of truth.
No agent commits or merges while the label is present. QA uses its own `<!-- qa-round:N -->` markers and the same human-review
stop. For issues labelled `architecture-approval-required`, PR Review also checks conformance to the approved design note (material
deviations are at least major), backward compatibility and, for schema changes, migration and rollback evidence. PR descriptions
must not claim review, QA or CI/check statuses (for example, "no review performed" or "QA pending"); commit statuses and check
runs are the source of truth. The test section may list only local commands actually run and their results; if none were run, leave it without test-result entries rather than adding prose about unrun tests.

CI fix attempts are a separate three-attempt loop tracked by `<!-- ci-fix-attempt:N -->` and
`<!-- ci-failure-signature:<check name>|<test id or normalized error> -->` in PR comments. The engineer reads the failed
check and its Actions log/test report, reproduces and re-runs locally before pushing; one `infra:` retry counts as an
attempt. If attempt 3 still fails or the same signature appears twice consecutively, the engineer applies
`needs-human-review` and mentions `@martinslavov` with the check, run URL, signature, count and log excerpt. No agent
commits or merges while the label is present; only a human removes it to resume, retaining the separate CI, QA and PR
Review markers. After resumption numeric limits are not reapplied, but a repeated CI signature still stops the loop.
Auto-merge requires all existing ruleset checks plus `PR Review` and `QA Agent` success on the current head SHA (`Definition of Done` is not required), no
`needs-human-review` label, and no human comments or unresolved blocker/major findings. `PR Review` is also a required check in the
`Main protection` ruleset. Rules are in `.github/copilot-instructions.md`.

### Task queue: Backlog and TODO

The RCAS Tracking board has the Status columns `Backlog`, `Assessment`, `Defining`, `TODO`, `In Progress` and `Done`.

| Input | Result |
|-------|--------|
| `TASK-NAME:<name>` then optional `DEVELOPMENT`/`TAG` metadata | Issue created in `TODO`; each TAG becomes an issue label, and `DEVELOPMENT` becomes `development:<level>` |
| `TASK-NAME:<name>` plus `TAG: cloud-agent` | Starts cloud automation: Architect then Engineer, unless `skip-architect` opts out; PR Review, QA and merge gates remain |
| `TASK-NAME:<name>` plus `TAG: local-agent` | Current session reports the issue URL and stops; the separately started worker handles local sessions, worktrees, PR Review, QA, CI and gated merge |
| `TAG: skip-product-owner,skip-architect` | Main agent creates the issue directly; the selected flow starts Engineer without Product Owner, Architect or architecture approval. With `local-agent`, the worker starts Engineer after handoff |
| `TASK-NAME:<name>` without TAG | Product Owner creates a TODO issue for the interactive local flow; no background worker starts |
| `/create-issue` | Product Owner creates a TODO issue only; no implementation starts, so you can finish it yourself later |
| `/create-pr-cloud` | Creates/reuses a task issue and PR; cloud automation runs review, QA, bounded fixes and gated automatic merge |
| `/create-pr-local` | Creates a PR without a task issue in a temporary linked worktree, carrying current tracked and untracked non-ignored edits into it; the local session runs PR Review and QA, then merges when all gates pass. Failures stop for human action |
| `LABEL:BACKLOG,TASK-NAME:<name>` then optional metadata | Issue created in `Backlog`; `backlog` and any parsed metadata labels are set |

#### Comparing task tags

These examples use the same task description and `DEVELOPMENT: medium`; the development level adds the `development:medium`
issue label but does not choose the execution flow.

| Input tag | Issue creation | Execution |
|------------|----------------|-----------|
| `TAG: local-agent` | Product Owner creates the issue with `local-agent`. | The local worker picks it up when running. It works in an isolated worktree and proceeds through PR, review, QA, CI and gated merge. The issue must be owner-authored. |
| `TAG: local-agent,skip-architect,skip-product-owner` | The current session creates the issue directly, reports its URL and stops. | The separately started local worker runs Engineer without Architect or architecture approval, then PR Review, QA, CI and gated merge. |
| `TAG: cloud-agent` | Product Owner creates the issue with `cloud-agent`. | GitHub Actions starts the cloud flow: Architect, then Engineer, followed by PR Review, QA, CI and automatic merge when all required gates pass. |
| `TAG: cloud-agent,skip-architect,skip-product-owner` | The main agent creates the issue directly with the supplied labels; Product Owner is skipped. | The cloud flow starts Engineer directly without Architect or architecture approval. PR Review, QA, CI and merge gates still apply. |

To start a backlog task without a state record, first seed it with `orchestrator.py init <issue> --state backlog --agent human`,
then use `orchestrator.py transition <issue> todo --agent human`; it updates the board and removes the legacy `backlog` label.
A board change cannot wake up the local Copilot session, so TODO items are picked up oldest first
after every merged task, or when you ask (for example `RUN-QUEUE`). Agents change stages only through the orchestrator;
its board projection moves active implementation/review work to `In Progress` and merge to `Done`.

EPICs (label `epic`) group related sub-issues; they stay `In Progress`, are never processed from the queue themselves and are
closed when all their sub-issues are done. The roadmap (five levels, the Level 1 Workflow Orchestrator and the features
deferred because of the GitHub Free / Copilot Free plan) is in [`.github/docs/roadmap.md`](.github/docs/roadmap.md). Each
of the five roadmap improvement tasks is one EPIC; parts that need a paid plan are `Backlog` issues labelled `requires-pro`
and listed, with order and prerequisites, in [`.github/docs/pro-plan.md`](.github/docs/pro-plan.md).

```bash
.github/scripts/task_queue.sh list                         # open TODO issues, oldest first
python3 .github/scripts/orchestrator.py init 96 --state todo --agent human # seed an existing issue without a record
python3 .github/scripts/orchestrator.py transition 96 architecture --agent architect-agent
```

### Local autonomous worker

The local worker requires the Copilot CLI and `gh` authenticated as `@martinslavov`. It runs only for issues authored by the
repository owner and explicitly labeled `local-agent`; it never processes `cloud-agent`, `backlog`, `requires-pro` or
`needs-human-review` issues. Start it manually from a clean, up-to-date `main` checkout:

```bash
python3 .github/scripts/local_agent_worker.py                 # poll every 60s; Ctrl+C stops it
python3 .github/scripts/local_agent_worker.py --once          # process up to one issue, then exit
python3 .github/scripts/local_agent_worker.py --workers 2     # allow two separate issue worktrees concurrently
```

Each issue and stage uses a named Copilot CLI session and an isolated `../rcas-sessions/issue-<number>-<slug>` worktree.
Copilot does not run while the queue is empty; model usage begins only when an eligible issue is picked up. The worker uses
non-interactive `--allow-all-tools`, so the label is explicit authorization to run trusted issue content with repository
tools. Architecture approval, CI, PR Review, QA, human comments, and `needs-human-review` are merge gates. A stopped task
gets `local-agent-failed`; inspect the terminal and remove that label to retry. Local failures never silently bypass the
orchestrator. If `needs-human-review` is also present, only a human may remove it; remove both labels when explicitly
resuming.

### Running agents without approval prompts

Approval prompts for file edits and shell commands come from the Copilot CLI/IDE, not from repository rules, so they
cannot be disabled in `.github/copilot-instructions.md`. To keep the agent workflow from waiting on you, start the CLI
with a scoped allow-list:

```bash
copilot --allow-tool='write' \
  --allow-tool='shell(git:*)' --allow-tool='shell(gh:*)' \
  --allow-tool='shell(make:*)' --allow-tool='shell(./gradlew:*)' \
  --allow-tool='shell(docker:*)' --allow-tool='shell(python3:*)' \
  --deny-tool='shell(git push --force)' --deny-tool='shell(rm -rf)'
```

Broader alternatives: `copilot --allow-all-tools` (all tools) or `copilot --yolo` (all tools, paths and URLs); inside a
running session use `/allow-all`, or answer a prompt with "Yes, and don't ask again". In the JetBrains Copilot plugin,
enable auto-approve under **Settings → Tools → GitHub Copilot → Chat** (agent auto-approve for file edits and terminal
commands). Check `copilot --help` for the flags of your version. The GitHub rulesets (required checks, no direct push to
`main`) remain the safety net when prompts are off.

### QA test scope and status

- A PR is docs-only only if every changed file matches `*.md`, `.github/agents/**`, `.github/copilot-instructions.md`, `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`, or `.github/ISSUE_TEMPLATE/**`. QA reviews the documentation and its consistency; tests are not required. Any other changed file means the PR is not docs-only.
- For any change under `src/**`, `component-tests/**`, `.github/checkstyle/**`, or `.github/scripts/**`, or to `build.gradle`, `settings.gradle`, `gradle/**`, `Dockerfile`, `docker-compose.yml`, `docker/**`, `Makefile`, `.github/workflows/**`, or `db.migration/**`, QA runs the relevant tests, at minimum `./gradlew build` with JDK 25.
- For runtime-affecting changes (application source or configuration, runtime dependencies or packaging, database migrations, or Docker/Compose runtime setup; including changes in `src/**`, `db.migration/**`, `Dockerfile`, `docker-compose.yml`, and `docker/**`), QA additionally runs `make build && make up && make component-tests && make sanity-tests && make down`.
- When in doubt, QA runs the tests.
- The `QA Agent` status description identifies the checks actually executed and their results, e.g. `docs-only review`, `build passed`, or `build+component+sanity passed`. It includes failures and never implies an unrun check passed.

By default the engineer merges with a merge commit and deletes the branch only after every ruleset-required check and all agent statuses
are successful on the current head SHA, the label is absent, and no human comments or unresolved blocker/major findings remain. Merging closes the task
issue (`Closes #N`) and the tracking issue and moves the board item to Done. A failing, pending or unknown check blocks the merge. Add
"leave the PR open" or "do not merge" to the task to keep the PR open.

## Task reports: elapsed time

At the end of every task the agent reports the total elapsed time from the user's input until everything is merged and all agents are done.
The main (orchestrating) agent records the start with `date +%s` at the beginning of the task and computes the difference at the end
(see `.github/copilot-instructions.md`).

After the merge the same time (start, end and total) is shown at the top of the task issue and PR descriptions
(an "Elapsed time" note) and recorded as a `<!-- task-elapsed -->` comment on both. Re-running updates both instead of
duplicating them:

```bash
.github/scripts/post_task_elapsed.sh <issue> <pr> <start-epoch> [end-epoch]
```


### Agent run records and dashboard

Each agent appends one versioned, secret-free `<!-- agent-run: {{...}} -->` JSON comment at the end of its run. The schema,
UTC timestamp requirements and failure-source definitions are in `.github/copilot-instructions.md`. The
`Agent Workflow Dashboard` (runs on every push to `main`, daily, and manually from `main`; never on `pull_request`/forks) aggregates issue/PR comments. Its single issue is explicit configuration: the repository Actions variable `AGENT_DASHBOARD_ISSUE` holds its issue number (the job fails with a clear error if unset; there is no fallback and the workflow never creates issues). The script updates (and reopens if closed) exactly that issue after verifying it starts with `<!-- agent-dashboard -->`. One-time bootstrap: `GH_TOKEN=... python3 .github/scripts/agent_dashboard.py --repo martinslavov/rcas --create`, then `gh variable set AGENT_DASHBOARD_ISSUE -b <number> -R martinslavov/rcas`. The dashboard issue is
excluded from the task board. If automatic pinning is denied, a repository owner pins the created dashboard once.
