#!/bin/bash
# Starts the two brewlog services with OpenTelemetry auto-instrumentation,
# exporting traces + metrics + logs over OTLP to local SigNoz.
set -euo pipefail
cd "$(dirname "$0")"

export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_TRACES_EXPORTER="otlp"
export OTEL_METRICS_EXPORTER="otlp"
export OTEL_LOGS_EXPORTER="otlp"
export OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED="true"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=hackathon"

OTEL_SERVICE_NAME=brew-machine ./.venv/bin/opentelemetry-instrument \
  ./.venv/bin/uvicorn app:app --port 8002 --log-level warning &
MACHINE_PID=$!

OTEL_SERVICE_NAME=brewlog-api ./.venv/bin/opentelemetry-instrument \
  ./.venv/bin/uvicorn app:app --port 8001 --log-level warning &
API_PID=$!

echo "brewlog-api pid=$API_PID (:8001), brew-machine pid=$MACHINE_PID (:8002)"
echo "stop with: kill $API_PID $MACHINE_PID"
wait
