import os, json, threading, queue, time, asyncio
from flask import Flask, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import websockets  # requirements: websockets==12.0

# ---------------------------
# Config & Persona
# ---------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
PORT = int(os.getenv("PORT", "5050"))

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID  = os.getenv("ELEVEN_VOICE_ID", "7eUAxNOneHxqfyRS77mW")
ELEVEN_MODEL_ID  = os.getenv("ELEVEN_MODEL_ID", "eleven_flash_v2_5")
ELEVEN_LATENCY   = int(os.getenv("ELEVEN_LATENCY", "2"))  # 0-4
ELEVEN_FORMAT    = os.getenv("ELEVEN_FORMAT", "mp3_44100_128")  # "mp3_44100_128" recommandé

def load_persona():
    try:
        with open(os.path.join(STATIC_DIR, "persona.txt"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Tu es Selena, machine à laver brésilienne, batucada, drôle, un peu coquine."
PERSONA = load_persona()

# ---------------------------
# Flask
# ---------------------------
app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.get("/static/<path:path>")
def static_proxy(path):
    return send_from_directory(STATIC_DIR, path)

# ---------------------------
# OpenAI Realtime: session (client ne demande QUE du texte)
# ---------------------------
@app.get("/session")
def session():
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500
    try:
        r = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": REALTIME_MODEL},
            timeout=20,
        )
        if r.status_code >= 300:
            print("[/session] ERROR", r.status_code, r.text)
            return jsonify({"status": r.status_code, "body": r.text}), 500
        data = r.json()
        data["persona"] = PERSONA
        data["note"] = "Côté client: demande des réponses modalities:['text'] et envoie sur /tts/chunk puis /tts/flush."
        return jsonify(data)
    except Exception as e:
        print("[/session] EXC", e)
        return jsonify({"error": str(e)}), 500

# ---------------------------
# ElevenLabs worker (thread + event loop)
# ---------------------------
# Files/queues thread-safe côté Flask (HTTP) <-> loop asyncio côté WS
audio_queue = queue.Queue(maxsize=512)   # flux MP3 vers /tts/stream.mp3
ctrl_queue  = queue.Queue(maxsize=512)   # debug/état si tu veux logger

# Ces deux-là sont pilotés DANS la loop asyncio :
_async_text_queue  = None  # asyncio.Queue[str]
_async_cmd_queue   = None  # asyncio.Queue[dict]  ({"flush":True}, etc.)

# L’event loop dédié du worker
_loop = None

async def el_worker():
    """
    Lance/répare la connexion WS ElevenLabs et gère 2 tâches concurrentes:
    - sender: lit _async_text_queue et envoie {text,...} / {flush:true}
    - reader: lit l'audio binaire et le pousse dans audio_queue
    """
    global _async_text_queue, _async_cmd_queue
    _async_text_queue = asyncio.Queue()
    _async_cmd_queue = asyncio.Queue()

    async def connect():
        url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream-input"
        ws = await websockets.connect(url, extra_headers={"xi-api-key": ELEVEN_API_KEY})
        init = {
            "text": "",
            "model_id": ELEVEN_MODEL_ID,
            "output_format": ELEVEN_FORMAT,
            "optimize_streaming_latency": ELEVEN_LATENCY,
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.7},
        }
        await ws.send(json.dumps(init))
        return ws

    ws = None
    last_keep = 0.0

    while True:
        try:
            if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
                ctrl_queue.put_nowait("[EL] Missing API key or voice id")
                await asyncio.sleep(2)
                continue

            ws = await connect()
            ctrl_queue.put_nowait("[EL] connected")

            async def sender():
                nonlocal last_keep
                while True:
                    # priorité aux commandes (flush)
                    try:
                        cmd = _async_cmd_queue.get_nowait()
                        if "flush" in cmd:
                            await ws.send(json.dumps({"flush": True}))
                        continue
                    except asyncio.QueueEmpty:
                        pass

                    # keepalive toutes ~12s pour éviter idle close
                    now = time.time()
                    if now - last_keep > 12:
                        await ws.send(json.dumps({"text": " ", "try_trigger_generation": False}))
                        last_keep = now

                    # texte à envoyer (si dispo), sinon dors léger
                    try:
                        txt = _async_text_queue.get_nowait()
                        if txt:
                            await ws.send(json.dumps({"text": txt, "try_trigger_generation": True}))
                        continue
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.02)

            async def reader():
                while True:
                    msg = await ws.recv()
                    if isinstance(msg, (bytes, bytearray)):
                        try:
                            audio_queue.put(msg, timeout=0.2)
                        except queue.Full:
                            pass  # on jette si saturé
                    else:
                        # JSON status from EL (rarement utile)
                        pass

            await asyncio.gather(sender(), reader())

        except Exception as e:
            ctrl_queue.put_nowait(f"[EL] reconnect in 1s: {e}")
            await asyncio.sleep(1)
        finally:
            try:
                if ws:
                    await ws.close()
            except:
                pass
            ws = None

def _start_loop_in_thread():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.create_task(el_worker())
    _loop.run_forever()

# Démarrage du worker en arrière-plan au launch du module
threading.Thread(target=_start_loop_in_thread, name="el-worker", daemon=True).start()

# Helpers pour pousser dans les queues asyncio depuis Flask (thread principal)
def _async_put_text(txt: str):
    if _loop is None or _async_text_queue is None:
        return
    fut = asyncio.run_coroutine_threadsafe(_async_text_queue.put(txt), _loop)
    fut.result(timeout=2)

def _async_send_flush():
    if _loop is None or _async_cmd_queue is None:
        return
    fut = asyncio.run_coroutine_threadsafe(_async_cmd_queue.put({"flush": True}), _loop)
    fut.result(timeout=2)

# ---------------------------
# Endpoints TTS
# ---------------------------
@app.post("/tts/chunk")
def tts_chunk():
    data = request.get_json(force=True) or {}
    txt = (data.get("text") or "").strip()
    if not txt:
        return {"ok": True}
    try:
        _async_put_text(txt)
        return {"ok": True}
    except Exception as e:
        print("[/tts/chunk] EXC", e)
        return {"ok": False, "error": str(e)}, 500

@app.post("/tts/flush")
def tts_flush():
    try:
        _async_send_flush()
        return {"ok": True}
    except Exception as e:
        print("[/tts/flush] EXC", e)
        return {"ok": False, "error": str(e)}, 500
@app.get("/health")
def health():
    return {
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "el_key": bool(os.getenv("ELEVEN_API_KEY")),
        "voice": bool(os.getenv("ELEVEN_VOICE_ID")),
    }

@app.get("/tts/stream.mp3")
def tts_stream():
    def gen():
        # stream chunked MP3
        while True:
            chunk = audio_queue.get()  # bloquant
            if not chunk:
                continue
            yield chunk
    return Response(gen(), mimetype="audio/mpeg")

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    print(f"➡️  http://localhost:{PORT}")
    # Dev server Flask. En prod Render: utiliser gunicorn avec 1 worker.
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
