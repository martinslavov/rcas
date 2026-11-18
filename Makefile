COMPOSE ?= docker compose
HEALTH_TIMEOUT ?= 180

.PHONY: build up down logs verify-stack-ready reset-test-data component-tests sanity-tests monitoring-up monitoring-down startup-service-records-populator performance-vacuum-database vacuum-snapshot citus-up citus-daily-partition-test citus-down

## Build the artifacts used by the Docker image: the executable jar and the health check class (build/healthcheck)
build:
	./gradlew bootJar healthCheckClass -x test

## Start (requires `make build` first): start the Citus cluster, Redis and RCAS; wait until all containers are healthy
up:
	$(COMPOSE) --profile app up -d --build --wait --wait-timeout $(HEALTH_TIMEOUT)

## Stop the stack and remove containers, network and volumes
down:
	$(COMPOSE) --profile app down -v

## Print the logs of all containers
logs:
	$(COMPOSE) --profile app logs --no-color

## Wait until Citus/PostgreSQL, Redis and RCAS health endpoint are ready
verify-stack-ready:
	COMPOSE="$(COMPOSE)" ./scripts/wait-for-stack-ready.sh

## Reset PostgreSQL + Redis test data and restart RCAS to clear in-memory cache
reset-test-data:
	COMPOSE="$(COMPOSE)" ./scripts/reset-test-data.sh

## Run the component tests against the running stack
component-tests: verify-stack-ready reset-test-data
	./gradlew :component-tests:componentTest

## Run only the fast sanity (smoke) tests against the running stack
sanity-tests: verify-stack-ready reset-test-data
	./gradlew :component-tests:sanityTest

## Start the stack with the monitoring profile (OTel Collector, Prometheus, Loki, Grafana) and OTLP export enabled in RCAS
monitoring-up:
	$(COMPOSE) --env-file docker/monitoring/monitoring.env --profile app --profile monitoring up -d --build --wait --wait-timeout $(HEALTH_TIMEOUT)

## Stop the stack including the monitoring services and remove containers, network and volumes
monitoring-down:
	$(COMPOSE) --env-file docker/monitoring/monitoring.env --profile app --profile monitoring down -v

## Seed the running PostgreSQL database with the startup service records
startup-service-records-populator:
	COMPOSE="$(COMPOSE)" ./scripts/startup-citus-service-records-populator.sh

## Add synthetic write churn for local PostgreSQL vacuum/partition analysis
performance-vacuum-database:
	$(COMPOSE) exec -T postgres-coordinator psql -U test -d testdb -v ON_ERROR_STOP=1 < docker/citus/performance-vacuum-database.sql

## Capture a PostgreSQL vacuum/autovacuum snapshot from the running stack (optional OUT=path)
vacuum-snapshot:
	COMPOSE="$(COMPOSE)" ./scripts/vacuum-monitoring-snapshot.sh "$(OUT)"

## Build RCAS and start the Citus + Redis + monitoring stack in the main Compose project
citus-up: build
	$(COMPOSE) --profile app --profile monitoring up -d --build --wait --wait-timeout $(HEALTH_TIMEOUT)

## Run the Citus daily-user-partition proof of concept
citus-daily-partition-test:
	$(COMPOSE) --profile test run --rm citus-test

## Stop the Citus stack and remove its local data
citus-down:
	$(COMPOSE) --profile app --profile monitoring down -v
