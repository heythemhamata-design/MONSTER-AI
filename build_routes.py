"""
BUILD FINAL ROUTES — uses ALL 78 working models
"""
import json
import re
from collections import defaultdict

# ═══════════════════════════════════════════════════════════
# قراءة final_routes.json
# ═══════════════════════════════════════════════════════════
with open("final_routes.json", "r", encoding="utf-8") as f:
    data = json.load(f)

WORKING = data.get("all_working", {})

# لو مافي latencies (كلها صفر)، نعطي قيم افتراضية
# pol/* = 1.0s, gy/* = 2.3s, gemini = 1.8s, groq = 2.3s, cohere = 1.4s
DEFAULT_LAT = {
    "pol/": 1.0, "pollinations/": 1.0,
    "agy/": 2.3, "gemini/": 1.9, "openai/": 2.0,
    "gh/": 2.5, "github/": 2.5,
    "groq/": 2.3, "cerebras/": 2.3,
    "cohere/": 1.4,
    "cursor/": 1.2, "cu/": 1.3,
    "glm/": 2.3, "zc/": 2.3,
    "moonshot/": 2.3, "kmc/": 2.4, "kimi-coding/": 2.4,
    "minimax/": 2.3,
    "xai-oauth/": 2.4, "xao/": 2.4,
    "ollama-cloud/": 2.0, "ollamacloud/": 2.0,
    "mimo/": 2.3, "xiaomi-mimo/": 2.3,
    "friendli/": 2.3, "friendliai/": 2.3,
    "kc/": 3.1, "kilocode/": 3.1,
    "deepinfra/": 3.0, "nvidia/": 3.0, "nanogpt/": 3.0,
    "openrouter/": 3.0,
}


def get_lat(mid, val):
    if val and val > 0:
        return val
    for p, l in DEFAULT_LAT.items():
        if mid.startswith(p):
            return l
    return 5.0


def rank_provider(mid):
    """الأقل = الأفضل"""
    order = [
        "pol/", "cohere/", "cursor/", "cu/", "gemini/",
        "agy/", "groq/", "cerebras/", "glm/", "zc/",
        "moonshot/", "kmc/", "kimi-coding/", "minimax/",
        "xai-oauth/", "xao/", "ollama-cloud/", "ollamacloud/",
        "mimo/", "friendli/", "friendliai/",
        "gh/", "github/", "openai/",
        "kc/", "kilocode/",
        "deepinfra/", "nvidia/", "nanogpt/", "openrouter/",
    ]
    for i, p in enumerate(order):
        if mid.startswith(p):
            return i
    return 99


# ═══════════════════════════════════════════════════════════
# التصنيف
# ═══════════════════════════════════════════════════════════
def categorize(mid):
    m = mid.lower()
    cats = set()

    # ⚡ rapid
    if any(k in m for k in ["flash", "fast", "turbo", "mini", "nano",
                             "lite", "haiku", "lightning", "small"]):
        cats.add("rapid")
    if m.startswith(("groq/", "cerebras/")):
        cats.add("rapid")

    # 💻 coding
    if any(k in m for k in ["coder", "coding", "code", "codestral",
                             "kimi-for-coding", "kimi-code", "qwen-coder",
                             "deepseek-v4", "kimi-k2.7", "kimi-k3"]):
        cats.add("coding")
    if "claude" in m or "sonnet" in m or "opus" in m:
        cats.add("coding")

    # 🎯 smart
    if any(k in m for k in ["thinking", "reasoning", "reason",
                             "opus", "gpt-5", "gpt-6", "gemini-3",
                             "gemini-2.5-pro", "max", "ultra", "pro"]):
        cats.add("smart")

    # 🌐 vision
    if any(k in m for k in ["vision", "gemini", "gpt-4o", "gpt-5"]):
        cats.add("vision")

    cats.add("auto")
    return cats


# ═══════════════════════════════════════════════════════════
# بناء
# ═══════════════════════════════════════════════════════════
categorized = defaultdict(list)
for mid, lat in WORKING.items():
    actual_lat = get_lat(mid, lat)
    for c in categorize(mid):
        categorized[c].append((mid, actual_lat))

# رتّب كل فئة: أولاً حسب السرعة، ثم provider rank
for c in categorized:
    categorized[c].sort(key=lambda x: (rank_provider(x[0]), x[1]))

# اطبع المختارين
def top(cat, n=6):
    return [m for m, _ in categorized[cat][:n]]

routes = {
    "auto/smart":     top("smart", 6),
    "auto/coding":    top("coding", 6),
    "auto/fast":      top("rapid", 6),
    "auto/reasoning": top("smart", 6),
    "auto/vision":    top("vision", 5),
    "auto/cheap":     top("auto", 5),
    "auto/balanced":  top("auto", 6),
}

print("=" * 78)
print("🎯 FINAL AUTO ROUTES (all 78 models)")
print("=" * 78)

for route, models in routes.items():
    print(f"\n  {route}:")
    for m in models:
        lat = next(l for mm, l in categorized[route.split("/")[1]] if mm == m) if route.split("/")[1] in categorized else 0
        print(f"      ⚡ {m:<55} {lat:>5.2f}s")

# ULTIMATE_FALLBACK
ULTIMATE = "pol/gpt-5.6-sol" if "pol/gpt-5.6-sol" in WORKING else top("auto", 1)[0]

print("\n" + "=" * 78)
print("📋 FALLBACK_CHAINS (COPY TO server.py)")
print("=" * 78)
print()
print("FALLBACK_CHAINS: Dict[str, List[str]] = {")
# Auto routes
for route, models in routes.items():
    chain = ", ".join(f'"{m}"' for m in models)
    print(f'    "{route}": [{chain}],')

print()
# Individual fallbacks — كل موديل يشير للموديلات اللي بعده في نفس الفئة
individual = {}
for cat in ["smart", "coding", "rapid", "vision", "auto"]:
    lst = categorized[cat]
    for i, (mid, _) in enumerate(lst):
        if mid in individual: continue
        # احط الموديلات اللي بعده
        others = [m for m, _ in lst[i+1:i+4] if m != mid]
        # إذا ما في، احط pol/gpt-5.6-sol
        if not others:
            others = [ULTIMATE] if mid != ULTIMATE else ["pol/gpt-oss"]
        individual[mid] = others

for mid in sorted(individual.keys()):
    v = individual[mid]
    chain = ", ".join(f'"{m}"' for m in v)
    print(f'    "{mid}": [{chain}],')

print("}")
print()
print(f'ULTIMATE_FALLBACK = "{ULTIMATE}"')

# احفظ
with open("chains_final.txt", "w", encoding="utf-8") as f:
    f.write("FALLBACK_CHAINS: Dict[str, List[str]] = {\n")
    for route, models in routes.items():
        chain = ", ".join(f'"{m}"' for m in models)
        f.write(f'    "{route}": [{chain}],\n')
    f.write("\n")
    for mid in sorted(individual.keys()):
        chain = ", ".join(f'"{m}"' for m in individual[mid])
        f.write(f'    "{mid}": [{chain}],\n')
    f.write("}\n\n")
    f.write(f'ULTIMATE_FALLBACK = "{ULTIMATE}"\n')

print(f"\n💾 Saved to chains_final.txt")