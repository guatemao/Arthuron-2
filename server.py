import os, json
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "sage")
PORT = int(os.getenv("PORT", "5050"))

def load_persona():
    try:
        persona_path = os.path.join(BASE_DIR, "static", "persona.txt")
        with open(persona_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Tu es Arthuron, vieux banc fatigué de Saint-Denis."

PERSONA = load_persona()

app = Flask(__name__, static_folder="static")
CORS(app)

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>")
def static_proxy(path):
    return app.send_static_file(path)

@app.route("/session", methods=["GET"])
def session():
    if not OPENAI_API_KEY:
        return jsonify({"error":"Missing OPENAI_API_KEY"}), 500
    try:
        r = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": REALTIME_MODEL, "voice": REALTIME_VOICE},
            timeout=20,
        )
        if r.status_code >= 300:
            print("[/session] ERROR", r.status_code, r.text)
            return jsonify({"status": r.status_code, "body": r.text}), 500

        data = r.json()
        data["persona"] = PERSONA
        return jsonify(data)
    except Exception as e:
        print("[/session] EXC", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print(f"➡️  http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)


