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

Key libraries include Flask, requests, slack_sdk, openai and opentelemetry-distro.

## Configuration

Provide your credentials through environment variables before starting the app:

```bash
export SLACK_BOT_TOKEN=<your token>
export OPENAI_API_KEY=<your key>
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

## Customizing the prompt

Edit `aisdr_system_prompt.txt` to adjust the tone, style or competitor references used when generating emails.

