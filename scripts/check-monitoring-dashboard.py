#!/usr/bin/env python3
"""Validate the provisioned RCAS Grafana dashboard's identity, queries and datasource."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVISIONING = ROOT / "docker/monitoring/grafana/provisioning"
DASHBOARD_PATH = PROVISIONING / "dashboards/rcas-cache-db-load.json"

dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
assert dashboard["uid"] == "rcas-cache-db-load"
assert dashboard["title"] == "RCAS — Cache & Database Load"
assert dashboard["refresh"] == "15s"
assert dashboard["time"] == {"from": "now-1h", "to": "now"}

variables = {entry["name"] for entry in dashboard["templating"]["list"]}
assert variables == {"job", "application", "instance", "cache", "operation"}

panels = dashboard["panels"]
titles = {panel["title"] for panel in panels}
required_titles = {
    "HTTP requests / second by route",
    "Cache lookups / second by layer and outcome",
    "Database repository reads / second",
    "Logical reads / second by source and outcome",
    "Logical reads served by source (%)",
    "Cache hit ratio (hits / (hits + misses))",
    "Cache lookups — total in selected period",
    "Cache hits — total in selected period",
    "Cache misses — total in selected period",
    "Database reads — total in selected period",
    "Errors — total in selected period",
    "Redis lookup failures — total in selected period",
    "Cache lookup latency by layer — avg / p95 / p99",
    "Database read latency — avg / p95 / p99",
    "Cache writes / second",
    "Redis TTL refreshes / second",
    "Cache / database errors and Redis fallback",
    "Caffeine entries and evictions",
    "Target availability, process CPU, JVM heap",
    "Logical reads — total in selected period by source and outcome",
    "HTTP requests / second by status code",
    "HTTP requests / second by status class",
    "HTTP requests — total in selected period by status code",
}
assert required_titles <= titles, f"Missing panels: {required_titles - titles}"

queries = [
    target["expr"]
    for panel in panels
    for target in panel.get("targets", [])
]
assert all(panel["datasource"]["uid"] == "prometheus" for panel in panels)
assert any("http_server_requests_seconds_count" in query and "uri!~" in query for query in queries)
assert any("sum(rate(http_server_requests_seconds_count" in query for query in queries)
assert any("rate(" in query and "[$__rate_interval]" in query for query in queries)
assert any("increase(" in query and "[$__range]" in query for query in queries)
assert any("histogram_quantile(0.95" in query for query in queries)
assert any("histogram_quantile(0.99" in query for query in queries)
for title, grouping, window in (
    ("HTTP requests / second by status code", "sum by (status)", "rate("),
    ("HTTP requests / second by status class", "sum by (outcome)", "rate("),
    ("HTTP requests — total in selected period by status code", "sum by (status)", "increase("),
):
    status_query = next(panel["targets"][0]["expr"] for panel in panels if panel["title"] == title)
    assert grouping in status_query and window in status_query, title
    assert "http_server_requests_seconds_count" in status_query, title
    assert 'uri!~"/actuator.*"' in status_query, title
ratio_query = next(
    panel["targets"][0]["expr"] for panel in panels
    if panel["title"] == "Cache hit ratio (hits / (hits + misses))"
)
assert 'outcome="hit"' in ratio_query and 'outcome=~"hit|miss"' in ratio_query
assert "or (0 *" in ratio_query, "Miss-only caches must show a zero hit ratio, not no data"
error_query = next(
    panel["targets"][0]["expr"] for panel in panels
    if panel["title"] == "Errors — total in selected period"
)
assert "__name__=~" in error_query and " + " not in error_query
assert any("rcas_cache_redis_fallback_total" in query for query in queries)
assert any("cache_size" in query for query in queries)
assert any("cache_evictions_total" in query for query in queries)
assert not any("clamp" in query.lower() for query in queries)

datasources = (PROVISIONING / "datasources/datasources.yml").read_text(encoding="utf-8")
dashboard_provider = (PROVISIONING / "dashboards/dashboards.yml").read_text(encoding="utf-8")
assert "uid: prometheus" in datasources
assert "path: /etc/grafana/provisioning/dashboards" in dashboard_provider

print(f"Monitoring dashboard validation passed ({len(panels)} panels; datasource UID prometheus).")
