"""
اكتشف كل الموديلات المتاحة في OmniRoute + افحصها
"""
import asyncio
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()
from health_registry import health_check_all

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")


async def fetch_all_model_ids():
    """اسأل OmniRoute: ما هي كل الموديلات المتاحة؟"""
    import httpx
    url = BASE_URL.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return [m["id"] for m in data.get("data", [])]


async def main():
    if not API_KEY:
        print("OMNIROUTE_API_KEY missing")
        sys.exit(1)

    print("=" * 70)
    print("Fetching all models from OmniRoute...")
    print("=" * 70)
    all_ids = await fetch_all_model_ids()
    print(f"Found {len(all_ids)} models\n")

    # احفظ القائمة الكاملة
    with open("all_models_list.json", "w", encoding="utf-8") as f:
        json.dump(all_ids, f, ensure_ascii=False, indent=2)
    print(f"Saved full list to all_models_list.json")

    # فلتر auto/* (لا نفحصها — هي routing)
    testable = [m for m in all_ids if not m.startswith("auto/")]
    print(f"Testable models (excluding auto/*): {len(testable)}\n")

    # اسأل المستخدم: كلهم أم عينة؟
    print("Options:")
    print("  1. Test ALL models (قد يأخذ وقت)")
    print("  2. Test only common prefixes (pol/, gh/, oc/, glm/, agy/, ds/, xai-)")
    choice = input("\nChoose [1/2] (default: 2): ").strip() or "2"

    if choice == "2":
        prefixes = ("pol/", "gh/", "oc/", "glm/", "agy/", "ds/", "xai-oauth/", "xai/")
        testable = [m for m in testable if m.startswith(prefixes)]

    print(f"\nTesting {len(testable)} models with concurrency=8...")
    print("=" * 70)

    results = await health_check_all(BASE_URL, API_KEY, testable, concurrency=8)

    working = sorted([r for r in results if r["ok"]], key=lambda x: x["latency"])
    broken = [r for r in results if not r["ok"]]

    print("\n" + "=" * 70)
    print(f"✅ WORKING: {len(working)}")
    print("=" * 70)
    for r in working:
        print(f"  {r['latency']:>6.2f}s  {r['model']}")

    print("\n" + "=" * 70)
    print(f"❌ BROKEN: {len(broken)}")
    print("=" * 70)
    for r in broken:
        reason = r.get("reason", "")[:80]
        print(f"  {r['model']:45}  {reason}")

    # احفظ النتائج
    out = {
        "total_available": len(all_ids),
        "total_tested": len(testable),
        "working": working,
        "broken": broken,
        "working_ids": [r["model"] for r in working],
    }
    with open("discovery_report.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n📄 Saved to discovery_report.json")
    print(f"\n💡 Working model IDs (copy-paste to index.html):")
    print()
    print('const WORKING_MODELS = [')
    for r in working:
        print(f'    "{r["model"]}",')
    print('];')


if __name__ == "__main__":
    asyncio.run(main())


