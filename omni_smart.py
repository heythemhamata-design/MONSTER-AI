"""
OMNIROUTE SMART ROUTER
- يقرأ prefix_inventory.json
- يختار أفضل ~150 مرشح من 13,689
- يختبرها فعلياً (parallel)
- ينتج auto_routes.json + تقرير كامل
"""
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")

# ═══════════════════════════════════════════════════════════
# ترتيب المزودين (الأفضل أولاً) — يُستعمل للترجيح
# ═══════════════════════════════════════════════════════════
PROVIDER_RANK = {
    # الدرجة 1: مجاني، سريع، موثوق
    "pol/": 1, "pollinations/": 1,

    # الدرجة 2: premium مباشر (Claude/Gemini/OpenAI)
    "agy/": 2, "gemini/": 2, "openai/": 2,
    "gh/": 2, "github/": 2,

    # الدرجة 3: providers سريعة جداً
    "cerebras/": 3, "groq/": 3,

    # الدرجة 4: OpenAI-compatible معروفين
    "glm/": 4, "zc/": 4, "moonshot/": 4, "minimax/": 4,
    "xai-oauth/": 4, "xao/": 4,

    # الدرجة 5: بوابات كبيرة
    "openrouter/": 5, "nvidia/": 5, "deepinfra/": 5,
    "nanogpt/": 5, "friendli/": 5, "friendliai/": 5,
    "ollamacloud/": 5, "ollama-cloud/": 5,
    "cohere/": 5,

    # الدرجة 6: IDE agents (قد تكون بطيئة)
    "kc/": 6, "kilocode/": 6, "oc/": 6, "opencode/": 6,
    "cursor/": 6, "cu/": 6, "dva/": 6, "kie/": 6,
    "aug/": 6, "cx/": 6, "codex/": 6, "cxa/": 6,
    "cfp/": 6, "tllm/": 6, "kimi-coding/": 6, "kmc/": 6,
    "mimo/": 6, "xiaomi-mimo/": 6, "ddgw/": 6, "unc/": 6,
    "no-think/": 6, "pepper/": 6, "agnes/": 6, "felo/": 6,
}

# المزودون غير القابلين للمحادثة — تخطَّهم
SKIP_PREFIXES = {
    "aihorde/", "horde/", "segmind/", "firefly/", "adobe-firefly/",
    "runway/", "runwayml/", "veo-free/", "veoaifree-web/",
    "ollama-search/", "serper-search/", "tavily-search/",
    "jules/",
}

# ═══════════════════════════════════════════════════════════
# تصنيف ذكي حسب اسم الموديل
# ═══════════════════════════════════════════════════════════
def classify(model_id):
    """يرجع set من التصنيفات"""
    mid = model_id.lower()
    tags = set()

    # ═══ coding ═══
    if any(k in mid for k in [
        "coder", "-code", "code-", "coding", "devstral", "swe",
        "kimi-k2.7-code", "kimi-k3", "qwen-coder", "deepseek-v4",
        "sonnet", "codestral", "starcoder", "codex",
    ]):
        tags.add("coding")

    # ═══ reasoning ═══
    if any(k in mid for k in [
        "thinking", "reasoning", "reason", "-r1", "o1", "o3", "o4",
        "opus", "sonnet-4-6", "gemini-3", "deepseek-r", "qwq",
    ]):
        tags.add("reasoning")

    # ═══ fast ═══
    if any(k in mid for k in [
        "flash", "fast", "turbo", "mini", "nano", "lightning",
        "haiku", "8b", "7b", "3b", "1b", "gpt-oss-20b",
        "llama-3.1-8b", "llama-3.2", "gemma-4",
    ]):
        tags.add("fast")

    # ═══ vision ═══
    if any(k in mid for k in [
        "vision", "-vl", "llava", "multimodal", "gemini-3", "gpt-4o",
        "claude-4", "claude-opus", "claude-sonnet", "gemini-3.1-flash-image",
    ]):
        tags.add("vision")

    # ═══ longctx (≥500K) ═══
    # (يُضاف لاحقاً بناءً على context_length الفعلي)

    # ═══ premium ═══
    if any(k in mid for k in [
        "opus", "gpt-5", "gpt-4.5", "gpt-6", "claude-4", "claude-5",
        "gemini-3.1-pro", "gemini-3-pro", "sonnet", "max", "ultra",
        "405b", "120b", "70b", "-pro",
    ]):
        tags.add("premium")

    return tags


# ═══════════════════════════════════════════════════════════
# اختيار أفضل المرشحين من كل مزود
# ═══════════════════════════════════════════════════════════
def pick_candidates(inventory, max_per_provider=8, max_total=180):
    """يختار أفضل المرشحين من كل مزود"""
    candidates = []

    for prefix, samples in inventory.get("prefix_samples", {}).items():
        if prefix in SKIP_PREFIXES:
            continue
        rank = PROVIDER_RANK.get(prefix, 99)
        if rank > 6:
            continue

        # اختر عدد محدود من كل مزود (حسب أولويته)
        limit = max_per_provider if rank <= 2 else (5 if rank <= 4 else 3)

        for mid in samples[:limit]:
            tags = classify(mid)
            candidates.append({
                "id": mid,
                "prefix": prefix,
                "rank": rank,
                "tags": list(tags),
                "priority": rank,  # الأقل = الأفضل
            })

    # ترتيب حسب الأولوية
    candidates.sort(key=lambda x: x["priority"])

    # حد أقصى
    return candidates[:max_total]


# ═══════════════════════════════════════════════════════════
# اختبار موديل — انتظر أول token فقط
# ═══════════════════════════════════════════════════════════
async def test_model(model_id, timeout=10.0):
    import httpx
    url = BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    t0 = time.time()
    try:
        t = httpx.Timeout(connect=4.0, read=timeout, write=8.0, pool=4.0)
        async with httpx.AsyncClient(timeout=t) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as r:
                if r.status_code != 200:
                    err = (await r.aread()).decode("utf-8", errors="ignore")[:120]
                    return {"id": model_id, "ok": False,
                            "reason": f"HTTP {r.status_code}: {err}",
                            "latency": 0}
                try:
                    async for line in r.aiter_lines():
                        if line.startswith("data:"):
                            raw = line[5:].strip()
                            if raw and raw != "[DONE]":
                                return {"id": model_id, "ok": True,
                                        "latency": round(time.time() - t0, 2)}
                except asyncio.TimeoutError:
                    return {"id": model_id, "ok": False, "reason": "timeout", "latency": 0}
        return {"id": model_id, "ok": False, "reason": "empty stream", "latency": 0}
    except httpx.ConnectError:
        return {"id": model_id, "ok": False, "reason": "connect error", "latency": 0}
    except Exception as e:
        return {"id": model_id, "ok": False, "reason": type(e).__name__, "latency": 0}


async def test_all(candidates, concurrency=10):
    sem = asyncio.Semaphore(concurrency)
    async def worker(c):
        async with sem:
            r = await test_model(c["id"])
            r["prefix"] = c["prefix"]
            r["rank"] = c["rank"]
            r["tags"] = c["tags"]
            return r
    return await asyncio.gather(*(worker(c) for c in candidates))


# ═══════════════════════════════════════════════════════════
# بناء auto routes
# ═══════════════════════════════════════════════════════════
def build_routes(results):
    working = [r for r in results if r["ok"]]
    working.sort(key=lambda r: (r["rank"], r["latency"]))

    routes = {
        "auto/smart": [],       # أفضل عقل عام
        "auto/coding": [],      # أفضل للبرمجة
        "auto/fast": [],        # الأسرع
        "auto/reasoning": [],   # تفكير عميق
        "auto/vision": [],      # صور
        "auto/cheap": [],       # مجاني
        "auto/balanced": [],    # توازن سرعة/جودة
    }

    # المرشحون
    for r in working:
        mid = r["id"]
        lat = r["latency"]
        tags = r.get("tags", [])

        # cheap = pol/ فقط
        if mid.startswith(("pol/", "pollinations/")) and len(routes["auto/cheap"]) < 5:
            routes["auto/cheap"].append(mid)

        # fast = <2s
        if lat < 2.0 and len(routes["auto/fast"]) < 5:
            routes["auto/fast"].append(mid)

        # coding
        if "coding" in tags and len(routes["auto/coding"]) < 5:
            routes["auto/coding"].append(mid)

        # reasoning
        if "reasoning" in tags and len(routes["auto/reasoning"]) < 5:
            routes["auto/reasoning"].append(mid)

        # vision
        if "vision" in tags and len(routes["auto/vision"]) < 5:
            routes["auto/vision"].append(mid)

        # smart = premium + جودة عالية
        if "premium" in tags and len(routes["auto/smart"]) < 5:
            routes["auto/smart"].append(mid)

        # balanced = سريع + جودة
        if lat < 3.0 and len(routes["auto/balanced"]) < 5:
            routes["auto/balanced"].append(mid)

    # ضمان عدم الفراغ — املأ بـ أفضل الشغالين
    fallback = [r["id"] for r in working[:5]]
    for route in routes:
        while len(routes[route]) < 3:
            for f in fallback:
                if f not in routes[route]:
                    routes[route].append(f)
                    break

    return routes, working


# ═══════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════
async def main():
    if not API_KEY:
        print("❌ OMNIROUTE_API_KEY missing in .env")
        sys.exit(1)

    if not os.path.exists("prefix_inventory.json"):
        print("❌ prefix_inventory.json not found")
        sys.exit(1)

    with open("prefix_inventory.json", "r", encoding="utf-8") as f:
        inventory = json.load(f)

    print("=" * 78)
    print("🧠 OMNIROUTE SMART ROUTER")
    print("=" * 78)
    print(f"\n📦 Total models: {inventory['total']:,}")

    candidates = pick_candidates(inventory, max_per_provider=8, max_total=180)
    print(f"🎯 Candidates selected: {len(candidates)}")

    print(f"\n⏱  Testing with concurrency=10...")
    print(f"   Estimated time: ~{len(candidates) * 10 // 10}s\n")

    t0 = time.time()
    results = await test_all(candidates, concurrency=10)
    elapsed = time.time() - t0

    working = [r for r in results if r["ok"]]
    broken = [r for r in results if not r["ok"]]

    print(f"\n{'=' * 78}")
    print(f"✅ Working: {len(working)} / {len(candidates)}  ({elapsed:.1f}s)")
    print(f"{'=' * 78}")

    # أفضل 30 شغال
    working.sort(key=lambda r: (r["rank"], r["latency"]))
    for r in working[:30]:
        print(f"  {r['latency']:>5.2f}s  [{r['prefix']:<15}] {r['id']}")

    routes, working = build_routes(results)

    print(f"\n{'=' * 78}")
    print("🎯 SMART AUTO ROUTES")
    print("=" * 78)
    for route, models in routes.items():
        print(f"\n  {route}:")
        for m in models:
            lat = next((r["latency"] for r in working if r["id"] == m), 0)
            print(f"      ⚡ {m:<50} {lat:>5.2f}s")

    # حفظ
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tested": len(candidates),
        "total_working": len(working),
        "routes": routes,
        "working": working,
        "broken": broken,
    }
    with open("auto_routes.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved to auto_routes.json")

    # اطبع كود Python جاهز
    print(f"\n{'=' * 78}")
    print("📋 COPY-PASTE TO server.py")
    print("=" * 78)
    print()
    print("FALLBACK_CHAINS: Dict[str, List[str]] = {")
    for route, models in routes.items():
        if models:
            chain = ", ".join(f'"{m}"' for m in models[:5])
            print(f'    "{route}": [{chain}],')
    print("}")
    print()
    best = routes["auto/smart"][0] if routes["auto/smart"] else "pol/gpt-5.6-sol"
    print(f'ULTIMATE_FALLBACK = "{best}"')


if __name__ == "__main__":
    asyncio.run(main())