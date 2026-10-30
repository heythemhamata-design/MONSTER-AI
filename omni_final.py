"""
OMNI FINAL MERGER
- يدمج discovery_report.json + auto_routes.json
- يستثني legacy OpenAI models
- ينتج final_routes.json + FALLBACK_CHAINS جاهز
"""
import json
import os
from datetime import datetime

# ═══════════════════════════════════════════════════════════
# قائمة سوداء — موديلات قديمة أو غير مفيدة
# ═══════════════════════════════════════════════════════════
BLACKLIST = [
    # OpenAI legacy
    "openai/babbage", "openai/davinci", "openai/curie", "openai/ada",
    "openai/text-embedding", "openai/text-similarity",
    "openai/tts-", "openai/whisper", "openai/omni-moderation",
    "openai/gpt-3.5", "openai/gpt-4-0125", "openai/gpt-4-1106",
    # Cohere embeddings
    "cohere/embed-", "cohere/rerank",
    # Groq whisper
    "groq/whisper-", "groq/distil-whisper",
    # Gemini embeddings
    "gemini/gemini-embedding",
    # Cohere aya (legacy)
    "cohere/c4ai-aya",
    # ollamacloud legacy
    "ollamacloud/gpt-oss:20b",
]

# أولوية المزودين (الأفضل أولاً)
PROVIDER_PRIORITY = {
    # الدرجة 1: أسرع + مجاني + موثوق
    "pol/": 1,

    # الدرجة 2: premium مباشر
    "agy/": 2, "gemini/": 2, "openai/": 2, "gh/": 2,

    # الدرجة 3: مزودون فائقو السرعة
    "cerebras/": 3, "groq/": 3, "cohere/": 3,

    # الدرجة 4: ممتازون
    "glm/": 4, "moonshot/": 4, "kmc/": 4, "minimax/": 4,
    "xai-oauth/": 4, "xao/": 4,

    # الدرجة 5: بوابة كبيرة
    "openrouter/": 5, "nvidia/": 5, "deepinfra/": 5, "nanogpt/": 5,
    "ollamacloud/": 5, "friendli/": 5,

    # الدرجة 6: IDE agents
    "kc/": 6, "oc/": 6, "cursor/": 6, "cu/": 6, "dva/": 6,
    "kie/": 6, "cx/": 6, "codex/": 6, "cxa/": 6, "aug/": 6,
    "opencode/": 6, "kilocode/": 6,
}


def is_blacklisted(model_id):
    mid = model_id.lower()
    return any(b in mid for b in BLACKLIST)


def provider_rank(mid):
    for p, r in PROVIDER_PRIORITY.items():
        if mid.startswith(p):
            return r
    return 99


def load_json(path):
    if not os.path.exists(path):
        print(f"⚠️  {path} not found — skipping")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_working_from_discovery(data):
    """من discovery_report.json"""
    working = data.get("working", [])
    return {r["model"]: r.get("time", 0) for r in working if "model" in r}


def extract_working_from_routes(data):
    """من auto_routes.json"""
    working = data.get("working", [])
    return {r["id"]: r.get("latency", 0) for r in working if "id" in r}


def classify(model_id, latency=0):
    """تصنيف ذكي"""
    mid = model_id.lower()
    tags = set()

    # ═══ coding ═══
    if any(k in mid for k in [
        "coder", "code", "coding", "devstral", "swe-",
        "kimi-k2.7", "kimi-k3", "qwen-coder", "codestral",
        "sonnet", "opus", "gpt-5.6", "gpt-5.5", "gpt-5",
        "gemini-3.1-pro", "gemini-3-pro", "glm-5",
    ]):
        tags.add("coding")

    # ═══ reasoning ═══
    if any(k in mid for k in [
        "thinking", "reasoning", "reason", "deepseek-r", "qwq",
        "o1", "o3", "o4", "opus", "sonnet-4-6", "gemini-3.1-pro",
        "gemini-3-pro", "deepseek-v4-pro",
    ]):
        tags.add("reasoning")

    # ═══ fast ═══
    if latency < 2.0 or any(k in mid for k in [
        "flash", "fast", "turbo", "mini", "nano", "lightning",
        "haiku", "8b", "7b", "3b", "1b",
    ]):
        tags.add("fast")

    # ═══ vision ═══
    if any(k in mid for k in [
        "vision", "-vl", "llava", "multimodal",
        "gpt-4o", "gpt-5", "gemini-3", "gemini-2.5",
        "claude-opus", "claude-sonnet", "claude-4",
        "gemma-4", "gemma3",
    ]):
        tags.add("vision")

    # ═══ long context ═══
    if any(k in mid for k in [
        "1m", "2m", "500k", "long", "kimi-k3",
        "gemini-3", "gemini-2.5-pro",
    ]):
        tags.add("longctx")

    # ═══ premium ═══
    if any(k in mid for k in [
        "opus", "gpt-5.6", "gpt-6", "claude-4", "claude-5",
        "gemini-3.1-pro", "sonnet-4-6", "max", "ultra", "pro",
        "405b", "120b", "70b",
    ]):
        tags.add("premium")

    # ═══ free/cheap ═══
    if mid.startswith(("pol/", "pollinations/")):
        tags.add("cheap")

    return tags


def build_final_routes(all_working):
    """يبني routes نهائية من كل الشغالين"""
    routes = {
        "auto/smart": [],
        "auto/coding": [],
        "auto/fast": [],
        "auto/reasoning": [],
        "auto/vision": [],
        "auto/cheap": [],
        "auto/balanced": [],
    }

    # افرز حسب الأولوية ثم السرعة
    sorted_models = sorted(
        all_working.items(),
        key=lambda x: (provider_rank(x[0]), x[1])
    )

    for mid, lat in sorted_models:
        if is_blacklisted(mid):
            continue
        tags = classify(mid, lat)

        # cheap = pol فقط
        if "cheap" in tags and len(routes["auto/cheap"]) < 5:
            routes["auto/cheap"].append(mid)

        # fast = <2s
        if "fast" in tags and len(routes["auto/fast"]) < 5:
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

        # smart = premium + سريع
        if "premium" in tags and lat < 4.0 and len(routes["auto/smart"]) < 5:
            routes["auto/smart"].append(mid)

        # balanced = سريع + جودة
        if lat < 3.0 and len(routes["auto/balanced"]) < 5:
            routes["auto/balanced"].append(mid)

    # fallback إذا أحد routes فارغ — نأخذ أفضل الشغالين
    best_5 = [m for m, _ in sorted_models[:10] if not is_blacklisted(m)]
    for route in routes:
        while len(routes[route]) < 3:
            for m in best_5:
                if m not in routes[route]:
                    routes[route].append(m)
                    break
            else:
                break

    return routes


def build_fallback_chains(routes):
    """يبني dict chains كامل — يشمل كل الموديلات الفردية"""
    chains = {}

    # Auto routes أولاً
    for route, models in routes.items():
        if models:
            chains[route] = models[:5]

    # ثم كل موديل فردي — fallback ذكي
    for route_models in routes.values():
        for i, mid in enumerate(route_models):
            if mid in chains:
                continue
            # fallback = التالي في نفس الـ route
            next_in_route = route_models[i+1:i+4]
            if next_in_route:
                chains[mid] = next_in_route
            else:
                # fallback للأفضل العام
                chains[mid] = routes["auto/smart"][:2]

    return chains


def main():
    print("=" * 78)
    print("🧠 OMNI FINAL MERGER")
    print("=" * 78)

    # تحميل
    disc = load_json("discovery_report.json")
    auto = load_json("auto_routes.json")

    disc_working = extract_working_from_discovery(disc)
    auto_working = extract_working_from_routes(auto)

    print(f"\n📊 discovery_report: {len(disc_working)} models")
    print(f"📊 auto_routes:      {len(auto_working)} models")

    # دمج (الأسرع يفوز)
    all_working = {}
    for mid, lat in disc_working.items():
        all_working[mid] = lat
    for mid, lat in auto_working.items():
        if mid not in all_working or lat < all_working[mid]:
            all_working[mid] = lat

    print(f"📦 Combined:         {len(all_working)} unique models")

    # استثناء blacklist
    filtered = {m: l for m, l in all_working.items() if not is_blacklisted(m)}
    removed = len(all_working) - len(filtered)
    if removed:
        print(f"🗑️  Removed (legacy): {removed}")
    print(f"✅ Final working:    {len(filtered)}")

    if not filtered:
        print("\n❌ No working models after filtering!")
        return

    # بناء routes
    routes = build_final_routes(filtered)

    print("\n" + "=" * 78)
    print("🎯 FINAL SMART AUTO ROUTES")
    print("=" * 78)
    for route, models in routes.items():
        print(f"\n  {route}:")
        for m in models:
            lat = filtered.get(m, 0)
            print(f"      ⚡ {m:<55} {lat:>5.2f}s")

    # FALLBACK_CHAINS
    chains = build_fallback_chains(routes)

    print("\n" + "=" * 78)
    print("📋 FALLBACK_CHAINS — COPY TO server.py")
    print("=" * 78)
    print()
    print("FALLBACK_CHAINS: Dict[str, List[str]] = {")
    for k in sorted(chains.keys()):
        v = chains[k]
        chain_str = ", ".join(f'"{m}"' for m in v)
        print(f'    "{k}": [{chain_str}],')
    print("}")
    print()
    best = routes["auto/smart"][0] if routes["auto/smart"] else "pol/gpt-5.6-sol"
    print(f'ULTIMATE_FALLBACK = "{best}"')

    # حفظ
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_working": len(filtered),
        "routes": routes,
        "fallback_chains": chains,
        "ultimate_fallback": best,
        "all_working": filtered,
    }
    with open("final_routes.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved to final_routes.json")


if __name__ == "__main__":
    main()
