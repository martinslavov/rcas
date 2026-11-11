COMPOSE ?= docker compose
HEALTH_TIMEOUT ?= 180

.PHONY: build up down logs component-tests sanity-tests monitoring-up monitoring-down startup-service-records-populator

## Build the artifacts used by the Docker image: the executable jar and the health check class (build/healthcheck)
build:
	./gradlew bootJar healthCheckClass -x test

## Start (requires `make build` first): build the image and start PostgreSQL, Redis and RCAS; waits until all containers are healthy
up:
	$(COMPOSE) --profile app up -d --build --wait --wait-timeout $(HEALTH_TIMEOUT)

## Stop the stack and remove containers, network and volumes
down:
	$(COMPOSE) --profile app down -v

## Print the logs of all containers
logs:
	$(COMPOSE) --profile app logs --no-color

## Run the component tests against the running stack
component-tests:
	./gradlew :component-tests:componentTest

## Run only the fast sanity (smoke) tests against the running stack
sanity-tests:
	./gradlew :component-tests:sanityTest

## Start the stack with the monitoring profile (OTel Collector, Prometheus, Loki, Grafana) and OTLP export enabled in RCAS
monitoring-up:
	$(COMPOSE) --env-file docker/monitoring/monitoring.env --profile app --profile monitoring up -d --build --wait --wait-timeout $(HEALTH_TIMEOUT)

## Stop the stack including the monitoring services and remove containers, network and volumes
monitoring-down:
	$(COMPOSE) --env-file docker/monitoring/monitoring.env --profile app --profile monitoring down -v

## Seed the running PostgreSQL database with the startup service records
startup-service-records-populator:
	COMPOSE="$(COMPOSE)" ./scripts/startup-service-records-populator.sh
