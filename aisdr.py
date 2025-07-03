import os
import time
import logging
from flask import Flask, request, jsonify
import requests
import threading
from opentelemetry import trace

# Initialize OpenTelemetry before creating the Flask app
from otel_setup import setup_observability

app = Flask(__name__)

# Initialize OpenTelemetry instrumentation
tracer, meter, custom_metrics = setup_observability(app)
logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "YOUR_SLACK_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

with open("aisdr_system_prompt.txt", "r", encoding="utf-8") as f:
    system_prompt_template = f.read()

processed_events = set()

def background_process(user_message, channel):
    with tracer.start_as_current_span("background_process") as span:
        start_time = time.time()
        custom_metrics["background_tasks_counter"].add(1, {"type": "event"})
        
        span.set_attribute("user_message", user_message)
        span.set_attribute("channel", channel)
        logger.info(f"Processing background task for channel: {channel}")
        
        try:
            response_text = process_user_input(user_message)
            send_message_to_slack(channel, response_text)
            span.set_attribute("success", True)
            logger.info(f"Successfully processed background task for channel: {channel}")
        except Exception as e:
            span.set_attribute("success", False)
            span.set_attribute("error", str(e))
            custom_metrics["processing_errors_counter"].add(1, {"type": "background_process"})
            logger.error(f"Error in background process: {str(e)}")
            raise
        finally:
            duration = time.time() - start_time
            custom_metrics["background_task_duration"].record(duration, {"type": "event"})

def background_slash_processing(text, response_url):
    with tracer.start_as_current_span("background_slash_processing") as span:
        start_time = time.time()
        custom_metrics["background_tasks_counter"].add(1, {"type": "slash"})
        
        span.set_attribute("text", text)
        span.set_attribute("response_url", response_url)
        logger.info(f"Processing slash command background task: {text}")
        
        try:
            response_text = process_user_input(text)
            final_payload = {
                "response_type": "in_channel",
                "text": response_text
            }
            requests.post(response_url, json=final_payload)
            span.set_attribute("success", True)
            logger.info(f"Successfully processed slash command: {text}")
        except Exception as e:
            span.set_attribute("success", False)
            span.set_attribute("error", str(e))
            custom_metrics["processing_errors_counter"].add(1, {"type": "background_slash"})
            logger.error(f"Error in slash command processing: {str(e)}")
            raise
        finally:
            duration = time.time() - start_time
            custom_metrics["background_task_duration"].record(duration, {"type": "slash"})

@app.route("/slack/events", methods=["POST"])
def slack_events():
    with tracer.start_as_current_span("slack_events") as span:
        custom_metrics["slack_events_counter"].add(1)
        data = request.json or {}
        
        span.set_attribute("event_type", data.get("type", "unknown"))
        logger.info(f"Received Slack event: {data.get('type', 'unknown')}")
        
        if "challenge" in data:
            span.set_attribute("challenge_received", True)
            logger.info("Slack challenge received")
            return jsonify({"challenge": data["challenge"]})

        event_id = data.get("event_id")
        if event_id:
            span.set_attribute("event_id", event_id)
            if event_id in processed_events:
                span.set_attribute("duplicate_event", True)
                logger.info(f"Duplicate event ignored: {event_id}")
                return jsonify({"status": "ok"})
            processed_events.add(event_id)

        event = data.get("event", {})
        event_type = event.get("type")
        span.set_attribute("slack_event_type", event_type)

        if event_type not in ["message", "app_mention"]:
            span.set_attribute("event_ignored", True)
            logger.info(f"Event type ignored: {event_type}")
            return jsonify({"status": "ok"})

        if event.get("bot_id"):
            span.set_attribute("bot_message_ignored", True)
            logger.info("Bot message ignored")
            return jsonify({"status": "ok"})
        if event.get("subtype"):
            span.set_attribute("subtype_ignored", True)
            logger.info(f"Event subtype ignored: {event.get('subtype')}")
            return jsonify({"status": "ok"})

        user_message = event.get("text", "")
        channel = event.get("channel")
        
        span.set_attribute("user_message", user_message)
        span.set_attribute("channel", channel)
        span.set_attribute("processing_started", True)
        
        logger.info(f"Starting background processing for message in channel: {channel}")

        resp = jsonify({"status": "ok"})
        t = threading.Thread(target=background_process, args=(user_message, channel))
        t.start()

        return resp

@app.route("/slack/slash", methods=["POST"])
def slash_aisdr():
    with tracer.start_as_current_span("slash_aisdr") as span:
        custom_metrics["slack_slash_commands_counter"].add(1)
        text = request.form.get("text", "")
        response_url = request.form.get("response_url")
        
        span.set_attribute("command_text", text)
        span.set_attribute("response_url", response_url)
        logger.info(f"Received slash command: {text}")

        # Respond in-channel so everyone sees this message (no "Only visible to you")
        initial_response = {
            "response_type": "in_channel",
            "text": f"Received: `/aisdr {text}`\n\nProcessing your request, please wait..."
        }

        t = threading.Thread(target=background_slash_processing, args=(text, response_url))
        t.start()
        
        span.set_attribute("background_task_started", True)
        logger.info(f"Started background processing for slash command: {text}")

        return jsonify(initial_response)

def process_user_input(user_message):
    with tracer.start_as_current_span("process_user_input") as span:
        span.set_attribute("user_message", user_message)
        logger.info(f"Processing user input: {user_message}")
        
        # Parse user input
        name = "Jack"
        position = "CTO"
        competitor_tool = "Datadog"

        parts = [p.strip() for p in user_message.split(",")]
        for part in parts:
            if "Name:" in part:
                name = part.split("Name:")[1].strip()
            elif "Position:" in part:
                position = part.split("Position:")[1].strip()
            elif "Competitor:" in part:
                competitor_tool = part.split("Competitor:")[1].strip()

        span.set_attribute("prospect_name", name)
        span.set_attribute("prospect_position", position)
        span.set_attribute("competitor_tool", competitor_tool)
        
        logger.info(f"Parsed prospect info - Name: {name}, Position: {position}, Competitor: {competitor_tool}")

        system_prompt = system_prompt_template.format(
            name=name,
            position=position,
            competitor_tool=competitor_tool
        )

        user_prompt = (
            f"Name: {name}\n"
            f"Position: {position}\n"
            f"Competitor Tool: {competitor_tool}\n\n"
            "Please craft a compelling cold email introducing our tool and why "
            f"{name} should consider switching from {competitor_tool}."
        )

        # OpenAI API call with tracing
        with tracer.start_as_current_span("openai_api_call") as api_span:
            start_time = time.time()
            custom_metrics["openai_requests_counter"].add(1, {"competitor": competitor_tool})
            
            api_span.set_attribute("model", "gpt-4o")
            api_span.set_attribute("competitor_tool", competitor_tool)
            api_span.set_attribute("prospect_name", name)
            
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }

            try:
                logger.info("Making OpenAI API request")
                response = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
                api_duration = time.time() - start_time
                custom_metrics["openai_request_duration"].record(api_duration, {"competitor": competitor_tool})
                
                response_data = response.json()
                api_span.set_attribute("response_status_code", response.status_code)
                api_span.set_attribute("response_success", response.status_code == 200)
                
                logger.info(f"OpenAI API response status: {response.status_code}")
                print("OpenAI API response:", response_data)

                if "error" in response_data:
                    api_span.set_attribute("error", str(response_data["error"]))
                    custom_metrics["processing_errors_counter"].add(1, {"type": "openai_error"})
                    logger.error(f"OpenAI API error: {response_data['error']}")
                    return "Sorry, I couldn't process your request at the moment."
                    
                if "choices" not in response_data or not response_data["choices"]:
                    api_span.set_attribute("error", "No choices in response")
                    custom_metrics["processing_errors_counter"].add(1, {"type": "no_choices"})
                    logger.error("No choices in OpenAI response")
                    return "Sorry, I couldn't generate a response right now."

                completion = response_data["choices"][0]["message"]["content"]
                api_span.set_attribute("completion_length", len(completion))
                custom_metrics["emails_generated_counter"].add(1, {"competitor": competitor_tool})
                
                logger.info(f"Successfully generated email of length: {len(completion)}")
                return completion.strip()
                
            except Exception as e:
                api_span.set_attribute("error", str(e))
                custom_metrics["processing_errors_counter"].add(1, {"type": "openai_exception"})
                logger.error(f"Exception during OpenAI API call: {str(e)}")
                raise

def send_message_to_slack(channel, text):
    with tracer.start_as_current_span("send_message_to_slack") as span:
        custom_metrics["slack_messages_counter"].add(1)
        span.set_attribute("channel", channel)
        span.set_attribute("message_length", len(text))
        logger.info(f"Sending message to Slack channel: {channel}")
        
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"}
        payload = {"channel": channel, "text": text}
        
        try:
            resp = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
            response_data = resp.json()
            
            span.set_attribute("response_status_code", resp.status_code)
            span.set_attribute("slack_response_ok", response_data.get("ok", False))
            
            if response_data.get("ok"):
                span.set_attribute("message_sent_successfully", True)
                logger.info(f"Successfully sent message to Slack channel: {channel}")
            else:
                span.set_attribute("slack_error", response_data.get("error", "unknown"))
                custom_metrics["processing_errors_counter"].add(1, {"type": "slack_api_error"})
                logger.error(f"Slack API error: {response_data.get('error', 'unknown')}")
            
            print("Slack message response:", response_data)
            
        except Exception as e:
            span.set_attribute("error", str(e))
            custom_metrics["processing_errors_counter"].add(1, {"type": "slack_exception"})
            logger.error(f"Exception sending message to Slack: {str(e)}")
            raise

if __name__ == "__main__":
    logger.info("Starting AISDR Flask application with OpenTelemetry instrumentation")
    logger.info(f"OpenTelemetry configuration: endpoint={os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'https://api.observe.inc/v1/otel')}")
    app.run(host="0.0.0.0", port=8080)
