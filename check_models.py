  
import asyncio
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()
from health_registry import health_check_all

ALL_MODELS = [
    "pol/grok-4.6",
    "pol/gpt-oss",
    "pol/kimi-k3",
    "pol/deepseek-pro",
    "pol/gpt-5.6-luna",
    "pol/glm-5.3",
    "pol/llama",
    "pol/command-a-plus",
    "gh/gpt-5.6-luna",
    "gh/gpt-5.6-sol",
    "gh/claude-sonnet-5",
    "gh/claude-opus-4.8",
    "gh/gemini-3.7-flash",
    "gh/kimi-k3",
    "oc/claude-sonnet-5",
    "oc/gpt-5.6-luna",
    "oc/gpt-5.6-sol",
    "oc/gemini-3.7-flash",
    "oc/kimi-k3",
    "oc/deepseek-v4-flash-free",
    "xai-oauth/grok-4.5",
    "glm/glm-5.3",
    "glm/glm-5.3-flash",
    "glm/glm-5.2",
]

BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
API_KEY = os.getenv("OMNIROUTE_API_KEY")

async def main():
    if not API_KEY:
        print("OMNIROUTE_API_KEY missing in .env")
        sys.exit(1)
    print(f"Checking {len(ALL_MODELS)} models...\n")
    results = await health_check_all(BASE_URL, API_KEY, ALL_MODELS, concurrency=10)
    working, broken = [], []
    for r in results:
        if r["ok"]:
            working.append(r)
            print(f"  OK   {r['model']:45} {r['latency']:>6.2f}s")
        else:
            broken.append(r)
            print(f"  FAIL {r['model']:45} {r.get('reason','')[:60]}")
    print(f"\nWorking: {len(working)} | Broken: {len(broken)}")
    with open("health_report.json", "w", encoding="utf-8") as f:
        json.dump({"working": working, "broken": broken}, f, ensure_ascii=False, indent=2)
    print("\nWorking models:")
    for r in sorted(working, key=lambda x: x["latency"]):
        print(f'    "{r["model"]}",')

if __name__ == "__main__":
    asyncio.run(main())