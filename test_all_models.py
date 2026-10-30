"""
FULL MODEL TEST — 12,411 models (from all_models_list.json)
"""
import asyncio
import json
import os
import sys
import time
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")

RESULT_FILE = "full_test_results.json"
ALL_MODELS_FILE = "all_models_list.json"

CONCURRENCY = 40
TIMEOUT = 8.0
SAVE_EVERY = 100


# ═══════════════════════════════════════════════════════════
# Non-chat filters
# ═══════════════════════════════════════════════════════════
SKIP_KEYWORDS = [
    "whisper", "tts", "text-to-speech", "embed-", "embedding",
    "rerank", "moderation", "dall-e", "dalle-", "flux", "sdxl",
    "sd3", "stable-diffusion", "imagen", "nano-banana", "seedream",
    "seedance", "veo", "sora-", "-sora", "kling", "runway",
    "gen-3", "gen-4", "wan2", "hunyuan-video", "ltx-video",
    "luma-", "hailuo", "t2v", "i2v", "v2v", "music-", "udio",
    "voice-clone", "voice-design", "image-01", "fibo_edit",
    "z-image", "gpt4o-image", "robotics", "guard-", "-guard",
    "safeguard", "computer-use", "transcribe", "lyria",
    "image-to-image", "text-to-image", "text-to-video",
    "image-to-video", "sound-effect", "speech-to-text",
]

SKIP_PREFIXES = [
    "aihorde/", "horde/", "segmind/", "firefly/", "adobe-firefly/",
    "runway/", "runwayml/", "veo-free/", "veoaifree-web/",
    "ollama-search/", "serper-search/", "tavily-search/", "jules/",
    "kie/",  # mostly image/video/audio
]


def is_skip(mid):
    ml = mid.lower()
    if any(ml.startswith(p) for p in SKIP_PREFIXES):
        return True
    if any(k in ml for k in SKIP_KEYWORDS):
        return True
    return False


# ═══════════════════════════════════════════════════════════
# Load / Save results
# ═══════════════════════════════════════════════════════════
def load_results():
    if not os.path.exists(RESULT_FILE):
        return {"working": {}, "broken": {}, "tested_at": None}
    try:
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"working": {}, "broken": {}, "tested_at": None}


def save_results(data):
    try:
        tmp = RESULT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RESULT_FILE)
    except Exception as e:
        print(f"⚠️ Save error: {e}")


# ═══════════════════════════════════════════════════════════
# Test one model
# ═══════════════════════════════════════════════════════════
async def test_one(sem, mid, results_lock, stats):
    import httpx

    async with sem:
        async with results_lock:
            if mid in stats["data"]["working"] or mid in stats["data"]["broken"]:
                stats["skipped"] += 1
                stats["done"] += 1
                return

        url = BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": mid,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
        t0 = time.time()
        ok = False
        reason = ""
        latency = 0.0

        try:
            t = httpx.Timeout(connect=3.0, read=TIMEOUT, write=5.0, pool=3.0)
            async with httpx.AsyncClient(timeout=t) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as r:
                    if r.status_code != 200:
                        err = (await r.aread()).decode("utf-8", errors="ignore")[:120]
                        reason = f"HTTP {r.status_code}"
                    else:
                        try:
                            async for line in r.aiter_lines():
                                if line.startswith("data:"):
                                    raw = line[5:].strip()
                                    if raw and raw != "[DONE]":
                                        ok = True
                                        latency = round(time.time() - t0, 2)
                                        break
                        except asyncio.TimeoutError:
                            reason = "timeout"
                        if not ok and not reason:
                            reason = "empty"
        except httpx.ConnectError:
            reason = "connect error"
        except asyncio.TimeoutError:
            reason = "timeout"
        except Exception as e:
            reason = type(e).__name__

        async with results_lock:
            if ok:
                stats["data"]["working"][mid] = latency
                stats["ok_count"] += 1
            else:
                stats["data"]["broken"][mid] = reason
                stats["broken_count"] += 1

            stats["done"] += 1
            total = stats["total"]
            done = stats["done"]

            if done % 50 == 0 or done == total:
                elapsed = time.time() - stats["start_time"]
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(
                    f"  [{done:>6}/{total}] "
                    f"✅ {stats['ok_count']:>5} | "
                    f"❌ {stats['broken_count']:>5} | "
                    f"⏭ {stats['skipped']:>5} | "
                    f"{rate:.1f}/s | ETA {eta/60:.1f}m",
                    flush=True,
                )

            if done % SAVE_EVERY == 0:
                stats["data"]["tested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                save_results(stats["data"])
                print(f"  💾 Saved ({done} tested)", flush=True)


# ═══════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════
def print_results(data):
    working = data.get("working", {})
    broken = data.get("broken", {})

    print(f"\n✅ Working: {len(working):,}")
    print(f"❌ Broken:  {len(broken):,}")
    total = len(working) + len(broken)
    if total > 0:
        print(f"📊 Success: {len(working)/total*100:.1f}%")

    top = sorted(working.items(), key=lambda x: x[1])[:30]
    print("\n⚡ Top 30 fastest:")
    for mid, lat in top:
        print(f"   {lat:>6.2f}s  {mid}")

    working_prefixes = Counter(m.split("/")[0] + "/" for m in working)
    print("\n📦 Working per provider (top 20):")
    for prefix, count in working_prefixes.most_common(20):
        print(f"   {prefix:25} {count:>5}")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════
async def main():
    if not API_KEY:
        print("❌ OMNIROUTE_API_KEY missing in .env")
        sys.exit(1)

    if not os.path.exists(ALL_MODELS_FILE):
        print(f"❌ {ALL_MODELS_FILE} not found")
        print("   Run this first: python -c \"import json,httpx,os;from dotenv import load_dotenv;load_dotenv();r=httpx.get(os.getenv('OMNIROUTE_BASE_URL','http://127.0.0.1:20128/v1').rstrip('/')+'/models',headers={'Authorization':f'Bearer {os.getenv(\\\"OMNIROUTE_API_KEY\\\")}'});json.dump([m['id'] for m in r.json()['data']],open('all_models_list.json','w'))\"")
        sys.exit(1)

    with open(ALL_MODELS_FILE, "r", encoding="utf-8") as f:
        raw_models = json.load(f)

    all_models = sorted(m for m in raw_models if not is_skip(m))
    total_available = len(all_models)

    print("=" * 70)
    print("🚀 FULL MODEL TEST")
    print("=" * 70)
    print(f"📊 Total in all_models_list.json: {len(raw_models):,}")
    print(f"📊 Chat-capable (after filter):   {total_available:,}")

    data = load_results()
    working_prev = set(data.get("working", {}).keys())
    broken_prev = set(data.get("broken", {}).keys())
    print(f"\n💾 Previously tested: {len(working_prev) + len(broken_prev):,}")
    print(f"   ✅ Working: {len(working_prev):,}")
    print(f"   ❌ Broken:  {len(broken_prev):,}")

    remaining = [m for m in all_models if m not in working_prev and m not in broken_prev]
    print(f"\n🎯 Remaining to test: {len(remaining):,}")

    if not remaining:
        print("\n✅ All models already tested!")
        print_results(data)
        return

    est_sec = len(remaining) * TIMEOUT / CONCURRENCY
    print(f"\n⏱️  Estimated: {est_sec/60:.0f} min (worst) — {est_sec/60/3:.0f} min (best)")

    ans = input("\n▶️  Start test? [y/N]: ").strip().lower()
    if ans != "y":
        print("Cancelled.")
        return

    stats = {
        "data": data,
        "total": total_available,
        "done": 0,
        "ok_count": len(working_prev),
        "broken_count": len(broken_prev),
        "skipped": 0,
        "start_time": time.time(),
    }

    results_lock = asyncio.Lock()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n🔬 Testing {len(remaining):,} models (concurrency={CONCURRENCY}, timeout={TIMEOUT}s)...")
    print("=" * 70)

    tasks = [test_one(sem, mid, results_lock, stats) for mid in remaining]
    await asyncio.gather(*tasks, return_exceptions=True)

    stats["data"]["tested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_results(stats["data"])

    print("\n" + "=" * 70)
    print("🎉 DONE!")
    print("=" * 70)
    print_results(stats["data"])


if __name__ == "__main__":
    asyncio.run(main())