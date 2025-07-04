# AISDR

AISDR is a lightweight Slack bot that uses OpenAI's API to generate cold outreach emails.
It exposes two Flask endpoints that Slack can call:

- `/slack/events` for event subscriptions
- `/slack/slash` for a slash command

The prompt used to craft the email lives in `aisdr_system_prompt.txt` so you can customize the messaging.

## Requirements

Install the Python dependencies listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

This installs the OTLP HTTP exporter required for tracing. If the package is missing, you'll see errors like `ModuleNotFoundError: No module named 'opentelemetry.exporter'`.

Key libraries include Flask, requests, slack_sdk, openai and comprehensive OpenTelemetry instrumentation.

## Configuration

Provide your credentials through environment variables before starting the app:

```bash
export SLACK_BOT_TOKEN=<your token>
export OPENAI_API_KEY=<your key>
```

### OpenTelemetry Configuration

The application includes comprehensive OpenTelemetry instrumentation for observability:

```bash
# Required for basic functionality
export SLACK_BOT_TOKEN=<your_slack_bot_token>
export OPENAI_API_KEY=<your_openai_api_key>

# OpenTelemetry configuration
export OTEL_SERVICE_NAME=aisdr-bot
export OTEL_SERVICE_VERSION=1.0.0
export OTEL_ENVIRONMENT=production
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.observe.inc/v2/otel
export OTEL_EXPORTER_OTLP_HEADERS='{"Authorization":"Bearer <YOUR_INGEST_TOKEN>"}'
# Or use the simplified variable
export OTEL_EXPORTER_OTLP_AUTH_HEADER="Authorization=Bearer <YOUR_INGEST_TOKEN>"
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf

# For Observe.inc integration
export OBSERVE_INGEST_TOKEN=<your_observe_ingest_token>

# When set, `OBSERVE_INGEST_TOKEN` replaces any token defined via
# `OTEL_EXPORTER_OTLP_HEADERS` or `OTEL_EXPORTER_OTLP_AUTH_HEADER`. Make sure
# this token grants access to Tracing, Metrics and Logs, or unset it if you want
# to rely solely on `OTEL_EXPORTER_OTLP_AUTH_HEADER`.
```

The application automatically sets the `x-observe-target-package` header for each
signal:

- Traces: `Tracing`
- Metrics: `Metrics`
- Logs: `Host Explorer`

So you only need to provide the `Authorization` token using either
`OTEL_EXPORTER_OTLP_HEADERS` or `OTEL_EXPORTER_OTLP_AUTH_HEADER`.
```

Copy `.env.example` to `.env` and configure your values:
```bash
cp .env.example .env
# Edit .env with your credentials
```

These are loaded at startup by `aisdr.py`:

```python
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "YOUR_SLACK_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
```

## Running

Launch the Flask application with:

```bash
python aisdr.py
```

By default the server listens on port 8080:

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

## Slack Setup

Configure your Slack app to send events to `/slack/events` and create a slash command (for example `/aisdr`) that posts to `/slack/slash`.
The bot will reply in the originating channel with the generated email once OpenAI returns a response.

## OpenTelemetry Observability

The application includes comprehensive OpenTelemetry instrumentation providing:

### 🔍 Distributed Tracing
- All HTTP requests (Slack events, slash commands)
- OpenAI API calls with timing and error tracking
- Background processing operations
- Slack API message sending

### 📊 Metrics Collection
- `aisdr_slack_events_total` - Total Slack events processed
- `aisdr_slash_commands_total` - Total slash commands executed
- `aisdr_openai_requests_total` - OpenAI API calls by competitor
- `aisdr_openai_request_duration_seconds` - OpenAI response times
- `aisdr_emails_generated_total` - Successful email generations
- `aisdr_processing_errors_total` - Error counts by type
- `aisdr_background_tasks_total` - Background task metrics

### 📝 Structured Logging
- JSON-formatted logs with trace correlation
- Trace and span IDs included in all log entries
- Proper log levels (INFO, ERROR, WARN)
- Request flow tracking across all components

### 🧪 Testing Instrumentation

Validate the OpenTelemetry setup:

```bash
python test_instrumentation.py
```

### 🚀 Metrics Endpoint

Prometheus metrics are available at `http://localhost:8080/metrics` (auto-configured by OpenTelemetry).

## Customizing the prompt

Edit `aisdr_system_prompt.txt` to adjust the tone, style or competitor references used when generating emails.

