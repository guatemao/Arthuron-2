import os, requests
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

# --- Config ---
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

ELEVEN_API_KEY  = os.getenv("ELEVEN_API_KEY")   # DOIT être défini dans Render
ELEVEN_AGENT_ID = os.getenv("ELEVEN_AGENT_ID")  # format ag_..., depuis le Dashboard Agents

app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)

# --- Static / index ---
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.get("/static/<path:path>")
def static_proxy(path):
    return send_from_directory(STATIC_DIR, path)

# --- Health pour vérifier rapidement ---
@app.get("/health")
def health():
    return {
        "el_key": bool(ELEVEN_API_KEY),
        "agent_id": bool(ELEVEN_AGENT_ID),
    }
@app.get("/health")
def health():
    return {
        "el_key": bool(ELEVEN_API_KEY),
        "agent_id": bool(ELEVEN_AGENT_ID),
    }

# --- SIGNED URL Eleven Agents (la route qui te manque) ---
@app.get("/signed-url")
def get_signed_url():
    if not ELEVEN_API_KEY or not ELEVEN_AGENT_ID:
        return jsonify({"error": "Missing ELEVEN_API_KEY or ELEVEN_AGENT_ID"}), 500

    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": ELEVEN_AGENT_ID},
            headers={"xi-api-key": ELEVEN_API_KEY},
            timeout=10,
        )
    except Exception as e:
        return jsonify({"status": "network_error", "error": str(e)}), 502

    # renvoie TEL QUEL ce que dit ElevenLabs
    if r.status_code >= 300:
        return jsonify({
            "status": r.status_code,
            "body": r.text,
            "hint": "Clé/Agent invalide ? Workspace ?"
        }), r.status_code

    return jsonify(r.json())  # { "signed_url": "wss://..." }

if __name__ == "__main__":
    app.run("0.0.0.0", int(os.getenv("PORT", "5050")), debug=False)
