import json
import time
import httpx

CANDIDATES = [
    # Pollinations
    "pol/grok-4.6",
    "pol/gpt-oss",
    "pol/kimi-k3",
    "pol/claude",
    "pol/gemini",
    "pol/deepseek-pro",
    "pol/gpt-5.6-luna",
    "pol/glm-5.3",
    "pol/mistral",
    "pol/llama",
    "pol/command-a-plus",
    "pol/qwen-coder-large",
    "pol/qwen3-coder-480b",
    "pol/kimi-k2.7-code",
    # GitHub Copilot
    "gh/gpt-5.6-luna",
    "gh/gpt-5.6-sol",
    "gh/claude-sonnet-5",
    "gh/claude-opus-4.8",
    "gh/gemini-3.7-flash",
    "gh/grok-4.6",
    "gh/kimi-k3",
    "gh/o3-mini",
    "gh/o4-mini",
    # KiloCode
    "kc/claude-sonnet-5",
    "kc/claude-opus-4.8",
    "kc/gpt-5.6-luna",
    "kc/gpt-5.6-sol",
    "kc/gemini-3.7-flash",
    "kc/kimi-k3",
    "kc/deepseek-v4-pro",
    "kc/qwen3.6-plus",
    # OpenCode
    "oc/claude-sonnet-5",
    "oc/claude-opus-4.8",
    "oc/gpt-5.6-luna",
    "oc/gpt-5.6-sol",
    "oc/gemini-3.7-flash",
    "oc/kimi-k3",
    "oc/deepseek-v4-flash-free",
    # xAI OAuth
    "xai-oauth/grok-4.6",
    "xai-oauth/grok-4.6-high",
    "xai-oauth/grok-4.5",
    # DeepSeek
    "ds/deepseek-v4-pro",
    "ds/deepseek-v4-flash",
    # GLM
    "glm/glm-5.3",
    "glm/glm-5.3-flash",
    "glm/glm-5.2",
]


def test_model(model):
    try:
        start = time.time()
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "http://localhost:8000/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False
                }
            )
        elapsed = time.time() - start

        if response.status_code != 200:
            return {"model": model, "status": "broken", "reason": f"HTTP {response.status_code}", "time": elapsed}

        text = response.text.lower()

        if "fallback" in text:
            return {"model": model, "status": "fallback", "reason": "fallback triggered", "time": elapsed}
        elif "⚠️" in text or '"error"' in text:
            return {"model": model, "status": "broken", "reason": "error in response", "time": elapsed}
        else:
            return {"model": model, "status": "working", "reason": "ok", "time": elapsed}
    except Exception as e:
        return {"model": model, "status": "broken", "reason": f"{type(e).__name__}: {e}", "time": 0}


def main():
    print(f"Testing {len(CANDIDATES)} curated models...\n")

    results = {"working": [], "fallback": [], "broken": []}

    for i, model in enumerate(CANDIDATES, 1):
        print(f"[{i:2}/{len(CANDIDATES)}] {model:45}", end=" ", flush=True)
        result = test_model(model)

        if result["status"] == "working":
            print(f"OK ({result['time']:.1f}s)")
            results["working"].append(result)
        elif result["status"] == "fallback":
            print(f"FALLBACK ({result['time']:.1f}s)")
            results["fallback"].append(result)
        else:
            print(f"BROKEN: {result['reason']}")
            results["broken"].append(result)

    print("\n" + "=" * 70)
    print("REPORT")
    print("=" * 70)
    print(f"Working:  {len(results['working'])}")
    print(f"Fallback: {len(results['fallback'])}")
    print(f"Broken:   {len(results['broken'])}")

    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("WORKING MODELS:")
    print("=" * 70)
    for r in results["working"]:
        print(f'  "{r["model"]}",')

    print("\nFull results saved to test_results.json")


if __name__ == "__main__":
    main()