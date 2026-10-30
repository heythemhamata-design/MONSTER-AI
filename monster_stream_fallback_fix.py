from __future__ import annotations

import ast
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SERVER = Path(__file__).resolve().parent / "server.py"

REPLACEMENT = r'''async def call_omniroute_stream(
    messages_history: list,
    model_name: str,
    _depth: int = 0,
    _tried: Optional[list] = None,
):
    """Stream from OmniRoute and try another model on 429, timeouts, or empty output."""
    if _tried is None:
        _tried = []

    chain = _resolve_chain(model_name) or [DEFAULT_MODEL]
    candidates: List[str] = []
    seen = set(_tried)
    for candidate in chain:
        if candidate and candidate not in seen and not _provider_is_cooling(candidate):
            candidates.append(candidate)
            seen.add(candidate)
    # If all remaining providers are cooling, still try untried candidates rather than hang.
    if not candidates:
        candidates = []
        seen = set(_tried)
        for candidate in chain:
            if candidate and candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    candidates = candidates[:4]

    if not candidates:
        raise Exception(
            f"No untried fallback models remain for '{model_name}'. Tried: {_tried}"
        )

    payload_messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    for msg in messages_history:
        payload_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        })

    url = OMNIROUTE_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OMNIROUTE_API_KEY}",
        "Accept": "text/event-stream",
    }
    rate_or_quota_terms = (
        "too many requests", "rate limit", "rate-limit", "rate_limit",
        "rate_limit_exceeded", "resource_exhausted", "429", "quota",
        "top up", "credits", "payment required", "insufficient",
    )
    fallback_statuses = {400, 402, 404, 408, 409, 422, 429, 500, 502, 503, 504}
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
    failures: List[str] = []

    for attempt, selected_model in enumerate(candidates):
        if selected_model not in _tried:
            _tried.append(selected_model)
        if attempt == 0 and _depth == 0:
            yield ("badge", selected_model)
        else:
            yield ("badge", f"{selected_model} (fallback)")

        print(
            f"{LOG_PREFIX} Trying: {selected_model} "
            f"(attempt={attempt + 1}/{len(candidates)})",
            flush=True,
        )
        payload = {
            "model": selected_model,
            "messages": payload_messages,
            "stream": True,
        }
        received_text = False
        stream_error = ""

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    if response.status_code != 200:
                        raw = await response.aread()
                        error_text = raw.decode("utf-8", errors="ignore")
                        error_lower = error_text.lower()
                        retryable = (
                            response.status_code in fallback_statuses
                            or any(k in error_lower for k in FALLBACK_KEYWORDS)
                            or any(k in error_lower for k in rate_or_quota_terms)
                        )
                        if not retryable:
                            raise Exception(
                                f"OmniRoute HTTP {response.status_code}: {error_text[:500]}"
                            )
                        stream_error = f"HTTP {response.status_code}: {error_text[:300]}"
                        if (
                            response.status_code == 429
                            or any(k in error_lower for k in rate_or_quota_terms)
                        ):
                            _cool_down_provider(selected_model)
                        failures.append(f"{selected_model}: {stream_error}")
                        print(
                            f"{LOG_PREFIX} {selected_model} failed with "
                            f"{stream_error}; trying fallback",
                            flush=True,
                        )
                        continue

                    iterator = response.aiter_lines().__aiter__()
                    # A provider that opens a stream but never emits text must not block
                    # the entire chat request. Limit time to first text to 28 seconds.
                    first_text_deadline = time.monotonic() + 28.0
                    while True:
                        try:
                            if not received_text:
                                remaining = first_text_deadline - time.monotonic()
                                if remaining <= 0:
                                    stream_error = "No text received within 28 seconds"
                                    break
                                line = await asyncio.wait_for(
                                    iterator.__anext__(), timeout=remaining
                                )
                            else:
                                line = await iterator.__anext__()
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            stream_error = "No text received within 28 seconds"
                            break

                        if not line or not line.startswith("data:"):
                            continue
                        raw_data = line[5:].strip()
                        if not raw_data:
                            continue
                        if raw_data == "[DONE]":
                            break

                        try:
                            data = json.loads(raw_data)
                        except json.JSONDecodeError:
                            continue

                        error_obj = data.get("error")
                        if error_obj:
                            error_text = json.dumps(error_obj, ensure_ascii=False)
                            error_lower = error_text.lower()
                            if received_text:
                                raise Exception(
                                    "Upstream error after partial output; the response "
                                    "was not restarted to avoid mixing model answers. "
                                    + error_text[:300]
                                )
                            stream_error = error_text[:300]
                            if any(k in error_lower for k in rate_or_quota_terms):
                                _cool_down_provider(selected_model)
                            break

                        choices = data.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        first = choices[0]
                        if not isinstance(first, dict):
                            continue
                        delta = first.get("delta") or {}
                        content = (
                            delta.get("content")
                            or delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thinking")
                            or ""
                        )
                        if isinstance(content, list):
                            content = "".join(
                                part.get("text", "") if isinstance(part, dict)
                                else str(part)
                                for part in content
                            )
                        if not content:
                            continue

                        content_text = str(content)
                        content_lower = content_text.lower()
                        looks_like_provider_error = (
                            not received_text
                            and len(content_text) < 1200
                            and any(k in content_lower for k in rate_or_quota_terms)
                        )
                        if looks_like_provider_error:
                            stream_error = content_text[:300]
                            _cool_down_provider(selected_model)
                            break

                        received_text = True
                        yield ("text", content_text)

            if received_text:
                return
            if not stream_error:
                stream_error = "Empty stream ended without response text"
            failures.append(f"{selected_model}: {stream_error}")
            print(
                f"{LOG_PREFIX} {selected_model}: {stream_error}; trying fallback",
                flush=True,
            )

        except asyncio.TimeoutError:
            if received_text:
                raise Exception(
                    f"Stream timed out after partial output from '{selected_model}'; "
                    "fallback was not started to avoid mixing answers."
                )
            stream_error = "No text received within 28 seconds"
            failures.append(f"{selected_model}: {stream_error}")
            print(f"{LOG_PREFIX} {selected_model}: {stream_error}; trying fallback", flush=True)
        except httpx.TimeoutException as exc:
            if received_text:
                raise Exception(
                    f"Stream timed out after partial output from '{selected_model}'; "
                    "fallback was not started to avoid mixing answers."
                ) from exc
            stream_error = f"Upstream timeout: {type(exc).__name__}"
            failures.append(f"{selected_model}: {stream_error}")
            print(f"{LOG_PREFIX} {selected_model}: {stream_error}; trying fallback", flush=True)
        except httpx.HTTPError as exc:
            if received_text:
                raise Exception(
                    f"Connection failed after partial output from '{selected_model}'; "
                    "fallback was not started to avoid mixing answers."
                ) from exc
            stream_error = f"Upstream connection error: {type(exc).__name__}: {exc}"
            failures.append(f"{selected_model}: {stream_error}")
            print(f"{LOG_PREFIX} {selected_model}: {stream_error}; trying fallback", flush=True)

    raise Exception(
        f"All fallback attempts failed for '{model_name}'. "
        f"Tried: {_tried}. Last errors: {' | '.join(failures[-4:])}"
    )
'''


def main() -> int:
    if not SERVER.is_file():
        print(f"ERROR: {SERVER} not found. Put this script beside server.py.")
        return 1

    original_bytes = SERVER.read_bytes()
    try:
        original = original_bytes.decode("utf-8-sig")
        tree = ast.parse(original, filename=str(SERVER))
    except Exception as exc:
        print(f"ERROR: Current server.py cannot be parsed: {exc}. No changes made.")
        return 1

    top_level = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    target_nodes = [n for n in top_level if n.name == "call_omniroute_stream"]
    required = {"_resolve_chain", "ai_stream_generator"}
    found = {n.name for n in top_level}
    missing = sorted(required - found)
    if len(target_nodes) != 1 or missing:
        print(
            "ERROR: Unexpected server.py structure; "
            f"call_omniroute_stream definitions={len(target_nodes)}, missing={missing}. "
            "No changes made."
        )
        return 1

    try:
        compile(REPLACEMENT, str(SERVER) + " (replacement)", "exec")
        lines = original.splitlines(keepends=True)
        node = target_nodes[0]
        start = node.lineno - 1
        end = node.end_lineno
        patched = "".join(lines[:start]) + REPLACEMENT.rstrip() + "\n\n" + "".join(lines[end:])
        patched_tree = ast.parse(patched, filename=str(SERVER))
        compile(patched, str(SERVER), "exec")
    except Exception as exc:
        print(f"ERROR: Patched source failed validation: {exc}. Original file unchanged.")
        return 1

    # Confirm we only replaced the target function and preserved the key route symbols.
    patched_functions = {
        n.name for n in patched_tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not {"_resolve_chain", "call_omniroute_stream", "ai_stream_generator"}.issubset(patched_functions):
        print("ERROR: Required function validation failed. Original file unchanged.")
        return 1
    if "@app.post(\"/api/chat\")" not in patched and "@app.post('/api/chat')" not in patched:
        print("ERROR: /api/chat route was not found. Original file unchanged.")
        return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = SERVER.with_name(f"server.py.before-stream-fallback-fix-{timestamp}.bak")
    temp = SERVER.with_name("server.py.stream-fallback.tmp")
    try:
        shutil.copy2(SERVER, backup)
        temp.write_text(patched, encoding="utf-8", newline="\n")
        # Re-read and compile the temp file before atomic replacement.
        compile(temp.read_text(encoding="utf-8"), str(temp), "exec")
        os.replace(temp, SERVER)
    except Exception as exc:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
        print(f"ERROR: Could not safely write the patch: {exc}. Backup: {backup.name}")
        return 1

    print("SUCCESS: Streaming fallback patch applied and syntax-validated.")
    print(f"Backup: {backup.name}")
    print("Behavior: retries up to 4 models; falls back on 429, upstream errors, empty streams,")
    print("          or no text within 28 seconds. .env and other files were not modified.")
    print("Next: restart MONSTER AI and repeat the /api/chat stream test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
