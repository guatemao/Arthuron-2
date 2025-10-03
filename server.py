import os, json, asyncio
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import websockets  # pip install websockets

# ---------------------------
# Config & Persona
# ---------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
PORT = int(os.getenv("PORT", "5050"))

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "499f1e03920aaced255f33c8867054f064d9ef62e8bb75797350bf0c2adde4dd")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "7eUAxNOneHxqfyRS77mW")  # ex: 7eUAxNOneHxqfyRS77mW
ELEVEN_MODEL_ID = os.getenv("ELEVEN_MODEL_ID", "eleven_flash_v2_5")
ELEVEN_LATENCY = int(os.getenv("ELEVEN_LATENCY", "2"))  # 0-4
ELEVEN_FORMAT = os.getenv("ELEVEN_FORMAT", "mp3_44100_128")  # ou pcm_16000

def load_persona():
    try:
        with open(os.path.join(BASE_DIR, "static", "persona.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Tu es Arthuron, vieux banc fatigué de Saint-Denis."
PERSONA = load_persona()

# ---------------------------
# Flask
# ---------------------------
app = Flask(__name__, static_folder="static")
CORS(app)

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>")
def static_proxy(path):
    return app.send_static_file(path)

# ---------------------------
# OpenAI Realtime: session (TEXTE SEULEMENT côté client)
# ---------------------------
@app.route("/session", methods=["GET"])
def session():
    """
    Renvoie la config Realtime OpenAI pour le client.
    IMPORTANT: on n’envoie PAS 'voice' → on ne veut pas d’audio OpenAI.
    C’est le client qui doit demander des réponses en modalities:["text"].
    """
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    try:
        r = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": REALTIME_MODEL},
            timeout=20,
        )
        if r.status_code >= 300:
            print("[/session] ERROR", r.status_code, r.text)
            return jsonify({"status": r.status_code, "body": r.text}), 500

        data = r.json()
        data["persona"] = PERSONA  # on repasse la persona au front
        data["note"] = "Demande des réponses modalities:['text'] et streame vers /tts/chunk puis /tts/flush."
        return jsonify(data)
    except Exception as e:
        print("[/session] EXC", e)
        return jsonify({"error": str(e)}), 500

# ---------------------------
# ElevenLabs Proxy (WS persistant)
# ---------------------------
eleven_ws = None

async def ensure_ws():
    """
    Ouvre (ou réutilise) une connexion WS ElevenLabs pour streaming TTS.
    """
    global eleven_ws
    if eleven_ws and not eleven_ws.closed:
        return eleven_ws
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        raise RuntimeError("ELEVEN_API_KEY ou ELEVEN_VOICE_ID manquant")

    url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream-input"
    eleven_ws = await websockets.connect(url, extra_headers={"xi-api-key": ELEVEN_API_KEY})

    init = {
        "text": "",
        "model_id": ELEVEN_MODEL_ID,
        "output_format": ELEVEN_FORMAT,        # ex: "mp3_44100_128" (simple à jouer)
        "optimize_streaming_latency": ELEVEN_LATENCY,  # 0-4
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.7}
    }
    await eleven_ws.send(json.dumps(init))
    return eleven_ws

@app.post("/tts/chunk")
def tts_chunk():
    """
    Reçoit les fragments de texte (delta) d’OpenAI et les envoie à ElevenLabs.
    Body: { "text": "..." }
    """
    data = request.get_json(force=True) or {}
    txt = (data.get("text") or "").strip()
    if not txt:
        return {"ok": True}
    asyncio.get_event_loop().create_task(_send_chunk(txt))
    return {"ok": True}

async def _send_chunk(txt: str):
    try:
        ws = await ensure_ws()
        await ws.send(json.dumps({"text": txt, "try_trigger_generation": True}))
    except Exception as e:
        print("[/tts/chunk] EXC", e)

@app.post("/tts/flush")
def tts_flush():
    """
    Appelé quand OpenAI signale 'response.completed' → force la génération audio côté ElevenLabs.
    """
    asyncio.get_event_loop().create_task(_flush())
    return {"ok": True}

async def _flush():
    try:
        ws = await ensure_ws()
        await ws.send(json.dumps({"flush": True}))
    except Exception as e:
        print("[/tts/flush] EXC", e)

# (Optionnel) endpoint pour reset/fermer le WS si besoin
@app.post("/tts/reset")
def tts_reset():
    asyncio.get_event_loop().create_task(_reset_ws())
    return {"ok": True}

async def _reset_ws():
    global eleven_ws
    try:
        if eleven_ws and not eleven_ws.closed:
            await eleven_ws.close()
    finally:
        eleven_ws = None

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    print(f"➡️  http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)


