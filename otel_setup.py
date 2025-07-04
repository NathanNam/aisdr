"""
OpenTelemetry setup for the AISDR Slack-bot.

* Tracing  → OTLP/HTTP  → Observe  (+ BatchSpanProcessor)
* Metrics  → Prometheus (local) + OTLP/HTTP  → Observe
* Logs     → OTLP/HTTP  → Observe
* Auto-instrumentation for Flask, requests, threading, logging
* Helper to create business-level custom metrics
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Optional, Tuple

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.resource import ResourceAttributes

# --------------------------------------------------------------------------- #
# Global log formatting
# --------------------------------------------------------------------------- #

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=(
        '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
        '"message":"%(message)s","trace_id":"%(otelTraceID)s","span_id":"%(otelSpanID)s"}'
    ),
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resource() -> Resource:
    """Return an OTEL resource populated with common attributes."""
    return Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "aisdr-bot"),
            ResourceAttributes.SERVICE_VERSION: os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.getenv(
                "OTEL_ENVIRONMENT", "production"
            ),
            ResourceAttributes.SERVICE_INSTANCE_ID: os.getenv("HOSTNAME", "unknown"),
            "service.team": "observability",
            "service.component": "slack-bot",
        }
    )


def _encode_header_value(value: str) -> str:
    """Return a spec-compliant, URL-encoded header value (spaces → %20, : → %3A …)."""
    return urllib.parse.quote(value, safe="")


def _build_otlp_headers(package_tag: str) -> dict[str, str]:
    """
    Construct the headers dict for OTLP exporters.

    Precedence:
    1. OTEL_EXPORTER_OTLP_HEADERS (JSON string, values may already be encoded)
    2. OTEL_EXPORTER_OTLP_AUTH_HEADER (single key=value, will be encoded if needed)
    3. OBSERVE_INGEST_TOKEN (plain Bearer token, always encoded here)
    """
    headers: dict[str, str] = {}

    # 1. Generic JSON headers
    if raw := os.getenv("OTEL_EXPORTER_OTLP_HEADERS"):
        try:
            headers.update(json.loads(raw))
        except json.JSONDecodeError as exc:
            logging.warning("Invalid OTEL_EXPORTER_OTLP_HEADERS JSON: %s", exc)

    # 2. Single auth header
    if kv := os.getenv("OTEL_EXPORTER_OTLP_AUTH_HEADER"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            headers[k.strip().title()] = urllib.parse.unquote(v.strip())
        else:
            logging.warning(
                "OTEL_EXPORTER_OTLP_AUTH_HEADER expected 'key=value', got %s", kv
            )

    # 3. Observe token shortcut
    if token := os.getenv("OBSERVE_INGEST_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    # ---- URL-encode every value NOW so Observe accepts it ----
    encoded = {k: _encode_header_value(v) for k, v in headers.items()}

    # Expose encoded form via the spec var (helps auto-instrument CLI users)
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = ",".join(f"{k}={v}" for k, v in encoded.items())

    # Tag every request so Observe routes it to the right “package”
    encoded["x-observe-target-package"] = package_tag
    return encoded


def _endpoint() -> str:
    return os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "https://191369360817.collect.observe-eng.com/v2/otel",
    )


# --------------------------------------------------------------------------- #
# Tracing / Metrics / Logging setup
# --------------------------------------------------------------------------- #


def _setup_tracing() -> trace.Tracer:
    tp = TracerProvider(resource=_resource())
    span_exporter = OTLPSpanExporter(
        endpoint=f"{_endpoint()}/traces", headers=_build_otlp_headers("Tracing")
    )
    tp.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tp)
    return trace.get_tracer(__name__)


def _setup_metrics() -> metrics.Meter:
    readers = [PrometheusMetricReader()]

    metric_exporter = OTLPMetricExporter(
        endpoint=f"{_endpoint()}/metrics",
        headers=_build_otlp_headers("Metrics"),
    )
    readers.append(
        PeriodicExportingMetricReader(exporter=metric_exporter, export_interval_millis=5000)
    )

    mp = MeterProvider(resource=_resource(), metric_readers=readers)
    metrics.set_meter_provider(mp)
    return metrics.get_meter(__name__)


def _setup_logging() -> None:
    LoggingInstrumentor().instrument(set_logging_format=True)

    lp = LoggerProvider(resource=_resource())
    log_exporter = OTLPLogExporter(
        endpoint=f"{_endpoint()}/logs",
        headers=_build_otlp_headers("Host Explorer"),
    )
    lp.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(lp)

    root = logging.getLogger()
    root.addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=lp))
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


# --------------------------------------------------------------------------- #
# Public API called from aisdr.py
# --------------------------------------------------------------------------- #

_tracer: Optional[trace.Tracer] = None
_meter: Optional[metrics.Meter] = None
_custom_metrics: Optional[dict] = None


def setup_observability(app) -> Tuple[trace.Tracer, metrics.Meter, dict]:
    """Bootstrap OTEL and auto-instrument the Flask app."""
    global _tracer, _meter, _custom_metrics

    _tracer = _setup_tracing()
    _meter = _setup_metrics()
    _setup_logging()

    # Auto-instrument libraries
    FlaskInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()
    ThreadingInstrumentor().instrument()
    logging.info("OpenTelemetry initialisation complete")

    _custom_metrics = _define_custom_metrics(_meter)
    return _tracer, _meter, _custom_metrics


def _define_custom_metrics(meter: metrics.Meter) -> dict:
    """Business-level counters & histograms."""
    return {
        "slack_events_total": meter.create_counter(
            "aisdr_slack_events_total", description="Slack events processed"
        ),
        "emails_generated_total": meter.create_counter(
            "aisdr_emails_generated_total", description="Cold emails generated"
        ),
        "openai_latency_seconds": meter.create_histogram(
            "aisdr_openai_request_duration_seconds", unit="s"
        ),
    }


# Convenience getters --------------------------------------------------------


def get_tracer() -> trace.Tracer:  # noqa: D401
    return _tracer if _tracer else trace.get_tracer(__name__)


def get_meter() -> metrics.Meter:  # noqa: D401
    return _meter if _meter else metrics.get_meter(__name__)


def get_custom_metrics() -> dict:  # noqa: D401
    return _custom_metrics or {}
