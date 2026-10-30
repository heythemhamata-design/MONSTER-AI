# -*- coding: utf-8 -*-
"""MONSTER AI Server — OmniRoute + Local Voice Edition.

Full server implementation with bounded first-token waiting and automatic
fallback when a provider returns an empty or stalled SSE stream.
"""

import os
import json
import uuid
import time
import asyncio
import base64
import traceback
from typing import List, Optional, Dict, Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
    FileResponse,
    JSONResponse,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")
CATALOG_FILE = os.path.join(BASE_DIR, "catalog.json")
OMNIROUTE_BASE_URL = os.getenv(
    "OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1"
).rstrip("/")
OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY", "").strip()
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "auto/smart").strip() or "auto/smart"
MONSTER_VOICE_URL = os.getenv(
    "MONSTER_VOICE_URL", "http://127.0.0.1:8010"
).rstrip("/")
LOG_PREFIX = "[MONSTER]"

# Timeout for the first *assistant text*, not merely the first SSE event.
FIRST_TEXT_TIMEOUT_SECONDS = 12.0
CONNECT_TIMEOUT_SECONDS = 8.0
READ_TIMEOUT_SECONDS = 45.0
MAX_FALLBACK_ATTEMPTS = 6


def print_banner() -> None:
    print("=" * 68)
    print("  MONSTER AI Server - OmniRoute + Local Voice Edition v3.1")
    print("=" * 68)
    if not OMNIROUTE_API_KEY:
        print("  ERROR: OMNIROUTE_API_KEY is missing from the environment.")
        print("  Add these lines to C:\\OmniChat\\.env:")
        print("      OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1")
        print("      OMNIROUTE_API_KEY=sk-9b0b9fd2f800659e-578873-ebaf4461")
        print("=" * 68)
        raise SystemExit(1)
    masked = (
        f"{OMNIROUTE_API_KEY[:5]}...{OMNIROUTE_API_KEY[-4:]}"
        if len(OMNIROUTE_API_KEY) > 12 else "***"
    )
    print(f"  OmniRoute URL : {OMNIROUTE_BASE_URL}")
    print(f"  API Key       : {masked}")
    print(f"  Default Model : {DEFAULT_MODEL}")
    print(f"  Database      : {DB_FILE}")
    print(f"  Local Voice   : {MONSTER_VOICE_URL}")
    print("=" * 68)


print_banner()


# ---------------------------------------------------------------------------
# System instruction — UTF-8 (the pasted version had mojibake)
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """أنت MONSTER AI، مساعد ذكاء اصطناعي طوّره هيثم حماتة.
شخصيتك: ذكي، محترف، مباشر، ودقيق.
اللغة: أجب بلغة المستخدم نفسها، سواء العربية أو الدارجة أو الفرنسية أو الإنجليزية.
تخصصك: البرمجة، الذكاء الاصطناعي، الأتمتة، وواجهات API وسير العمل والتحليل التقني.
لا تخترع نتائج الأدوات أو الاختبارات. إذا لم تتمكن من التحقق من شيء فاذكر ذلك بوضوح."""


# ---------------------------------------------------------------------------
# Known-good fallback candidates
# Based on the repository's previously saved health_report.json. The live
# availability can change, so every candidate is still verified by response.
# ---------------------------------------------------------------------------
SAFE_MODELS: List[str] = [
    "glm/glm-5.3",
    "pol/kimi-k3",
    "pol/gpt-oss",
    "pol/deepseek-pro",
    "pol/gpt-5.6-luna",
    "pol/glm-5.3",
    "glm/glm-5.3-flash",
    "glm/glm-5.2",
    "pol/llama",
    "pol/command-a-plus",
]

SMART_CATEGORIES: Dict[str, List[str]] = {
    "smart": [
        "glm/glm-5.3",
        "pol/kimi-k3",
        "pol/gpt-oss",
        "pol/deepseek-pro",
        "pol/gpt-5.6-luna",
        "pol/glm-5.3",
        "glm/glm-5.3-flash",
        "glm/glm-5.2",
    ],
    "coding": [
        "pol/kimi-k3",
        "pol/deepseek-pro",
        "glm/glm-5.3",
        "glm/glm-5.2",
        "pol/gpt-oss",
        "pol/command-a-plus",
    ],
    "rapid": [
        "glm/glm-5.3-flash",
        "glm/glm-5.2",
        "pol/gpt-oss",
        "pol/deepseek-pro",
        "pol/gpt-5.6-luna",
    ],
    "vision": [
        "agy/gemini-3.1-pro-high",
        "agy/gemini-3.7-flash-high",
        "pol/gpt-5.6-luna",
        "pol/gpt-oss",
    ],
}

FALLBACK_CHAINS: Dict[str, List[str]] = {
    "auto/smart": SMART_CATEGORIES["smart"],
    "auto/coding": SMART_CATEGORIES["coding"],
    "auto/fast": SMART_CATEGORIES["rapid"],
    "auto/rapid": SMART_CATEGORIES["rapid"],
    "auto/reasoning": [
        "pol/kimi-k3", "pol/deepseek-pro", "glm/glm-5.3", "pol/gpt-oss"
    ],
    "auto/vision": SMART_CATEGORIES["vision"],
    "auto/cheap": ["pol/gpt-oss", "pol/gpt-5.6-luna", "glm/glm-5.3"],
    "auto/balanced": SMART_CATEGORIES["smart"],
}

FALLBACK_KEYWORDS = (
    "not available", "not found", "no active credentials", "invalid model",
    "bad_request", "model does not exist", "unknown model", "no such model",
    "unsupported model", "model not supported", "not supported",
    "model_not_supported", "enough credits", "out of credits", "top up",
    "quota", "insufficient", "payment required", "rate limit", "rate-limit",
    "429", "resource_exhausted",
)
RATE_OR_QUOTA_TERMS = (
    "too many requests", "rate limit", "rate-limit", "rate_limit",
    "rate_limit_exceeded", "resource_exhausted", "429", "quota",
    "top up", "credits", "payment required", "insufficient",
)
RETRYABLE_HTTP_STATUSES = {400, 401, 402, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def load_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {"conversations": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"conversations": {}}
        if not isinstance(data.get("conversations"), dict):
            data["conversations"] = {}
        return data
    except Exception as exc:
        print(f"{LOG_PREFIX} DB read error: {exc}", flush=True)
        return {"conversations": {}}


def save_db(data: Dict[str, Any]) -> None:
    try:
        tmp_path = DB_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DB_FILE)
    except Exception as exc:
        print(f"{LOG_PREFIX} DB write error: {exc}", flush=True)


def extract_title_from_messages(messages: List[Dict[str, Any]]) -> Optional[str]:
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()[:50]
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    value = str(part.get("text") or "").strip()
                    if value:
                        return value[:50]
    return None


def _conversation_title(messages: List[Dict[str, Any]]) -> Optional[str]:
    title = extract_title_from_messages(messages)
    if not title:
        return None
    return title[:30] + ("..." if len(title) > 30 else "")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class FileUploadModel(BaseModel):
    filename: str
    mime_type: str
    data: str
    conversation_id: Optional[str] = None


class MessagesSaveModel(BaseModel):
    messages: List[Dict[str, Any]]


class ChatRequestModel(BaseModel):
    model: str = Field(default="auto/smart")
    conversation_id: Optional[str] = None
    messages: List[Dict[str, Any]]
    stream: bool = True


class VoiceSpeakModel(BaseModel):
    text: str = Field(min_length=1)
    language: str = Field(default="ar")


# ---------------------------------------------------------------------------
# FastAPI app and middleware
# ---------------------------------------------------------------------------
app = FastAPI(title="MONSTER AI Server", version="3.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Simple in-memory provider cooldown
# ---------------------------------------------------------------------------
PROVIDER_COOLDOWN_SECONDS = 60
_provider_cooldown: Dict[str, float] = {}


def _get_provider(model_id: str) -> str:
    return model_id.split("/", 1)[0] if "/" in model_id else model_id


def _provider_is_cooling(model_id: str) -> bool:
    return _provider_cooldown.get(_get_provider(model_id), 0.0) > time.time()


def _cool_down_provider(model_id: str, seconds: int = PROVIDER_COOLDOWN_SECONDS) -> None:
    provider = _get_provider(model_id)
    _provider_cooldown[provider] = max(
        _provider_cooldown.get(provider, 0.0), time.time() + seconds
    )
    print(f"{LOG_PREFIX} Provider '{provider}' cooling down for {seconds}s", flush=True)


def _resolve_chain(model_name: str) -> List[str]:
    name = (model_name or "").strip()
    if name in SMART_CATEGORIES:
        return list(SMART_CATEGORIES[name])
    if name in {"", "auto", "smart", "auto/smart"}:
        return list(SMART_CATEGORIES["smart"])
    if name.startswith("auto/") and name in FALLBACK_CHAINS:
        return list(FALLBACK_CHAINS[name])
    chain = [name]
    chain.extend(FALLBACK_CHAINS.get(name, []))
    chain.extend(SAFE_MODELS)
    return list(dict.fromkeys(m for m in chain if m))


def _get_candidates(model_name: str, already_tried: List[str]) -> List[str]:
    requested = (model_name or DEFAULT_MODEL or "auto/smart").strip()
    base = _resolve_chain(requested)

    # For auto modes, prefer the tested candidate list, then retain any
    # category-specific candidates not present in the tested list.
    if requested in {"auto", "auto/smart", "smart"}:
        ordered = list(SMART_CATEGORIES["smart"]) + SAFE_MODELS + base
    elif requested in SMART_CATEGORIES:
        ordered = base + SAFE_MODELS
    elif requested.startswith("auto/"):
        ordered = base + SAFE_MODELS
    else:
        ordered = [requested] + base[1:] + SAFE_MODELS

    tried = set(already_tried)
    unique: List[str] = []
    for candidate in ordered:
        if candidate and candidate not in tried and candidate not in unique:
            unique.append(candidate)

    available = [m for m in unique if not _provider_is_cooling(m)]
    if not available:
        # Do not get stuck just because every provider is cooling down.
        available = unique
    return available[:MAX_FALLBACK_ATTEMPTS]


# ---------------------------------------------------------------------------
# Health/status endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    voice_ok = False
    try:
        timeout = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{MONSTER_VOICE_URL}/health")
        voice_ok = response.status_code == 200
    except Exception:
        voice_ok = False
    return {
        "status": "ok",
        "omniroute_url": OMNIROUTE_BASE_URL,
        "api_key_configured": bool(OMNIROUTE_API_KEY),
        "default_model": DEFAULT_MODEL,
        "categories": list(SMART_CATEGORIES.keys()),
        "local_voice": {"url": MONSTER_VOICE_URL, "online": voice_ok},
    }


@app.get("/api/voice/status")
async def voice_status():
    try:
        timeout = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{MONSTER_VOICE_URL}/health")
        if response.status_code != 200:
            return JSONResponse(content={
                "ok": False, "configured": False, "voice_id": None,
                "error": f"Voice server returned HTTP {response.status_code}",
            })
        data = response.json()
        return {
            "ok": True,
            "configured": data.get("status") == "ok",
            "voice_id": "local",
            "device": data.get("device"),
            "model": data.get("model", "chatterbox-multilingual"),
        }
    except httpx.ConnectError:
        return {
            "ok": False, "configured": False, "voice_id": None,
            "error": f"Local voice server is offline. Expected: {MONSTER_VOICE_URL}",
        }
    except Exception as exc:
        return {"ok": False, "configured": False, "voice_id": None, "error": str(exc)}


@app.post("/api/voice/speak")
async def voice_speak(req: VoiceSpeakModel):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    language = (req.language or "ar").strip().lower()
    if language not in {"ar", "en", "fr"}:
        language = "ar"
    print(f"{LOG_PREFIX} TTS request lang={language} chars={len(text)}", flush=True)
    try:
        timeout = httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{MONSTER_VOICE_URL}/speak",
                json={"text": text, "language": language},
            )
        if response.status_code != 200:
            error_text = response.text[:1500] or "Unknown voice server error"
            raise HTTPException(status_code=502, detail=f"Local voice server error: {error_text}")
        if not response.content:
            raise HTTPException(status_code=502, detail="Voice server returned empty audio")
        return Response(
            content=response.content,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Content-Disposition": 'inline; filename="monster_voice.wav"',
            },
        )
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Local voice server is offline.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Local voice generation timed out.")
    except Exception as exc:
        print(f"{LOG_PREFIX} TTS exception: {exc}", flush=True)
        raise HTTPException(status_code=502, detail=f"Voice generation failed: {exc}")


# ---------------------------------------------------------------------------
# Conversations API
# ---------------------------------------------------------------------------
@app.get("/api/conversations")
async def get_conversations():
    db = load_db()
    convs = list(db["conversations"].values())
    convs.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return convs


@app.post("/api/conversations")
async def create_conversation():
    db = load_db()
    cid = str(uuid.uuid4())
    now = time.time()
    conversation = {
        "id": cid,
        "title": "New Conversation",
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    db["conversations"][cid] = conversation
    save_db(db)
    return conversation


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return db["conversations"][cid]


@app.post("/api/conversations/{cid}/messages")
async def save_messages(cid: str, req: MessagesSaveModel):
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = db["conversations"][cid]
    conv["messages"] = req.messages
    conv["updated_at"] = time.time()
    if conv.get("title") in (None, "", "New Conversation"):
        title = _conversation_title(req.messages)
        if title:
            conv["title"] = title
    db["conversations"][cid] = conv
    save_db(db)
    return {"status": "success", "conversation": conv}


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    db = load_db()
    if cid in db["conversations"]:
        del db["conversations"][cid]
        save_db(db)
        return {"status": "deleted", "id": cid}
    return {"status": "not_found", "id": cid}


# ---------------------------------------------------------------------------
# Files API
# ---------------------------------------------------------------------------
@app.post("/api/files")
async def upload_file(file_req: FileUploadModel):
    extracted_text = ""
    if not file_req.mime_type.startswith("image/"):
        try:
            encoded = file_req.data.split(",", 1)[1] if "," in file_req.data else file_req.data
            extracted_text = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        except Exception as exc:
            extracted_text = f"[Could not parse file content: {exc}]"
    return {
        "filename": file_req.filename,
        "mime_type": file_req.mime_type,
        "extracted_text": extracted_text,
    }


# ---------------------------------------------------------------------------
# OmniRoute streaming engine — fallback on status errors, timeout, or empty SSE
# ---------------------------------------------------------------------------
def _extract_delta_content(data: Dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta") or {}
    if not isinstance(delta, dict):
        return ""
    content = (
        delta.get("content")
        or delta.get("reasoning_content")
        or delta.get("reasoning")
        or delta.get("thinking")
        or ""
    )
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        )
    return content if isinstance(content, str) else str(content or "")


async def call_omniroute_stream(
    messages_history: list,
    model_name: str,
    _depth: int = 0,
    _tried: Optional[list] = None,
):
    """Yield ('badge', model) and ('text', chunk); retry models before first text."""
    tried = list(_tried or [])
    candidates = _get_candidates(model_name, tried)
    if not candidates:
        raise Exception(f"No untried OmniRoute model candidates remain for '{model_name}'.")

    payload_messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    for message in messages_history:
        if isinstance(message, dict):
            payload_messages.append({
                "role": message.get("role", "user"),
                "content": message.get("content", ""),
            })

    endpoint = f"{OMNIROUTE_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OMNIROUTE_API_KEY}",
        "Accept": "text/event-stream",
    }
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=READ_TIMEOUT_SECONDS,
        write=30.0,
        pool=8.0,
    )
    failures: List[str] = []

    for index, selected_model in enumerate(candidates):
        tried.append(selected_model)
        yield ("badge", selected_model if index == 0 else f"{selected_model} (fallback)")
        print(
            f"{LOG_PREFIX} Trying model {selected_model} ({index + 1}/{len(candidates)})",
            flush=True,
        )

        payload = {
            "model": selected_model,
            "messages": payload_messages,
            "stream": True,
        }
        received_text = False
        stream_error = ""
        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", endpoint, headers=headers, json=payload
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="ignore")
                        body_lower = body.lower()
                        stream_error = f"HTTP {response.status_code}: {body[:350]}"
                        retryable = (
                            response.status_code in RETRYABLE_HTTP_STATUSES
                            or any(term in body_lower for term in FALLBACK_KEYWORDS)
                        )
                        if not retryable:
                            raise Exception(f"OmniRoute returned {stream_error}")
                        failures.append(f"{selected_model}: {stream_error}")
                        if (
                            response.status_code in {401, 402, 403, 429}
                            or any(term in body_lower for term in RATE_OR_QUOTA_TERMS)
                        ):
                            _cool_down_provider(selected_model)
                    else:
                        iterator = response.aiter_lines().__aiter__()
                        while True:
                            try:
                                if not received_text:
                                    remaining = FIRST_TEXT_TIMEOUT_SECONDS - (
                                        time.monotonic() - start_time
                                    )
                                    if remaining <= 0:
                                        stream_error = (
                                            "No assistant text within "
                                            f"{FIRST_TEXT_TIMEOUT_SECONDS:.0f}s"
                                        )
                                        break
                                    line = await asyncio.wait_for(
                                        iterator.__anext__(), timeout=remaining
                                    )
                                else:
                                    line = await iterator.__anext__()
                            except StopAsyncIteration:
                                break
                            except asyncio.TimeoutError:
                                stream_error = (
                                    "No assistant text within "
                                    f"{FIRST_TEXT_TIMEOUT_SECONDS:.0f}s"
                                )
                                break

                            if not line or not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if not raw:
                                continue
                            if raw == "[DONE]":
                                break
                            try:
                                event = json.loads(raw)
                            except json.JSONDecodeError:
                                continue

                            if event.get("error"):
                                error_text = json.dumps(event["error"], ensure_ascii=False)
                                if received_text:
                                    raise Exception(
                                        "Upstream error after partial output; refusing to mix "
                                        f"answers from different models: {error_text[:300]}"
                                    )
                                stream_error = error_text[:350]
                                if any(term in error_text.lower() for term in RATE_OR_QUOTA_TERMS):
                                    _cool_down_provider(selected_model)
                                break

                            content = _extract_delta_content(event)
                            if not content:
                                continue

                            lower_content = content.lower()
                            provider_error = (
                                not received_text
                                and len(content) < 1200
                                and any(term in lower_content for term in RATE_OR_QUOTA_TERMS)
                            )
                            if provider_error:
                                stream_error = content[:350]
                                _cool_down_provider(selected_model)
                                break

                            received_text = True
                            yield ("text", content)

            # This check is essential: HTTP 200 + empty stream is not success.
            if received_text:
                return
            if not stream_error:
                stream_error = "HTTP 200 stream ended without assistant text"
            failures.append(f"{selected_model}: {stream_error}")
            print(
                f"{LOG_PREFIX} {selected_model}: {stream_error}; trying next model",
                flush=True,
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if received_text:
                # Never restart another model after emitting text to the client.
                raise Exception(
                    f"Stream from '{selected_model}' failed after partial output: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            stream_error = f"{type(exc).__name__}: {exc}"
            failures.append(f"{selected_model}: {stream_error}")
            if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
                _cool_down_provider(selected_model)
            print(
                f"{LOG_PREFIX} {selected_model}: {stream_error}; trying next model",
                flush=True,
            )

    raise Exception(
        f"All {len(candidates)} model attempts failed for '{model_name}'. "
        f"Last errors: {' | '.join(failures[-4:]) or 'No usable response'}"
    )


# ---------------------------------------------------------------------------
# Streaming generator and chat endpoint
# ---------------------------------------------------------------------------
async def ai_stream_generator(
    cid: Optional[str], full_history: list, model_name: str
):
    accumulated_text = ""
    try:
        async for kind, value in call_omniroute_stream(full_history, model_name):
            if kind == "badge":
                yield "data: " + json.dumps(
                    {"__model_badge__": value}, ensure_ascii=False
                ) + "\n\n"
            elif kind == "text":
                accumulated_text += value
                yield "data: " + json.dumps(
                    {"choices": [{"delta": {"content": value}}]},
                    ensure_ascii=False,
                ) + "\n\n"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print("=" * 68, flush=True)
        print(f"{LOG_PREFIX} STREAM EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        print("=" * 68, flush=True)
        error_message = f"\n\n[MONSTER AI error: {type(exc).__name__}: {exc}]"
        accumulated_text += error_message
        yield "data: " + json.dumps(
            {"choices": [{"delta": {"content": error_message}}]},
            ensure_ascii=False,
        ) + "\n\n"

    yield "data: [DONE]\n\n"

    if cid and accumulated_text.strip():
        db = load_db()
        if cid in db["conversations"]:
            conversation = db["conversations"][cid]
            history_to_save = list(full_history)
            history_to_save.append({"role": "assistant", "content": accumulated_text})
            conversation["messages"] = history_to_save
            conversation["updated_at"] = time.time()
            if conversation.get("title") in (None, "", "New Conversation"):
                title = _conversation_title(history_to_save)
                if title:
                    conversation["title"] = title
            db["conversations"][cid] = conversation
            save_db(db)


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequestModel, request: Request):
    async def cancellable_stream():
        try:
            async for chunk in ai_stream_generator(
                req.conversation_id, req.messages, req.model
            ):
                if await request.is_disconnected():
                    print(f"{LOG_PREFIX} Client disconnected; stopping stream", flush=True)
                    break
                yield chunk
        except asyncio.CancelledError:
            print(f"{LOG_PREFIX} Stream cancelled by client", flush=True)
            raise

    return StreamingResponse(
        cancellable_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Static files, logo, and model catalog
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_index():
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>index.html not found!</h1>", status_code=404)


@app.get("/api/models/catalog")
async def get_catalog():
    if not os.path.exists(CATALOG_FILE):
        raise HTTPException(status_code=404, detail="catalog.json not found. Run build_catalog.py first.")
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as handle:
            return JSONResponse(content=json.load(handle))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Catalog read error: {exc}")


@app.get("/api/models/categories")
async def get_categories():
    if not os.path.exists(CATALOG_FILE):
        # Provide the same known categories even if catalog.json is absent.
        return {"categories": SMART_CATEGORIES, "counts": {k: len(v) for k, v in SMART_CATEGORIES.items()}}
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        return JSONResponse(content={
            "categories": catalog.get("categories", SMART_CATEGORIES),
            "counts": catalog.get("counts", {}),
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Catalog read error: {exc}")


@app.get("/api/models/providers")
async def get_providers():
    if not os.path.exists(CATALOG_FILE):
        return {"providers": []}
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        providers = [
            {key: value for key, value in provider.items() if key != "models"}
            for provider in catalog.get("providers", [])
            if isinstance(provider, dict)
        ]
        return JSONResponse(content={"providers": providers})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Catalog read error: {exc}")


@app.get("/monster_logo.png")
async def serve_logo():
    for filename in ("monster_logo.png", "monster_logo.png.png"):
        path = os.path.join(BASE_DIR, filename)
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)


@app.get("/favicon.ico")
async def serve_favicon():
    for filename in ("monster_logo.png", "monster_logo.png.png"):
        path = os.path.join(BASE_DIR, filename)
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
