import os, time, secrets
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "ash")

# static_url_path garantit /static/... propre
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
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
        # Fallback court si persona.txt absent
        return "Tu es Arthuron, vieux banc fatigué de Saint-Denis."

@app.route("/")
def index():
    # Sert /static/index.html si tu l’y as mis
    return send_from_directory(STATIC_DIR, "index.html")

# /static/* est déjà servi par Flask grâce à static_url_path

@app.route("/session")
def session():
    """
    ⚠️ Tu dois remplacer ce faux token par la création
    d'une vraie clé éphémère côté serveur.
    """
    ephemeral = {
        "id": f"eph_{int(time.time())}",
        "value": secrets.token_urlsafe(24)
    }
    return jsonify({
        "id": f"sess_{int(time.time())}",
        "client_secret": ephemeral,
        "model": REALTIME_MODEL,
        "voice": REALTIME_VOICE,
        "persona": load_persona()  # ← persona chargée à chaque session
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

# Optionnel: GET /state utile pour debug/UI
@app.route("/state", methods=["GET"])
def get_state():
    return jsonify({"status": STATE["status"]})

@socketio.on("connect")
def on_connect():
    emit("state_update", {"status": STATE["status"]})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    socketio.run(app, host="0.0.0.0", port=port)
