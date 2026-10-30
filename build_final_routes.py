"""
BUILD FINAL ROUTES — from full_test_results.json
Creates clean fallback chains for server.py
"""
import json
from collections import defaultdict

with open("full_test_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

working = data.get("working", {})
print(f"📊 Total working: {len(working):,}")

# فلتر حسب السرعة والمزود
FAST_LIMIT = 2.5
MED_LIMIT = 4.0

PREFERRED_PROVIDERS = {
    "pol/": 1,
    "pollinations/": 1,
    "agy/": 2,
    "xao/": 3,
    "xai-oauth/": 3,
    "groq/": 4,
    "cerebras/": 4,
    "cohere/": 4,
    "glm/": 5,
    "zc/": 5,
    "moonshot/": 5,
    "kmc/": 5,
    "minimax/": 5,
    "gemini/": 6,
    "openai/": 6,
    "gh/": 6,
    "github/": 6,
    "ollamacloud/": 7,
    "ollama-cloud/": 7,
    "openrouter/": 8,
}

def provider_rank(mid):
    for p, r in PREFERRED_PROVIDERS.items():
        if mid.startswith(p):
            return r
    return 99

def is_dup(mid):
    """استثني المستخدمين المكررين في pol/"""
    if mid.startswith("pol/AkshayCoder48/"): return True
    if mid.startswith("pol/Catniti/"): return True
    if mid.startswith("pol/JustScriptzz/"): return True
    if mid.startswith("pollinations/AkshayCoder48/"): return True
    if mid.startswith("pollinations/Catniti/"): return True
    if "/deepseek/deepseek/" in mid: return True
    return False

# رتّب: أولوية المزود، ثم السرعة
all_working = sorted(
    [(mid, lat) for mid, lat in working.items() if not is_dup(mid)],
    key=lambda x: (provider_rank(x[0]), x[1])
)

print(f"📊 After dedup: {len(all_working):,}")

# تصنيف
smart = []
coding = []
rapid = []
vision = []
general = []

def classify(mid):
    m = mid.lower()
    tags = set()
    if any(k in m for k in ["flash", "fast", "turbo", "mini", "nano", "lite", "lightning", "haiku"]):
        tags.add("rapid")
    if any(k in m for k in ["coder", "code", "coding", "kimi-k2.7", "kimi-k3", "codestral"]):
        tags.add("coding")
    if any(k in m for k in ["thinking", "reasoning", "opus", "deepseek-r", "o1", "o3", "o4"]):
        tags.add("smart")
    if any(k in m for k in ["vision", "gemini", "gpt-4o", "gpt-5", "claude-opus", "claude-sonnet"]):
        tags.add("vision")
    return tags

for mid, lat in all_working:
    tags = classify(mid)
    if "rapid" in tags and lat < FAST_LIMIT and len(rapid) < 15:
        rapid.append((mid, lat))
    elif "coding" in tags and len(coding) < 15:
        coding.append((mid, lat))
    elif "smart" in tags and len(smart) < 15:
        smart.append((mid, lat))
    elif "vision" in tags and len(vision) < 10:
        vision.append((mid, lat))
    if len(general) < 25:
        general.append((mid, lat))

def top_pick(lst, n=8):
    """اختر أفضل N من قائمة"""
    return [m for m, _ in lst[:n]]

routes = {
    "auto/smart":     top_pick(smart) or top_pick(general),
    "auto/coding":    top_pick(coding) or top_pick(general),
    "auto/fast":      top_pick(rapid) or top_pick(general),
    "auto/reasoning": top_pick(smart) or top_pick(general),
    "auto/vision":    top_pick(vision) or top_pick(general),
    "auto/cheap":     top_pick([(m, l) for m, l in all_working if m.startswith(("pol/", "pollinations/"))]),
    "auto/balanced":  top_pick(general),
}

# اطبع
print("\n" + "=" * 78)
print("🎯 FINAL AUTO ROUTES")
print("=" * 78)
for route, models in routes.items():
    print(f"\n  {route}:")
    for m in models:
        lat = working.get(m, 0)
        print(f"      ⚡ {m:<55} {lat:>5.2f}s")

# FALLBACK_CHAINS
print("\n" + "=" * 78)
print("📋 FALLBACK_CHAINS — COPY TO server.py")
print("=" * 78)
print()
print("FALLBACK_CHAINS: Dict[str, List[str]] = {")
# Auto routes
for route, models in routes.items():
    if models:
        chain = ", ".join(f'"{m}"' for m in models[:8])
        print(f'    "{route}": [{chain}],')
print()
# Individual fallbacks
for mid, lat in all_working[:300]:
    if is_dup(mid):
        continue
    # نفس المزود، سرعة مماثلة
    chain = [
        m for m, l in all_working[:200]
        if m != mid and not is_dup(m) and provider_rank(m) == provider_rank(mid)
    ][:3]
    if not chain:
        chain = [routes["auto/smart"][0]] if routes["auto/smart"] else []
    if chain:
        chain_str = ", ".join(f'"{m}"' for m in chain)
        print(f'    "{mid}": [{chain_str}],')
print("}")
print()
ultimate = routes["auto/smart"][0] if routes["auto/smart"] else "pol/gpt-5.6-sol"
print(f'ULTIMATE_FALLBACK = "{ultimate}"')

# احفظ
out = {
    "routes": routes,
    "chains_text": "see above",
    "total_working": len(working),
}
with open("final_routes_v2.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\n💾 Saved to final_routes_v2.json")
