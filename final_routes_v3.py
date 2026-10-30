"""
FINAL ROUTES v3 — Optimized
- pol/ first (free + fast + reliable)
- agy/ second (Claude + Gemini)
- xao/xai-oauth third (Grok)
- openrouter last (rate-limited)
- ULTIMATE = pol/gpt-oss (0.57s)
"""
import json
from collections import defaultdict

with open("full_test_results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

working = data.get("working", {})
print(f"📊 Total working: {len(working):,}")

# ═══════════════════════════════════════════════════════════
# فلتر الجودة
# ═══════════════════════════════════════════════════════════
def is_dup(mid):
    """استثني مستخدمي pol/ المكررين"""
    for ns in ["pol/AkshayCoder48/", "pol/Catniti/", "pol/JustScriptzz/",
               "pol/Narkoleptika/", "pol/MarcosFRG/", "pol/NamanSoni78/",
               "pol/tomdacatto/", "pol/gggff123/", "pol/iotserver24/",
               "pol/chigwell/", "pol/vendouple/", "pol/sparkleware-ai/",
               "pollinations/AkshayCoder48/", "pollinations/Catniti/",
               "pollinations/JustScriptzz/", "pollinations/tomdacatto/",
               "pollinations/NamanSoni78/", "pollinations/MarcosFRG/",
               "pollinations/gggff123/", "pollinations/iotserver24/",
               "pollinations/chigwell/", "pollinations/vendouple/",
               "pollinations/Bakhshi7889/", "pollinations/Spit-fires/",
               "pollinations/Minor-fun/", "pollinations/CloudCompile/",
               "pollinations/sharktide/", "pollinations/Circuit-Overtime/",
               "pol/Bakhshi7889/", "pol/Spit-fires/", "pol/Minor-fun/",
               "pol/CloudCompile/", "pol/sharktide/", "pol/Circuit-Overtime/",
               "pol/Lorodn4x/", "pol/YoannDev90/", "pol/zero2launch/",
               "pol/pegalink/", "pol/morriszdweck/", "pol/inferenceport-ai/",
               "pol/deepseek/deepseek/"]:
        if mid.startswith(ns):
            return True
    return False


# ═══════════════════════════════════════════════════════════
# ترتيب المزودين
# ═══════════════════════════════════════════════════════════
PROVIDER_PRIORITY = {
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
    for p, r in PROVIDER_PRIORITY.items():
        if mid.startswith(p):
            return r
    return 99


# ═══════════════════════════════════════════════════════════
# تصنيف
# ═══════════════════════════════════════════════════════════
def classify(mid):
    m = mid.lower()
    tags = set()
    if any(k in m for k in ["flash", "fast", "turbo", "mini", "nano",
                             "lite", "lightning", "haiku"]):
        tags.add("rapid")
    if any(k in m for k in ["coder", "code-", "-code", "coding",
                             "kimi-k2.7", "kimi-k3", "codestral", "qwen-coder"]):
        tags.add("coding")
    if any(k in m for k in ["thinking", "reasoning", "opus",
                             "deepseek-r", "-r1", "qwq", "o1-", "o3-", "o4-"]):
        tags.add("smart")
    if any(k in m for k in ["vision", "-vl", "gemini", "gpt-4o", "gpt-5",
                             "claude-opus", "claude-sonnet", "llava"]):
        tags.add("vision")
    return tags


# ═══════════════════════════════════════════════════════════
# ابنِ القوائم
# ═══════════════════════════════════════════════════════════
filtered = {mid: lat for mid, lat in working.items() if not is_dup(mid)}
print(f"📊 After dedup: {len(filtered):,}")

# رتّب: مزود أولاً، ثم سرعة
sorted_models = sorted(
    filtered.items(),
    key=lambda x: (provider_rank(x[0]), x[1])
)

# قوائم مبدئية
buckets = {
    "smart": [],
    "coding": [],
    "rapid": [],
    "vision": [],
    "general": [],
}

for mid, lat in sorted_models:
    tags = classify(mid)
    if "rapid" in tags and lat <= 2.5:
        buckets["rapid"].append((mid, lat))
    elif "coding" in tags:
        buckets["coding"].append((mid, lat))
    elif "smart" in tags:
        buckets["smart"].append((mid, lat))
    elif "vision" in tags:
        buckets["vision"].append((mid, lat))
    if len(buckets["general"]) < 30:
        buckets["general"].append((mid, lat))

def top(lst, n=8):
    return [m for m, _ in lst[:n]]

# Routes نهائية
routes = {
    "auto/smart":     top(buckets["smart"]) or top(buckets["general"]),
    "auto/coding":    top(buckets["coding"]) or top(buckets["general"]),
    "auto/fast":      top(buckets["rapid"]) or top(buckets["general"]),
    "auto/reasoning": top(buckets["smart"][1:]) or top(buckets["general"]),  # ابدأ من 2 لتجنب تطابق مع smart
    "auto/vision":    top(buckets["vision"]) or top(buckets["general"]),
    "auto/cheap":     top([(m, l) for m, l in sorted_models if m.startswith(("pol/", "pollinations/"))]),
    "auto/balanced":  top(buckets["general"]),
}

# ═══════════════════════════════════════════════════════════
# ULTIMATE_FALLBACK — pol/gpt-oss
# ═══════════════════════════════════════════════════════════
ULTIMATE = "pol/gpt-oss"
if ULTIMATE not in filtered:
    # ابحث عن أفضل pol/ متاح
    for mid, lat in sorted_models:
        if mid.startswith("pol/") and not is_dup(mid):
            ULTIMATE = mid
            break

print("\n" + "=" * 78)
print("🎯 FINAL AUTO ROUTES (v3)")
print("=" * 78)
for route, models in routes.items():
    print(f"\n  {route}:")
    for m in models:
        lat = filtered.get(m, 0)
        print(f"      ⚡ {m:<55} {lat:>5.2f}s")

print("\n" + "=" * 78)
print("📋 FALLBACK_CHAINS — COPY TO server.py")
print("=" * 78)
print()
print("FALLBACK_CHAINS: Dict[str, List[str]] = {")
print("    # ═══ Auto Routes ═══")
for route, models in routes.items():
    if models:
        chain = ", ".join(f'"{m}"' for m in models)
        print(f'    "{route}": [{chain}],')
print()
print("    # ═══ Individual — Top 60 ═══")
count = 0
for mid, lat in sorted_models:
    if is_dup(mid):
        continue
    if mid in routes.get("auto/smart", []):
        continue
    # اختر الموديلات التالية في نفس المستوى
    same_tier = [
        m for m, _ in sorted_models
        if m != mid and not is_dup(m) and provider_rank(m) == provider_rank(mid)
    ][:3]
    if same_tier:
        chain = ", ".join(f'"{m}"' for m in same_tier)
        print(f'    "{mid}": [{chain}],')
        count += 1
    if count >= 60:
        break
print("}")
print()
print(f'ULTIMATE_FALLBACK = "{ULTIMATE}"')

# احفظ
out = {"routes": routes, "ultimate": ULTIMATE}
with open("final_routes_v3.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\n💾 Saved to final_routes_v3.json")
