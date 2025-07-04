"""
OpenTelemetry Setup and Configuration

This module provides comprehensive OpenTelemetry instrumentation setup for the AISDR application.
It configures tracing, metrics, and logging with minimal code changes to the main application.
"""

import os
import json
import logging
from typing import Optional
from urllib.parse import quote, unquote

from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry._logs import set_logger_provider

# Configure structured logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s", "trace_id": "%(otelTraceID)s", "span_id": "%(otelSpanID)s"}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

def get_resource() -> Resource:
    """Create OpenTelemetry resource with comprehensive attributes."""
    return Resource.create({
        ResourceAttributes.SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "aisdr-bot"),
        ResourceAttributes.SERVICE_VERSION: os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: os.getenv("OTEL_ENVIRONMENT", "production"),
        ResourceAttributes.SERVICE_INSTANCE_ID: os.getenv("HOSTNAME", "unknown"),
        "service.team": "observability",
        "service.component": "slack-bot"
    })

def get_otlp_headers(package: str) -> dict:
    """Parse OTLP headers and ensure correct target package.

    Supports the following environment variables:
    - ``OTEL_EXPORTER_OTLP_HEADERS`` as a JSON object (existing behaviour)
    - ``OTEL_EXPORTER_OTLP_AUTH_HEADER`` as ``key=value`` where the value may
      be unencoded. The value is URL encoded automatically for the exporter.
    """

    otlp_headers: dict = {}

    headers_json = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
    if headers_json:
        try:
            otlp_headers.update(json.loads(headers_json))
        except json.JSONDecodeError as e:
            logging.warning(f"Invalid OTEL_EXPORTER_OTLP_HEADERS: {e}")

    auth_header = os.getenv("OTEL_EXPORTER_OTLP_AUTH_HEADER")
    if auth_header:
        if "=" in auth_header:
            key, value = auth_header.split("=", 1)
            key = key.strip().title()
            value = value.strip()
            if "%" in value:
                value = unquote(value)
            otlp_headers[key] = value

            # Expose encoded form for other tools expecting OTEL spec format
            os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"{key}={quote(value, safe='')}"
        else:
            logging.warning(
                "Invalid OTEL_EXPORTER_OTLP_AUTH_HEADER format, expected 'key=value'"
            )

    if not otlp_headers:
        otlp_headers = {"Authorization": "Bearer <YOUR_INGEST_TOKEN>"}

    observe_token = os.getenv("OBSERVE_INGEST_TOKEN")
    if observe_token:
        if "Authorization" in otlp_headers and otlp_headers["Authorization"] != f"Bearer {observe_token}":
            logging.info(
                "OBSERVE_INGEST_TOKEN overrides Authorization header defined by other variables"
            )
        otlp_headers["Authorization"] = f"Bearer {observe_token}"

    otlp_headers["x-observe-target-package"] = package

    masked_headers = {
        k: ("<masked>" if k.lower() == "authorization" else v)
        for k, v in otlp_headers.items()
    }
    logging.info("OTLP headers for %s: %s", package, masked_headers)
    return otlp_headers

def setup_tracing() -> trace.Tracer:
    """Configure OpenTelemetry tracing with OTLP export."""
    resource = get_resource()
    
    # Create tracer provider
    tracer_provider = TracerProvider(resource=resource)
    
    # Configure OTLP exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.observe.inc/v2/otel")
    otlp_headers = get_otlp_headers("Tracing")

    otlp_url = f"{otlp_endpoint}/v1/traces"
    masked_headers = {
        k: ("<masked>" if k.lower() == "authorization" else v)
        for k, v in otlp_headers.items()
    }
    logging.info(
        "OTLP trace exporter configured with url %s and headers %s",
        otlp_url,
        masked_headers,
    )

    # Set up OTLP span exporter
    otlp_exporter = OTLPSpanExporter(
        endpoint=otlp_url,
        headers=otlp_headers
    )
    
    # Add batch span processor
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    
    # Set global tracer provider
    trace.set_tracer_provider(tracer_provider)
    
    return trace.get_tracer(__name__)

def setup_metrics() -> metrics.Meter:
    """Configure OpenTelemetry metrics with Prometheus and OTLP export."""
    resource = get_resource()
    
    # Set up metric readers
    readers = []
    
    # Prometheus reader for local metrics
    prometheus_reader = PrometheusMetricReader()
    readers.append(prometheus_reader)
    
    # OTLP reader for remote metrics
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.observe.inc/v2/otel")
    otlp_headers = get_otlp_headers("Metrics")

    otlp_url = f"{otlp_endpoint}/v1/metrics"
    masked_headers = {
        k: ("<masked>" if k.lower() == "authorization" else v)
        for k, v in otlp_headers.items()
    }
    logging.info(
        "OTLP metric exporter configured with url %s and headers %s",
        otlp_url,
        masked_headers,
    )

    otlp_metric_exporter = OTLPMetricExporter(
        endpoint=otlp_url,
        headers=otlp_headers
    )
    
    otlp_reader = PeriodicExportingMetricReader(
        exporter=otlp_metric_exporter,
        export_interval_millis=5000
    )
    readers.append(otlp_reader)
    
    # Create meter provider
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=readers
    )
    
    # Set global meter provider
    metrics.set_meter_provider(meter_provider)
    
    return metrics.get_meter(__name__)

def setup_logging():
    """Configure OpenTelemetry logging integration."""
    LoggingInstrumentor().instrument(set_logging_format=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Configure OTLP log exporter
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.observe.inc/v2/otel")
    otlp_headers = get_otlp_headers("Host Explorer")

    otlp_url = f"{otlp_endpoint}/v1/logs"
    masked_headers = {
        k: ("<masked>" if k.lower() == "authorization" else v)
        for k, v in otlp_headers.items()
    }
    logging.info(
        "OTLP log exporter configured with url %s and headers %s",
        otlp_url,
        masked_headers,
    )

    logger_provider = LoggerProvider(resource=get_resource())
    log_exporter = OTLPLogExporter(
        endpoint=otlp_url,
        headers=otlp_headers,
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    root_logger.addHandler(handler)

    logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    for h in root_logger.handlers:
        h.setFormatter(logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s", "trace_id": "%(otelTraceID)s", "span_id": "%(otelSpanID)s"}',
            datefmt='%Y-%m-%dT%H:%M:%S'
        ))

def instrument_application(app):
    """Instrument Flask application with OpenTelemetry auto-instrumentation."""
    # Instrument Flask
    FlaskInstrumentor().instrument_app(app)
    
    # Instrument requests library (for OpenAI and Slack API calls)
    RequestsInstrumentor().instrument()
    
    # Instrument threading (for background processing)
    ThreadingInstrumentor().instrument()
    
    logging.info("Application instrumented with OpenTelemetry")

def create_custom_metrics(meter: metrics.Meter) -> dict:
    """Create custom business metrics for the AISDR application."""
    
    # Request counters
    slack_events_counter = meter.create_counter(
        name="aisdr_slack_events_total",
        description="Total number of Slack events processed",
        unit="1"
    )
    
    slack_slash_commands_counter = meter.create_counter(
        name="aisdr_slash_commands_total", 
        description="Total number of slash commands processed",
        unit="1"
    )
    
    # OpenAI API metrics
    openai_requests_counter = meter.create_counter(
        name="aisdr_openai_requests_total",
        description="Total number of OpenAI API requests",
        unit="1"
    )
    
    openai_request_duration = meter.create_histogram(
        name="aisdr_openai_request_duration_seconds",
        description="Duration of OpenAI API requests",
        unit="s"
    )
    
    # Slack API metrics
    slack_messages_counter = meter.create_counter(
        name="aisdr_slack_messages_sent_total",
        description="Total number of messages sent to Slack",
        unit="1"
    )
    
    # Email generation metrics
    emails_generated_counter = meter.create_counter(
        name="aisdr_emails_generated_total",
        description="Total number of emails successfully generated",
        unit="1"
    )
    
    processing_errors_counter = meter.create_counter(
        name="aisdr_processing_errors_total",
        description="Total number of processing errors",
        unit="1"
    )
    
    # Background task metrics
    background_tasks_counter = meter.create_counter(
        name="aisdr_background_tasks_total",
        description="Total number of background tasks started",
        unit="1"
    )
    
    background_task_duration = meter.create_histogram(
        name="aisdr_background_task_duration_seconds",
        description="Duration of background task processing",
        unit="s"
    )
    
    return {
        "slack_events_counter": slack_events_counter,
        "slack_slash_commands_counter": slack_slash_commands_counter,
        "openai_requests_counter": openai_requests_counter,
        "openai_request_duration": openai_request_duration,
        "slack_messages_counter": slack_messages_counter,
        "emails_generated_counter": emails_generated_counter,
        "processing_errors_counter": processing_errors_counter,
        "background_tasks_counter": background_tasks_counter,
        "background_task_duration": background_task_duration
    }

def setup_observability(app) -> tuple[trace.Tracer, metrics.Meter, dict]:
    """
    Complete OpenTelemetry setup for the AISDR application.
    
    Returns:
        Tuple of (tracer, meter, custom_metrics)
    """
    # Set up logging first so log records have trace context
    setup_logging()

    # Set up tracing
    tracer = setup_tracing()

    # Set up metrics
    meter = setup_metrics()
    
    # Instrument the application
    instrument_application(app)
    
    # Create custom metrics
    custom_metrics = create_custom_metrics(meter)
    
    logging.info("OpenTelemetry observability setup complete")
    
    return tracer, meter, custom_metrics

# Global variables for instrumentation
tracer: Optional[trace.Tracer] = None
meter: Optional[metrics.Meter] = None
custom_metrics: Optional[dict] = None

def get_tracer() -> trace.Tracer:
    """Get the global tracer instance."""
    global tracer
    if tracer is None:
        tracer = trace.get_tracer(__name__)
    return tracer

def get_meter() -> metrics.Meter:
    """Get the global meter instance."""
    global meter
    if meter is None:
        meter = metrics.get_meter(__name__)
    return meter

def get_custom_metrics() -> dict:
    """Get the custom metrics dictionary."""
    global custom_metrics
    if custom_metrics is None:
        custom_metrics = {}
    return custom_metrics