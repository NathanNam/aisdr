import os
from flask import Flask, request, jsonify
import requests
import threading

app = Flask(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "YOUR_SLACK_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

with open("aisdr_system_prompt.txt", "r", encoding="utf-8") as f:
    system_prompt_template = f.read()

processed_events = set()

def background_process(user_message, channel):
    response_text = process_user_input(user_message)
    send_message_to_slack(channel, response_text)

def background_slash_processing(text, response_url):
    response_text = process_user_input(text)
    final_payload = {
        "response_type": "in_channel",
        "text": response_text
    }
    requests.post(response_url, json=final_payload)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json or {}
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event_id = data.get("event_id")
    if event_id:
        if event_id in processed_events:
            return jsonify({"status": "ok"})
        processed_events.add(event_id)

    event = data.get("event", {})
    event_type = event.get("type")

    if event_type not in ["message", "app_mention"]:
        return jsonify({"status": "ok"})

    if event.get("bot_id"):
        return jsonify({"status": "ok"})
    if event.get("subtype"):
        return jsonify({"status": "ok"})

    user_message = event.get("text", "")
    channel = event.get("channel")

    resp = jsonify({"status": "ok"})
    t = threading.Thread(target=background_process, args=(user_message, channel))
    t.start()

    return resp

@app.route("/slack/slash", methods=["POST"])
def slash_aisdr():
    text = request.form.get("text", "")
    response_url = request.form.get("response_url")

    # Respond in-channel so everyone sees this message (no "Only visible to you")
    initial_response = {
        "response_type": "in_channel",
        "text": f"Received: `/aisdr {text}`\n\nProcessing your request, please wait..."
    }

    t = threading.Thread(target=background_slash_processing, args=(text, response_url))
    t.start()

    return jsonify(initial_response)

def process_user_input(user_message):
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

    response = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
    response_data = response.json()
    print("OpenAI API response:", response_data)

    if "error" in response_data:
        return "Sorry, I couldn't process your request at the moment."
    if "choices" not in response_data or not response_data["choices"]:
        return "Sorry, I couldn't generate a response right now."

    completion = response_data["choices"][0]["message"]["content"]
    return completion.strip()

def send_message_to_slack(channel, text):
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"}
    payload = {"channel": channel, "text": text}
    resp = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload)
    print("Slack message response:", resp.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
