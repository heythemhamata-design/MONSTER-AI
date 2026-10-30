"""
جرد ذكي لموديلات OmniRoute — يعرض البادئات قبل الاختبار
"""
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")


async def fetch_models():
    import httpx
    url = BASE_URL.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json().get("data", [])


def group_by_prefix(models):
    """يجمّع الموديلات حسب البادئة (pol/, gh/, oc/, ...)"""
    groups = defaultdict(list)
    for m in models:
        mid = m["id"]
        if mid.startswith("auto/"):
            continue
        prefix = mid.split("/", 1)[0] + "/" if "/" in mid else "(no-prefix)"
        groups[prefix].append(m)
    return groups


def analyze_capabilities(models):
    """يحلل القدرات المتوفرة"""
    caps = Counter()
    ctx_max = 0
    has_vision = 0
    has_tools = 0
    has_reasoning = 0
    for m in models:
        c = m.get("capabilities", {}) or {}
        for k, v in c.items():
            if v:
                caps[k] += 1
        if c.get("vision") or c.get("image"):
            has_vision += 1
        if c.get("tool_calling"):
            has_tools += 1
        if c.get("reasoning") or c.get("thinking"):
            has_reasoning += 1
        ctx = m.get("context_length", 0) or 0
        ctx_max = max(ctx_max, ctx)
    return {
        "total_caps": dict(caps),
        "vision_models": has_vision,
        "tool_models": has_tools,
        "reasoning_models": has_reasoning,
        "max_context": ctx_max,
    }


async def main():
    if not API_KEY:
        print("OMNIROUTE_API_KEY missing")
        sys.exit(1)

    print("=" * 78)
    print("📊 SMART DISCOVERY — Analyzing OmniRoute models")
    print("=" * 78)

    all_models = await fetch_models()
    print(f"\n✅ Total models: {len(all_models)}")

    groups = group_by_prefix(all_models)

    print("\n" + "─" * 78)
    print("📦 MODELS BY PREFIX (sorted by count)")
    print("─" * 78)

    sorted_prefixes = sorted(groups.items(), key=lambda x: -len(x[1]))
    for prefix, items in sorted_prefixes:
        # عيّنة 3 أسماء
        sample = [m["id"] for m in items[:3]]
        sample_str = ", ".join(sample)
        if len(sample_str) > 60:
            sample_str = sample_str[:57] + "..."
        print(f"  {prefix:25}  {len(items):>5}  │ {sample_str}")

    print(f"\n  Total prefixes: {len(groups)}")

    # احفظ الجرد
    inventory = {
        "total": len(all_models),
        "prefixes": {p: len(items) for p, items in groups.items()},
        "prefix_samples": {p: [m["id"] for m in items[:20]] for p, items in groups.items()},
    }
    with open("prefix_inventory.json", "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Saved to prefix_inventory.json")

    # ============ المرحلة 2: اختيار البادئات ============
    print("\n" + "=" * 78)
    print("🎯 SELECT PREFIXES TO TEST")
    print("=" * 78)
    print("\nTop prefixes by count:")
    print()

    # اعرض الـ 15 الأوائل
    top15 = sorted_prefixes[:15]
    for i, (prefix, items) in enumerate(top15, 1):
        print(f"  [{i:2}] {prefix:25}  ({len(items)} models)")

    print("\nSuggested common ones (test these first):")
    print("  pol/  gh/  oc/  glm/  agy/  ds/  xai/  xai-oauth/  gemini/  anthropic/  openai/")

    print("\nEnter numbers separated by spaces (e.g. 1 2 3),")
    print("or 'suggested' to test pol/gh/oc/glm/agy/ds/xai prefixes,")
    print("or 'top5' to test top 5 prefixes,")
    print("or 'skip' to just save the inventory:")
    choice = input("\nChoice: ").strip().lower()

    if choice == "skip":
        print("\n✅ Inventory saved. Run again when ready to test.")
        return

    selected_prefixes = []
    if choice == "suggested":
        wanted = ["pol/", "gh/", "oc/", "glm/", "agy/", "ds/", "xai/", "xai-oauth/"]
        selected_prefixes = [p for p in wanted if p in groups]
    elif choice == "top5":
        selected_prefixes = [p for p, _ in top15[:5]]
    else:
        try:
            nums = [int(x) for x in choice.split()]
            selected_prefixes = [top15[i - 1][0] for i in nums if 1 <= i <= len(top15)]
        except Exception:
            print("❌ Invalid input. Exiting.")
            return

    # اجمع الموديلات
    to_test = []
    for p in selected_prefixes:
        items = groups.get(p, [])
        # حد أقصى 30 لكل prefix لتوفير الوقت
        to_test.extend(m["id"] for m in items[:30])

    # أزل التكرار
    to_test = list(dict.fromkeys(to_test))

    print(f"\n🎯 Selected prefixes: {selected_prefixes}")
    print(f"🎯 Total models to test: {len(to_test)}")
    print(f"⏱️  Estimated time: ~{len(to_test) * 2 // 8}s with concurrency=8")

    confirm = input("\nProceed? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    # ============ المرحلة 3: اختبار ============
    from health_registry import health_check_all
    print("\n" + "=" * 78)
    print("🔬 TESTING...")
    print("=" * 78 + "\n")

    results = await health_check_all(BASE_URL, API_KEY, to_test, concurrency=10)

    working = sorted([r for r in results if r["ok"]], key=lambda x: x["latency"])
    broken = [r for r in results if not r["ok"]]

    print("\n" + "=" * 78)
    print(f"✅ WORKING: {len(working)}")
    print("=" * 78)
    for r in working:
        print(f"  {r['latency']:>6.2f}s  {r['model']}")

    print("\n" + "=" * 78)
    print(f"❌ BROKEN: {len(broken)}")
    print("=" * 78)
    for r in broken:
        print(f"  {r['model']:50}  {r.get('reason', '')[:50]}")

    out = {
        "tested": len(to_test),
        "working": working,
        "broken": broken,
        "working_ids": [r["model"] for r in working],
    }
    with open("discovery_report.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n📄 Saved to discovery_report.json")
    print(f"\n💡 Working IDs:")
    print()
    print("const WORKING_MODELS = [")
    for r in working:
        print(f'    "{r["model"]}",')
    print("];")


if __name__ == "__main__":
    asyncio.run(main())