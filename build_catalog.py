"""
BUILD CATALOG — كل 13,711 موديل مصنّف
"""
import json
import os
import re
from collections import defaultdict

# استثناءات
SKIP_PREFIXES = [
    "aihorde/", "horde/", "segmind/", "firefly/", "adobe-firefly/",
    "runway/", "runwayml/", "veo-free/", "veoaifree-web/",
    "ollama-search/", "serper-search/", "tavily-search/", "jules/",
]
SKIP_KEYWORDS = [
    "whisper", "tts", "-embed", "embedding", "rerank", "moderation",
    "dall-e", "dalle-", "flux", "sdxl", "sd3", "stable-diffusion",
    "imagen", "nano-banana", "seedream", "seedance", "veo", "sora-",
    "-sora", "kling", "runway", "gen-3", "gen-4", "wan2", "hunyuan-video",
    "ltx-video", "luma-", "hailuo", "t2v", "i2v", "v2v", "music-", "udio",
    "voice-clone", "voice-design", "image-01", "fibo_edit", "z-image",
    "gpt4o-image", "robotics", "guard-", "-guard", "safeguard",
    "computer-use", "transcribe", "lyria",
]

# أنماط التصنيف
CODING = [r"coder", r"code-", r"-code", r"coding", r"codestral", r"devstral",
          r"swe-", r"kimi-k2\.7", r"kimi-k3", r"kimi-for-coding",
          r"qwen-coder", r"codellama", r"starcoder", r"claude-", r"sonnet",
          r"opus", r"gpt-5\.[0-9]", r"gpt-6", r"gemini-3\.[0-9]-pro",
          r"glm-5", r"glm-4\.[67]", r"deepseek-v4", r"deepseek-coder"]

SMART = [r"thinking", r"-think", r"reasoning", r"deepseek-r", r"-r1", r"qwq",
         r"\bo1-", r"\bo3-", r"\bo4-", r"opus", r"gpt-5\.6", r"gpt-6",
         r"claude-5", r"claude-opus", r"gemini-3\.1-pro", r"gemini-3-pro",
         r"gemini-2\.5-pro", r"-max", r"ultra", r"405b", r"120b",
         r"gpt-oss-120b", r"deepseek-v4-pro"]

RAPID = [r"flash", r"fast", r"turbo", r"mini\b", r"nano\b", r"lite\b",
         r"lightning", r"haiku", r"small\b", r"\b[1-9]b\b", r"instant"]

RAPID_PROVIDERS = ["groq/", "cerebras/", "cohere/"]

# أولوية المزودين
PROVIDER_TIER = {
    "pol/": 1, "pollinations/": 1,
    "cohere/": 1, "cursor/": 1, "cu/": 1,
    "gemini/": 2, "agy/": 2, "groq/": 2, "cerebras/": 2,
    "glm/": 3, "zc/": 3, "moonshot/": 3, "kmc/": 3, "kimi-coding/": 3,
    "minimax/": 3, "xai-oauth/": 3, "xao/": 3,
    "gh/": 4, "github/": 4, "openai/": 4, "anthropic/": 4,
    "nvidia/": 5, "deepinfra/": 5, "nanogpt/": 5, "friendli/": 5,
    "friendliai/": 5, "ollamacloud/": 5, "ollama-cloud/": 5,
    "openrouter/": 6,
    "kc/": 7, "kilocode/": 7, "oc/": 7, "opencode/": 7,
    "dva/": 7, "kie/": 7, "cx/": 7, "codex/": 7, "cxa/": 7,
    "aug/": 7, "cfp/": 7, "tllm/": 7, "mimo/": 7, "xiaomi-mimo/": 7,
}

# أسماء مزودين للعرض
PROVIDER_NAMES = {
    "pol/": "🆓 Pollinations",
    "agy/": "💎 Antigravity",
    "gemini/": "🔷 Google Gemini",
    "openai/": "🟢 OpenAI Direct",
    "gh/": "🐙 GitHub Copilot",
    "groq/": "🚀 Groq (fastest)",
    "cerebras/": "⚡ Cerebras (fastest)",
    "glm/": "🎓 GLM (Zhipu)",
    "moonshot/": "🌟 Moonshot Kimi",
    "kmc/": "🌟 Kimi Coding",
    "xai-oauth/": "🚀 xAI Grok",
    "cohere/": "🇸🇦 Cohere",
    "cursor/": "🎯 Cursor",
    "cu/": "🎯 Cursor",
    "nvidia/": "💚 NVIDIA NIM",
    "deepinfra/": "🔵 DeepInfra",
    "openrouter/": "🌐 OpenRouter",
    "ollamacloud/": "🦙 Ollama Cloud",
    "mimo/": "🔮 MiMo",
}


def is_skip(mid):
    ml = mid.lower()
    if any(ml.startswith(p) for p in SKIP_PREFIXES): return True
    if any(k in ml for k in SKIP_KEYWORDS): return True
    return False


def classify(mid):
    m = mid.lower()
    cats = []
    # rapid
    if any(re.search(p, m) for p in RAPID): cats.append("rapid")
    if any(m.startswith(p) for p in RAPID_PROVIDERS): 
        if "rapid" not in cats: cats.append("rapid")
    # coding
    if any(re.search(p, m) for p in CODING): cats.append("coding")
    # smart
    if any(re.search(p, m) for p in SMART): cats.append("smart")
    return cats


def tier(mid):
    for p, t in PROVIDER_TIER.items():
        if mid.startswith(p): return t
    return 99


def provider_of(mid):
    return mid.split("/", 1)[0] + "/" if "/" in mid else "(other)"


def main():
    print("=" * 70)
    print("🗂  BUILD CATALOG")
    print("=" * 70)

    with open("all_models_list.json", "r", encoding="utf-8") as f:
        all_models = json.load(f)

    print(f"\n📦 Total: {len(all_models):,}")

    # فلتر
    chat = [m for m in all_models if not is_skip(m)]
    print(f"✅ Chat-capable: {len(chat):,}")

    # جمّع حسب المزود
    by_provider = defaultdict(list)
    for m in chat:
        by_provider[provider_of(m)].append(m)

    # رتّب
    for p in by_provider:
        by_provider[p].sort(key=lambda m: (tier(m), len(m), m))

    # قسم حسب الفئة
    smart = [m for m in chat if "smart" in classify(m)]
    coding = [m for m in chat if "coding" in classify(m)]
    rapid = [m for m in chat if "rapid" in classify(m)]

    smart.sort(key=lambda m: (tier(m), len(m)))
    coding.sort(key=lambda m: (tier(m), len(m)))
    rapid.sort(key=lambda m: (tier(m), len(m)))

    # المزودون — رتّب حسب tier
    providers_sorted = sorted(by_provider.keys(),
                              key=lambda p: (tier(p + "x"), p))

    # اطبعة
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)
    print(f"  smart:  {len(smart):,}")
    print(f"  coding: {len(coding):,}")
    print(f"  rapid:  {len(rapid):,}")

    print("\n" + "=" * 70)
    print("🏢 PROVIDERS")
    print("=" * 70)
    for p in providers_sorted[:40]:
        n = len(by_provider[p])
        name = PROVIDER_NAMES.get(p, p)
        print(f"  {name:30} {n:>5}")

    # كتالوج
    catalog = {
        "total": len(all_models),
        "chat_capable": len(chat),
        "providers": [
            {
                "prefix": p,
                "name": PROVIDER_NAMES.get(p, p),
                "tier": tier(p + "x"),
                "count": len(by_provider[p]),
                "models": by_provider[p][:200],  # أول 200 لكل مزود
            }
            for p in providers_sorted
        ],
        "categories": {
            "smart":  smart[:500],
            "coding": coding[:500],
            "rapid":  rapid[:500],
            "auto":   chat[:1000],
        },
        "counts": {
            "smart": len(smart),
            "coding": len(coding),
            "rapid": len(rapid),
            "auto": len(chat),
        },
    }

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved: catalog.json ({os.path.getsize('catalog.json')//1024} KB)")


if __name__ == "__main__":
    main()

