import os
import json
import asyncio
import base64
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

try:
    from google import genai
    from google.genai import types
except Exception as exc:
    genai = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env.live"
load_dotenv(ENV_FILE)

HOST = "127.0.0.1"
PORT = 8020
REQUESTED_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
# Gemini 3.1 Flash Live currently has a reported voiceName-selection bug.
# Force the known-good native-audio Live model for selectable voices.
LIVE_MODEL = (
    "gemini-2.5-flash-native-audio-preview-12-2025"
    if REQUESTED_LIVE_MODEL == "gemini-3.1-flash-live-preview"
    else REQUESTED_LIVE_MODEL
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ALLOWED_VOICES = {
    "male": "Algieba",
    "female": "Vindemiatrix",
}

BASE_SYSTEM_INSTRUCTION = os.getenv(
    "MONSTER_LIVE_SYSTEM",
    "You are MONSTER AI in live voice mode.\n"
    "Respond naturally, directly, and concisely.\n"
    "Do not repeat the user unless necessary.\n"
    "You are a voice assistant, not a narrator.\n"
    "Use a calm, warm, gentle and reassuring speaking style; avoid an excited or aggressive tone.\n"
)

def language_instruction(lang: str) -> str:
    lang = (lang or "ar-DZ").lower()
    if lang.startswith("en"):
        return "Speak and respond ONLY in English unless the user explicitly asks for another language."
    if lang.startswith("fr"):
        return "Speak and respond ONLY in French unless the user explicitly asks for another language."
    return (
        "Speak and respond ONLY in Algerian Arabic (Darija), using Arabic script, "
        "unless the user explicitly asks for another language. Keep technical product "
        "names, code, APIs, and model names in their original form when needed."
    )

app = FastAPI(title="MONSTER Live Voice Gateway")


def make_client():
    if genai is None:
        raise RuntimeError(f"google-genai import failed: {IMPORT_ERROR}")
    if not GEMINI_API_KEY:
        raise RuntimeError(
            f"GEMINI_API_KEY is missing. Put it in {ENV_FILE}"
        )
    return genai.Client(api_key=GEMINI_API_KEY)


@app.get("/health")
async def health():
    ok = bool(GEMINI_API_KEY) and genai is not None
    return JSONResponse({
        "ok": ok,
        "configured": bool(GEMINI_API_KEY),
        "model": LIVE_MODEL,
        "service": "monster-live-voice",
        "port": PORT,
        "import_error": None if genai is not None else str(IMPORT_ERROR),
    })


@app.websocket("/live")
async def live(websocket: WebSocket):
    await websocket.accept()
    try:
        client = make_client()
        query = parse_qs(urlparse(str(websocket.url)).query)
        lang = (query.get("lang", ["ar-DZ"])[0] or "ar-DZ").strip()
        voice_key = (query.get("voice", ["male"])[0] or "male").strip().lower()
        # Accept only gender keys from the browser; tolerate voice names for backward compatibility.
        if voice_key in {"orus", "puck", "charon", "fenrir", "iapetus", "rasalgethi", "sadachbia", "sadaltager", "schedar", "umbriel"}:
            voice_key = "male"
        elif voice_key in {"kore", "leda", "aoede", "laomedeia", "pulcherrima", "sulafat", "zephyr", "achernar", "vindemiatrix"}:
            voice_key = "female"
        voice_name = ALLOWED_VOICES.get(voice_key, ALLOWED_VOICES["male"])
        print(f"LIVE VOICE: lang={lang} voice={voice_key} voice_name={voice_name} model={LIVE_MODEL}")
        if REQUESTED_LIVE_MODEL != LIVE_MODEL:
            print(f"VOICE FIX: {REQUESTED_LIVE_MODEL} -> {LIVE_MODEL} (voice selection compatibility)")
        system_instruction = BASE_SYSTEM_INSTRUCTION + "\n" + language_instruction(lang)
        config = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": voice_name,
                    }
                }
            },
            "system_instruction": system_instruction,
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,
                }
            },
        }

        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await websocket.send_json({
                "type": "ready",
                "model": LIVE_MODEL,
                "language": lang,
                "voice": voice_key,
                "voice_name": voice_name,
            })

            async def browser_to_gemini():
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break

                    if message.get("bytes") is not None:
                        pcm = message["bytes"]
                        if pcm:
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                            )
                        continue

                    text = message.get("text")
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue

                    event = payload.get("type")
                    if event == "audio_end":
                        await session.send_realtime_input(audio_stream_end=True)
                    elif event == "start":
                        # The voice is selected when the WebSocket session is created.
                        # Keep this event for browser backwards compatibility.
                        pass
                    elif event == "close":
                        return

            async def gemini_to_browser():
                # A Gemini Live turn can complete without ending the live session.
                # Keep the browser WebSocket alive for the next turn.
                while True:
                    saw_any = False
                    async for response in session.receive():
                        saw_any = True
                        server_content = getattr(response, "server_content", None)
                        if server_content is None:
                            continue

                        if getattr(server_content, "interrupted", False):
                            await websocket.send_json({"type": "interrupted"})
                            continue

                        input_tx = getattr(server_content, "input_transcription", None)
                        if input_tx is not None:
                            text = getattr(input_tx, "text", None)
                            if text:
                                await websocket.send_json({
                                    "type": "input_transcript",
                                    "text": text,
                                    "final": True,
                                })

                        interim_tx = getattr(server_content, "interim_input_transcription", None)
                        if interim_tx is not None:
                            text = getattr(interim_tx, "text", None)
                            if text:
                                await websocket.send_json({
                                    "type": "input_transcript",
                                    "text": text,
                                    "final": False,
                                })

                        output_tx = getattr(server_content, "output_transcription", None)
                        if output_tx is not None:
                            text = getattr(output_tx, "text", None)
                            if text:
                                await websocket.send_json({
                                    "type": "output_transcript",
                                    "text": text,
                                })

                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn is not None:
                            for part in getattr(model_turn, "parts", []) or []:
                                inline = getattr(part, "inline_data", None)
                                if inline is None:
                                    continue
                                data = getattr(inline, "data", None)
                                if data:
                                    if isinstance(data, str):
                                        data = base64.b64decode(data)
                                    await websocket.send_bytes(data)

                        if getattr(server_content, "turn_complete", False):
                            await websocket.send_json({"type": "turn_complete"})

                    if not saw_any:
                        await asyncio.sleep(0.01)

            forward_task = asyncio.create_task(browser_to_gemini())
            receive_task = asyncio.create_task(gemini_to_browser())
            try:
                # The browser task owns the WebSocket lifetime. A completed Gemini
                # turn must NOT tear down the session; only browser disconnect/close does.
                await forward_task
            finally:
                if not receive_task.done():
                    receive_task.cancel()
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass
                elif receive_task.exception():
                    raise receive_task.exception()

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        print("LIVE VOICE ERROR:", repr(exc))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    print("=" * 64)
    print("MONSTER LIVE VOICE GATEWAY")
    print("=" * 64)
    print("Model:", LIVE_MODEL)
    print("Env  :", ENV_FILE)
    print("URL  :", f"ws://{HOST}:{PORT}/live")
    print("Health:", f"http://{HOST}:{PORT}/health")
    uvicorn.run(app, host=HOST, port=PORT)
