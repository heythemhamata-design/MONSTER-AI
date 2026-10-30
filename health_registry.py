# =========================================================
# Model Health Registry + Circuit Breaker
# =========================================================
import json
import os
import time
import asyncio
import httpx
from typing import Dict, Any, List, Optional

HEALTH_FILE = "model_health.json"
FAIL_THRESHOLD = 3          # بعد كم فشل يُفتح الـ circuit
COOLDOWN_SECONDS = 300      # مدة الإغلاق (5 دقائق)
FIRST_TOKEN_TIMEOUT = 15.0  # ثوانٍ لأول token
HEALTH_TIMEOUT = 12.0       # ثوانٍ لفحص صحة الموديل


def load_health() -> Dict[str, Any]:
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_health(data: Dict[str, Any]) -> None:
    try:
        tmp = HEALTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HEALTH_FILE)
    except Exception as e:
        print(f"[HEALTH] save error: {e}")


def get_status(model: str) -> Dict[str, Any]:
    data = load_health()
    return data.get(model, {
        "status": "unknown",
        "fail_count": 0,
        "last_ok": None,
        "last_fail": None,
        "last_latency": None,
        "cooldown_until": 0,
    })


def is_circuit_open(model: str) -> bool:
    """هل الموديل مُغلق حالياً (لا يجب تجريبه)؟"""
    s = get_status(model)
    if s.get("status") == "open":
        if time.time() < s.get("cooldown_until", 0):
            return True
        # انتهى الـ cooldown → half-open (يُجرَّب مرة واحدة)
    return False


def record_success(model: str, latency: float) -> None:
    data = load_health()
    data[model] = {
        "status": "closed",
        "fail_count": 0,
        "last_ok": time.time(),
        "last_fail": data.get(model, {}).get("last_fail"),
        "last_latency": round(latency, 2),
        "cooldown_until": 0,
    }
    save_health(data)


def record_failure(model: str, reason: str = "") -> None:
    data = load_health()
    prev = data.get(model, {})
    fail_count = prev.get("fail_count", 0) + 1
    entry = {
        "status": "open" if fail_count >= FAIL_THRESHOLD else "degraded",
        "fail_count": fail_count,
        "last_ok": prev.get("last_ok"),
        "last_fail": time.time(),
        "last_latency": prev.get("last_latency"),
        "cooldown_until": time.time() + COOLDOWN_SECONDS if fail_count >= FAIL_THRESHOLD else 0,
        "last_reason": reason[:200],
    }
    data[model] = entry
    save_health(data)


async def health_check_one(base_url: str, api_key: str, model: str) -> Dict[str, Any]:
    """فحص موديل واحد برسالة صغيرة + انتظار أول token."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    t0 = time.time()
    try:
        timeout = httpx.Timeout(connect=5.0, read=HEALTH_TIMEOUT, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as r:
                if r.status_code != 200:
                    err = (await r.aread()).decode("utf-8", errors="ignore")[:200]
                    return {"model": model, "ok": False, "reason": f"HTTP {r.status_code}: {err}",
                            "latency": round(time.time() - t0, 2)}

                # ننتظر أول token فقط ثم نُغلق الاتصال
                try:
                    async for line in r.aiter_lines():
                        if line.startswith("data:"):
                            raw = line[5:].strip()
                            if raw and raw != "[DONE]":
                                latency = round(time.time() - t0, 2)
                                return {"model": model, "ok": True, "latency": latency}
                except asyncio.TimeoutError:
                    return {"model": model, "ok": False, "reason": "first-token timeout",
                            "latency": round(time.time() - t0, 2)}

                return {"model": model, "ok": False, "reason": "empty stream",
                        "latency": round(time.time() - t0, 2)}
    except Exception as e:
        return {"model": model, "ok": False, "reason": f"{type(e).__name__}: {e}",
                "latency": round(time.time() - t0, 2)}


async def health_check_all(base_url: str, api_key: str, models: List[str],
                           concurrency: int = 8) -> List[Dict[str, Any]]:
    """فحص متوازي لكل الموديلات."""
    sem = asyncio.Semaphore(concurrency)

    async def worker(m):
        async with sem:
            return await health_check_one(base_url, api_key, m)

    results = await asyncio.gather(*(worker(m) for m in models), return_exceptions=True)
    clean = []
    for m, r in zip(models, results):
        if isinstance(r, Exception):
            r = {"model": m, "ok": False, "reason": str(r), "latency": 0}
        clean.append(r)
        # حدّث الـ registry
        if r["ok"]:
            record_success(m, r["latency"])
        else:
            # لا نُفعّل circuit breaker من الفحص — فقط نسجّل
            data = load_health()
            prev = data.get(m, {})
            data[m] = {
                "status": "degraded" if not r["ok"] else "closed",
                "fail_count": prev.get("fail_count", 0),
                "last_ok": prev.get("last_ok"),
                "last_fail": time.time() if not r["ok"] else prev.get("last_fail"),
                "last_latency": r["latency"] if r["ok"] else prev.get("last_latency"),
                "cooldown_until": prev.get("cooldown_until", 0),
                "last_reason": r.get("reason", "")[:200],
            }
            save_health(data)
    return clean