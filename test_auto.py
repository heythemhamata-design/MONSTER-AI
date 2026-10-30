import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
from health_registry import health_check_all

MODELS = [
    "auto/best-coding",
    "auto/best-reasoning",
    "auto/best-fast",
    "auto/best-chat",
    "auto/best-vision",
    "auto/pro-coding",
    "auto/pro-reasoning",
    "auto/pro-vision",
    "auto/pro-chat",
    "auto/best-coding-fast",
]

async def main():
    base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
    key = os.getenv("OMNIROUTE_API_KEY")
    print(f"Testing {len(MODELS)} auto models...\n")
    results = await health_check_all(base, key, MODELS, concurrency=7)
    print("\n" + "=" * 70)
    for r in results:
        status = "OK  " if r["ok"] else "FAIL"
        latency = f"{r['latency']:>6.2f}s"
        reason = r.get("reason", "")[:50]
        print(f"  {status}  {latency}  {r['model']:35}  {reason}")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())