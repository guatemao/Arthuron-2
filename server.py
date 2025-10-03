import os, requests
from flask import Flask, jsonify, request
from flask_cors import CORS

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")     # mets ça dans Render env vars
ELEVEN_AGENT_ID = os.getenv("ELEVEN_AGENT_ID")   # l’ID de ton agent

app = Flask(__name__)
CORS(app)

@app.get("/signed-url")
def signed_url():
    if not ELEVEN_API_KEY or not ELEVEN_AGENT_ID:
        return jsonify({"error":"missing ELEVEN_API_KEY or ELEVEN_AGENT_ID"}), 500
    r = requests.get(
        "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        params={"agent_id": ELEVEN_AGENT_ID},
        headers={"xi-api-key": ELEVEN_API_KEY},
        timeout=10
    )
    if r.status_code >= 300:
        return jsonify({"status": r.status_code, "body": r.text}), 500
    return jsonify(r.json())  # { "signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...&conversation_signature=..." }

if __name__ == "__main__":
    app.run("0.0.0.0", 5050)

