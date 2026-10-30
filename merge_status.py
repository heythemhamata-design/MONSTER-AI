"""
Merge full_test_results.json into catalog.json
Adds __working__ and __broken__ fields
"""
import json
from collections import defaultdict

with open("full_test_results.json", "r", encoding="utf-8") as f:
    test = json.load(f)

with open("catalog.json", "r", encoding="utf-8") as f:
    catalog = json.load(f)

working = test.get("working", {})
broken = test.get("broken", {})

print(f"✅ Working: {len(working):,}")
print(f"❌ Broken:  {len(broken):,}")

# إحصائيات لكل مزود
stats_by_provider = defaultdict(lambda: {"working": 0, "broken": 0})

def provider_of(mid):
    return mid.split("/", 1)[0] + "/" if "/" in mid else "other"

for mid in working:
    stats_by_provider[provider_of(mid)]["working"] += 1
for mid in broken:
    stats_by_provider[provider_of(mid)]["broken"] += 1

# حدّث كل مزود
total_working = 0
total_broken = 0

for prov in catalog.get("providers", []):
    prefix = prov["prefix"]
    new_models = []
    for mid in prov.get("models", []):
        if mid in working:
            new_models.append({
                "id": mid,
                "status": "ok",
                "latency": working[mid],
            })
            total_working += 1
        elif mid in broken:
            new_models.append({
                "id": mid,
                "status": "broken",
                "reason": broken[mid],
            })
            total_broken += 1
        else:
            new_models.append({
                "id": mid,
                "status": "unknown",
            })
    prov["models"] = new_models
    stats = stats_by_provider.get(prefix, {"working": 0, "broken": 0})
    prov["working_count"] = stats["working"]
    prov["broken_count"] = stats["broken"]

# احفظ
with open("catalog.json", "w", encoding="utf-8") as f:
    json.dump(catalog, f, ensure_ascii=False, indent=2)

print(f"\n✅ Added status to {total_working + total_broken:,} models")
print(f"💾 Saved to catalog.json")