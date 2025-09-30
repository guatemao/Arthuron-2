import os, time, secrets
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "ash")

app = Flask(__name__, static_folder=STATIC_DIR)
app.url_map.strict_slashes = False
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

STATE = {"status": "OFF"}  # ON/OFF partagé

def load_persona():
    p = os.path.join(STATIC_DIR, "persona.txt")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Tu es Arthuron, vieux banc fatigué de Saint-Denis."

@app.route("/")
def index():
    # si tu utilises templates, renvoie render_template(...)
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/static/<path:fn>")
def static_files(fn):
    return send_from_directory(STATIC_DIR, fn)

@app.route("/session")
def session():
    # Ici tu dois appeler ton backend qui crée la clé éphémère côté OpenAI.
    # Pour l’exemple: faux token court (remplace par ton vrai flux d’ephemeral key).
    ephemeral = {
        "id": f"eph_{int(time.time())}",
        "value": secrets.token_urlsafe(24)
    }
    return jsonify({
        "id": f"sess_{int(time.time())}",
        "client_secret": ephemeral,
        "model": REALTIME_MODEL,
        "voice": REALTIME_VOICE,
        "persona": load_persona()
    })

@app.route("/state", methods=["POST"])
def set_state():
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("ON", "OFF"):
        return jsonify({"error":"bad status"}), 400
    STATE["status"] = status
    socketio.emit("state_update", {"status": status})
    return jsonify({"ok": True})

@socketio.on("connect")
def on_connect():
    emit("state_update", {"status": STATE["status"]})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    socketio.run(app, host="0.0.0.0", port=port)

