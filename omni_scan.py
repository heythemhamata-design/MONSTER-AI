"""
OMNIROUTE FULL DISCOVERY
- يسحب كل الموديلات المتاحة
- يحلل القدرات + السياق + المزود
- ينتج تقرير مفصل
"""
import asyncio
import json
import os
import sys
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")


async def fetch_all():
    import httpx
    url = BASE_URL.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json().get("data", [])


def dedupe_models(models):
    """إزالة التكرار — بعض المزودين يعطون آلاف نسخ من نفس الموديل"""
    seen = {}
    for m in models:
        mid = m.get("id", "")
        if not mid:
            continue
        # تجاهل النسخ المكررة بنفس الـ root
        root = m.get("root") or mid
        key = (m.get("owned_by", ""), root)
        # احتفظ بالنسخة الأقصر اسماً والأوضح
        if key not in seen or len(mid) < len(seen[key].get("id", "")):
            seen[key] = m
    return list(seen.values())


def categorize(model):
    """تصنيف ذكي حسب الاسم + capabilities"""
    mid = (model.get("id") or "").lower()
    caps = model.get("capabilities", {}) or {}
    ctx = model.get("context_length", 0) or 0

    tags = set()

    # قدرات
    if caps.get("vision") or caps.get("image") or "vision" in mid or "-vl" in mid or "llava" in mid or "multimodal" in mid:
        tags.add("vision")
    if caps.get("tool_calling") or "tool" in mid:
        tags.add("tools")
    if caps.get("reasoning") or caps.get("thinking") or "thinking" in mid or "-r1" in mid or "reasoner" in mid or "o1" in mid or "o3" in mid or "o4" in mid:
        tags.add("reasoning")

    # الغرض
    if any(k in mid for k in ["coder", "code", "coding", "dev", "sql", "python", "javascript"]):
        tags.add("coding")
    if any(k in mid for k in ["flash", "fast", "turbo", "mini", "nano", "lightning", "8b", "7b", "3b"]):
        tags.add("fast")
    if any(k in mid for k in ["embed", "rerank", "whisper", "tts", "voice"]):
        tags.add("special")

    # الحجم / القوة
    if any(k in mid for k in ["opus", "gpt-5", "gpt-4.5", "gpt-4-turbo", "claude-4", "gemini-2.5-pro", "gemini-3", "-max", "large", "70b", "120b", "405b", "sonnet"]):
        tags.add("premium")

    # سياق طويل
    if ctx >= 500000:
        tags.add("longctx")

    return tags


async def main():
    if not API_KEY:
        print("❌ OMNIROUTE_API_KEY missing in .env")
        sys.exit(1)

    print("=" * 78)
    print("🔍 OMNIROUTE FULL DISCOVERY")
    print("=" * 78)

    models = await fetch_all()
    print(f"\n📦 Raw models: {len(models):,}")

    models = dedupe_models(models)
    print(f"📦 After dedupe: {len(models):,}\n")

    # جرد حسب البادئة
    by_prefix = defaultdict(list)
    for m in models:
        mid = m.get("id", "")
        prefix = mid.split("/", 1)[0] + "/" if "/" in mid else "(no-prefix)"
        by_prefix[prefix].append(m)

    print("=" * 78)
    print("📊 MODELS BY PROVIDER PREFIX")
    print("=" * 78)
    sorted_prefixes = sorted(by_prefix.items(), key=lambda x: -len(x[1]))
    for prefix, items in sorted_prefixes[:60]:
        print(f"  {prefix:28}  {len(items):>5}")

    print(f"\n  Total providers: {len(by_prefix)}")

    # تحليل القدرات
    cap_count = defaultdict(int)
    for m in models:
        for tag in categorize(m):
            cap_count[tag] += 1

    print("\n" + "=" * 78)
    print("🧠 CAPABILITY BREAKDOWN")
    print("=" * 78)
    for tag in ["coding", "reasoning", "vision", "tools", "fast", "premium", "longctx", "special"]:
        print(f"  {tag:15}  {cap_count.get(tag, 0):>5} models")

    # أفضل الموديلات لكل تصنيف
    print("\n" + "=" * 78)
    print("⭐ TOP MODELS PER CATEGORY (best-guess, needs testing)")
    print("=" * 78)

    priority_providers = ["pol/", "agy/", "gh/", "gemini/", "openai/", "anthropic/",
                          "groq/", "cerebras/", "nvidia/", "deepinfra/", "nanogpt/",
                          "glm/", "kimi/", "minimax/", "openrouter/", "xai-oauth/", "xai/",
                          "ollama/", "cursor/", "devin/"]

    def provider_priority(mid):
        for i, p in enumerate(priority_providers):
            if mid.startswith(p):
                return i
        return 999

    for tag in ["coding", "reasoning", "vision", "fast"]:
        matching = [m for m in models if tag in categorize(m)]
        matching.sort(key=lambda m: (provider_priority(m["id"]), -m.get("context_length", 0)))
        print(f"\n  🎯 {tag.upper()} (top 15):")
        for m in matching[:15]:
            mid = m["id"]
            ctx = m.get("context_length", 0) or 0
            ctx_str = f"{ctx//1000}K" if ctx else "?"
            print(f"      {mid:50}  ctx={ctx_str}")

    # حفظ التقرير
    report = {
        "total_raw": len(models),
        "providers": {p: len(items) for p, items in by_prefix.items()},
        "capabilities": dict(cap_count),
        "all_models": [
            {
                "id": m.get("id"),
                "owned_by": m.get("owned_by"),
                "context": m.get("context_length", 0),
                "tags": list(categorize(m)),
            }
            for m in models
        ],
    }
    with open("omni_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved to omni_report.json")


if __name__ == "__main__":
    asyncio.run(main())