#!/usr/bin/env python3
"""Exercise the dashboard status queries using the project's Prometheus version."""

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "docker/monitoring/grafana/provisioning/dashboards/rcas-cache-db-load.json"
STATUSES = ("200", "201", "204", "301", "302", "304", "400", "401", "403", "404", "500", "502", "503")

dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
queries = [
    next(panel["targets"][0]["expr"] for panel in dashboard["panels"] if panel["id"] == panel_id)
    .replace("$job", "rcas")
    .replace("$application", "rcas")
    .replace("$instance", "rcas:8080")
    .replace("$__rate_interval", "2m")
    .replace("$__range", "2m")
    for panel_id in (21, 23)
]
up = 'up{job="rcas",instance="rcas:8080"}'
jvm = 'jvm_memory_used_bytes{job="rcas",application="rcas",instance="rcas:8080",area="heap"}'
http = 'http_server_requests_seconds_count{job="rcas",application="rcas",instance="rcas:8080"'


def expected(values):
    return [
        {"labels": f'{{status="{status}"}}', "value": values.get(status, 0)}
        for status in sorted(set(STATUSES) | values.keys())
    ]


tests = []
for query, values in zip(queries, ({"200": 1, "404": 0.5, "418": 2}, {"200": 120, "404": 60, "418": 240})):
    for series, output in (
        ([{"series": up, "values": "1+0x3"}, {"series": jvm, "values": "1+0x3"}], expected({})),
        ([
            {"series": up, "values": "1+0x3"},
            {"series": jvm, "values": "1+0x3"},
            {"series": http + ',status="200",uri="/users"}', "values": "0+60x3"},
            {"series": http + ',status="404",uri="/users"}', "values": "0+30x3"},
            {"series": http + ',status="418",uri="/users"}', "values": "0+120x3"},
            {"series": http + ',status="503",uri="/actuator/health"}', "values": "0+60x3"},
        ], expected(values)),
        ([{"series": up, "values": "0+0x3"}, {"series": jvm, "values": "1+0x3"}], []),
        ([{"series": up, "values": "1+0x3"}], []),
        ([
            {"series": up, "values": "1+0x3"},
            {"series": jvm.replace('application="rcas"', 'application="other"'), "values": "1+0x3"},
        ], []),
    ):
        tests.append({
            "interval": "1m",
            "input_series": series,
            "promql_expr_test": [{"expr": query, "eval_time": "3m", "exp_samples": output}],
        })

with tempfile.TemporaryDirectory(prefix="rcas-promql-") as directory:
    Path(directory).chmod(0o755)
    fixture = Path(directory) / "status-queries.json"
    fixture.write_text(json.dumps({"tests": tests}), encoding="utf-8")
    subprocess.run([
        "docker", "run", "--rm", "--entrypoint", "promtool",
        "-v", f"{directory}:/tests:ro", "prom/prometheus:v3.0.1",
        "test", "rules", "/tests/status-queries.json",
    ], check=True)
