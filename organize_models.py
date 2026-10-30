"""
ORGANIZE V2 — تصنيف ذكي مع ترتيب حقيقي
- يستبعد موديلات المستخدمين (User Namespaces)
- يرجّح الموديلات الرسمية
- ترتيب داخل كل فئة حسب الجودة
"""
import json
import os
import re
import sys
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
# استثناءات
# ═══════════════════════════════════════════════════════════
NON_CHAT_PREFIXES = [
    "aihorde/", "horde/", "segmind/", "firefly/", "adobe-firefly/",
    "runway/", "runwayml/", "veo-free/", "veoaifree-web/",
    "ollama-search/", "serper-search/", "tavily-search/",
    "jules/", "no-think/",
]

NON_CHAT_KEYWORDS = [
    "whisper", "tts", "text-to-speech",
    "embedding", "embed-", "-embed", "rerank",
    "moderation", "dall-e", "dalle-", "flux",
    "sdxl", "sd3", "stable-diffusion", "imagen",
    "nano-banana", "seedream", "seedance", "veo",
    "sora-", "-sora", "kling", "runway", "gen-3", "gen-4",
    "wan2", "hunyuan-video", "ltx-video", "luma-",
    "hailuo", "t2v", "i2v", "v2v",
    "text-to-video", "image-to-video", "music-", "udio",
    "voice-clone", "voice-design", "voiceclone", "voicedesign",
    "image-01", "fibo_edit", "z-image", "gpt4o-image",
    "robotics", "omni-moderation", "guard-", "-guard",
    "safeguard", "computer-use", "computer_use",
    "transcribe", "lyria",
]

# ═══════════════════════════════════════════════════════════
# أسماء مستخدمين على Pollinations — نتجاهلها للترتيب
# ═══════════════════════════════════════════════════════════
USER_NAMESPACES = [
    "pol/AkshayCoder48/", "pol/Catniti/", "pol/JustScriptzz/",
    "pol/CloudCompile/", "pol/Gemini-3.7-Flash",
]

# ═══════════════════════════════════════════════════════════
# ترتيب المزودين
# ═══════════════════════════════════════════════════════════
PROVIDER_RANK = {
    # Tier 1: أفضل المصادر المباشرة
    "agy/": 1, "gemini/": 1, "openai/": 1,
    "gh/": 1, "github/": 1,
    "cerebras/": 1, "groq/": 1,

    # Tier 2: موديلات مباشرة جيدة
    "glm/": 2, "moonshot/": 2, "minimax/": 2,
    "xai-oauth/": 2, "xao/": 2, "cohere/": 2,

    # Tier 3: بوابات كبيرة
    "openrouter/": 3, "nvidia/": 3, "deepinfra/": 3,
    "nanogpt/": 3, "friendli/": 3, "friendliai/": 3,
    "ollamacloud/": 3, "ollama-cloud/": 3,

    # Tier 4: Pollinations (رسمية فقط)
    "pol/": 4, "pollinations/": 4,
    "pol/z-ai/": 4, "pol/deepseek/": 4,

    # Tier 5: IDE agents
    "kc/": 5, "kilocode/": 5, "oc/": 5, "opencode/": 5,
    "cursor/": 5, "cu/": 5, "dva/": 5, "kie/": 5,
    "cx/": 5, "codex/": 5, "cxa/": 5, "aug/": 5,
    "cfp/": 5, "tllm/": 5, "kmc/": 5, "kimi-coding/": 5,
}


def provider_rank(mid):
    """ترتيب المزود — الأقل = الأفضل. User namespaces = 99"""
    for ns in USER_NAMESPACES:
        if mid.startswith(ns):
            return 99
    for p, r in PROVIDER_RANK.items():
        if mid.startswith(p):
            return r
    return 10  # مجهول


def is_non_chat(mid):
    ml = mid.lower()
    for p in NON_CHAT_PREFIXES:
        if ml.startswith(p):
            return True
    for k in NON_CHAT_KEYWORDS:
        if k in ml:
            return True
    return False


# ═══════════════════════════════════════════════════════════
# التصنيف
# ═══════════════════════════════════════════════════════════
CODING_PATTERNS = [
    r"coder", r"code-", r"-code", r"coding", r"codestral",
    r"devstral", r"swe-", r"-swe",
    r"kimi-k2\.7", r"kimi-k3", r"kimi-for-coding",
    r"qwen-coder", r"codellama", r"starcoder",
    r"claude-", r"/claude",
    r"sonnet", r"opus",
    r"gpt-5\.[0-9]", r"gpt-5\b", r"gpt-6",
    r"gemini-3\.[0-9]-pro", r"gemini-3-pro",
    r"glm-5", r"glm-4\.[67]",
    r"deepseek-v4", r"deepseek-coder",
]

SMART_PATTERNS = [
    r"thinking", r"-think", r"think-",
    r"reasoning", r"-reason", r"reason-",
    r"deepseek-r", r"-r1", r"/r1", r"qwq",
    r"\bo1-", r"\bo3-", r"\bo4-",
    r"opus",
    r"gpt-5\.6", r"gpt-6",
    r"claude-5", r"claude-opus",
    r"gemini-3\.1-pro", r"gemini-3-pro",
    r"gemini-2\.5-pro",
    r"max-", r"-max",
    r"ultra",
    r"405b",
    r"gpt-oss-120b",
    r"deepseek-v4-pro",
]

RAPID_PATTERNS = [
    r"flash", r"fast", r"turbo", r"mini\b", r"nano\b",
    r"lite\b", r"lightning", r"haiku", r"small\b",
    r"\b20b\b", r"\b8b\b", r"\b7b\b", r"\b4b\b",
    r"\b3b\b", r"\b1b\b", r"\b0\.5b\b",
    r"instant", r"quick",
]

RAPID_PROVIDERS = ["groq/", "cerebras/"]


def classify(mid):
    m = mid.lower()
    cats = set()

    for p in RAPID_PATTERNS:
        if re.search(p, m):
            cats.add("rapid")
            break
    for prov in RAPID_PROVIDERS:
        if m.startswith(prov):
            cats.add("rapid")
            break

    for p in CODING_PATTERNS:
        if re.search(p, m):
            cats.add("coding")
            break

    for p in SMART_PATTERNS:
        if re.search(p, m):
            cats.add("smart")
            break

    cats.add("auto")
    return cats


# ═══════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 78)
    print("🗂  ORGANIZE V2")
    print("=" * 78)

    if not os.path.exists("all_models_list.json"):
        print("❌ all_models_list.json not found")
        sys.exit(1)

    with open("all_models_list.json", "r", encoding="utf-8") as f:
        all_ids = json.load(f)

    print(f"\n📦 Total models: {len(all_ids):,}")

    chat = [m for m in all_ids if not is_non_chat(m)]
    print(f"✅ Chat-capable: {len(chat):,}")

    # صنّف
    categorized = defaultdict(list)
    for mid in chat:
        for c in classify(mid):
            categorized[c].append(mid)

    # رتّب حسب: provider_rank ثم الحروف
    for c in categorized:
        categorized[c].sort(key=lambda m: (provider_rank(m), len(m), m))

    # فلتر المستخدمين
    for c in categorized:
        categorized[c] = [m for m in categorized[c] if provider_rank(m) < 99]

    # اطبع
    print("\n" + "=" * 78)
    print("📊 SUMMARY (after filtering user namespaces)")
    print("=" * 78)
    for c in ["smart", "coding", "rapid", "auto"]:
        print(f"  {c:10}  {len(categorized[c]):>6,} models")

    # احفظ
    out = {
        "smart":  categorized["smart"][:300],
        "coding": categorized["coding"][:300],
        "rapid":  categorized["rapid"][:300],
        "auto":   categorized["auto"][:600],
        "counts": {c: len(categorized[c]) for c in ["smart","coding","rapid","auto"]},
    }
    with open("models_v2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # اطبع أفضل 25 من كل فئة
    for cat, icon in [("smart","🎯"),("coding","💻"),("rapid","⚡"),("auto","🌐")]:
        print("\n" + "=" * 78)
        print(f"{icon} {cat.upper()} (top 25 after filtering)")
        print("=" * 78)
        for m in categorized[cat][:25]:
            pr = provider_rank(m)
            print(f"  [T{pr}] {m}")

    print(f"\n💾 Saved to models_v2.json")


if __name__ == "__main__":
    main()