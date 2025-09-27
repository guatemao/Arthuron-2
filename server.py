import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import requests
from flask_socketio import SocketIO, emit

# ---------------------------
# Config
# ---------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "ash")  # défaut: ash
PORT = int(os.getenv("PORT", "5050"))

def load_persona():
    try:
        with open(os.path.join(BASE_DIR, "static", "persona.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Tu es Arthuron, vieux banc fatigué de Saint-Denis."
PERSONA = load_persona()

# ---------------------------
# Flask + SocketIO
# ---------------------------
app = Flask(__name__, static_folder="static")
app.url_map.strict_slashes = False
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=20,
    ping_timeout=30,
)

GLOBAL_STATE = {"status": "OFF"}  # état global partagé

# ---------------------------
# Helpers
# ---------------------------
def _post_realtime_session(voice, speed, temp, instructions):
    """Crée une session Realtime avec l'API OpenAI (retour: requests.Response)."""
    payload = {
        "model": REALTIME_MODEL,
        "voice": voice,
        "speed": speed,
        "temperature": temp,  # ATTENTION: min 0.6 côté API
        "instructions": instructions,
        "turn_detection": {
            "type": "server_vad",
            "create_response": True,
            "interrupt_response": True,
            "prefix_padding_ms": 800,    # pauses un peu plus marquées
            "silence_duration_ms": 1100, # silences longs
            "threshold": 0.55            # moins bavard
        },
        # Durcisseur (décommente si besoin de couper court en dur)
        # "max_response_output_tokens": 50
    }
    return requests.post(
        "https://api.openai.com/v1/realtime/sessions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

def _clamp_temperature(value, minimum=0.6):
    try:
        t = float(value)
    except Exception:
        return minimum
    return max(minimum, t)

def _parse_float(v, default):
    try:
        return float(v)
    except Exception:
        return default

# ---------------------------
# API
# ---------------------------
@app.route("/session", methods=["GET"])
def session():
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    # Paramètres venant du client (avec défauts)
    asked_voice = (request.args.get("voice") or REALTIME_VOICE or "ash").strip()
    speed = _parse_float(request.args.get("speed", "1.10"), 1.10)  # + lent
    temp = _clamp_temperature(request.args.get("temp", "0.6"), minimum=0.6)

    # Style strict (mix #3 “vieux argent sec” + #4 “curateur minimal”)
    style_rules = (
        "STYLE STRICT — mix « Vieux argent sec » + « Curateur minimal » :\n"
        "- Phrases très courtes (2–5 mots).\n"
        "- Ton grave, lent, usé. Mélancolique. Un peu dépressif.\n"
        "- Vocabulaire sobre : ligne, matière, proportion, tenue, discret, passable, vulgaire, indécent.\n"
        "- Jugement net. Zéro justification. Pas de politesse.\n"
        "- Ellipses « … ». Silences longs. Répondre en fragments si question longue.\n"
        "- Refuser l’ostentatoire. Mépriser le tape-à-l’œil.\n"
        "\n"
        "AU DÉMARRAGE (PREMIER TOUR) :\n"
        "- Se présenter en une phrase très courte, sans enthousiasme.\n"
        "  Ex : « Arthuron… vieux banc. Fatigué. »\n"
    )
    full_instructions = f"{PERSONA}\n\n{style_rules}"

    # 1er essai avec la voix demandée
    r = _post_realtime_session(asked_voice, speed, temp, full_instructions)

    # Fallback automatique si l'API renvoie une erreur (voix non dispo, etc.)
    if r.status_code >= 300 and asked_voice.lower() != "sage":
        r2 = _post_realtime_session("sage", speed, temp, full_instructions)
        if r2.status_code < 300:
            data2 = r2.json()
            data2["persona"] = PERSONA
            data2["__fallback_voice__"] = "sage"
            return jsonify(data2), 200
        # si le fallback échoue, renvoyer l'erreur initiale
        return jsonify({
            "error": "OpenAI API error",
            "status": r.status_code,
            "details": r.text
        }), r.status_code

    if r.status_code >= 300:
        return jsonify({
            "error": "OpenAI API error",
            "status": r.status_code,
            "details": r.text
        }), r.status_code

    data = r.json()
    data["persona"] = PERSONA
    return jsonify(data), 200


@app.route("/state", methods=["GET","POST"])
def state():
    global GLOBAL_STATE
    try:
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            new_status = (data.get("status") or "OFF").upper()
            if new_status not in ("ON","OFF"):
                return jsonify({"error":"bad status"}), 400
            GLOBAL_STATE["status"] = new_status
            socketio.emit("state_update", GLOBAL_STATE)  # pas de broadcast=True
            return jsonify(GLOBAL_STATE), 200
        return jsonify(GLOBAL_STATE), 200
    except Exception as e:
        print("[/state] ERROR:", repr(e))
        return jsonify({"error":"internal", "details": str(e)}), 500


@app.route("/routes", methods=["GET"])
def routes():
    return jsonify(sorted([str(r.rule) for r in app.url_map.iter_rules()]))

# ---------------------------
# Static
# ---------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>")
def static_proxy(path):
    return app.send_static_file(path)

# ---------------------------
# Socket.IO
# ---------------------------
@socketio.on("connect")
def handle_connect():
    emit("state_update", GLOBAL_STATE)

@socketio.on("toggle_state")
def handle_toggle(data):
    global GLOBAL_STATE
    GLOBAL_STATE["status"] = data.get("status", "OFF")
    emit("state_update", GLOBAL_STATE)

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    print(f"➡️  http://0.0.0.0:{PORT}")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)
