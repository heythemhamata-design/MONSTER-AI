from pathlib import Path
from datetime import datetime
import ast
import re
import sys

SERVER = Path(__file__).resolve().parent / "server.py"
if not SERVER.exists():
    print(f"ERROR: {SERVER} not found. Put this script beside server.py in C:\\OmniChat.")
    sys.exit(1)

source = SERVER.read_text(encoding="utf-8-sig")
if not source.strip():
    print(f"ERROR: {SERVER} is empty. No changes made.")
    sys.exit(1)

# Parse the existing file first, then locate actual top-level function nodes.
# This avoids matching text inside comments, examples, or docstrings.
try:
    original_tree = ast.parse(source, filename=str(SERVER))
except SyntaxError as exc:
    print(f"ERROR: Existing server.py has a syntax error at line {exc.lineno}: {exc.msg}. No changes made.")
    sys.exit(1)

function_nodes = [
    node for node in original_tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
]
route_node = next((node for node in function_nodes if node.name == "_resolve_chain"), None)
stream_node = next((node for node in function_nodes if node.name == "ai_stream_generator"), None)
if route_node is None:
    print("ERROR: Could not find the actual top-level _resolve_chain function. No changes made.")
    sys.exit(1)
if stream_node is None:
    print("ERROR: Could not find the actual top-level ai_stream_generator function. No changes made.")
    sys.exit(1)

def node_start_line(node):
    decorator_lines = [item.lineno for item in getattr(node, "decorator_list", [])]
    return min(decorator_lines + [node.lineno])

route_start_line = node_start_line(route_node)
stream_start_line = node_start_line(stream_node)
if stream_start_line <= route_start_line:
    print("ERROR: ai_stream_generator is not after _resolve_chain. No changes made.")
    sys.exit(1)

# Refuse to overwrite any unrelated top-level definition between these functions.
segment_nodes = [
    node for node in original_tree.body
    if route_start_line <= node_start_line(node) < stream_start_line
]
unexpected_nodes = []
for node in segment_nodes:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name not in {"_resolve_chain", "call_omniroute_stream"}:
            unexpected_nodes.append(f"function {node.name} at line {node.lineno}")
    else:
        unexpected_nodes.append(f"{type(node).__name__} at line {node.lineno}")
if unexpected_nodes:
    print("ERROR: The routing section contains unrelated top-level code; refusing to replace it:")
    for item in unexpected_nodes:
        print(" - " + item)
    print("No changes made. Send this output for a targeted patch.")
    sys.exit(1)

source_lines = source.splitlines(keepends=True)
def line_offset(line_number: int) -> int:
    return sum(len(line) for line in source_lines[:line_number - 1])

start = line_offset(route_start_line)
stream_function = line_offset(stream_start_line)

replacement = r'''def _resolve_chain(model_name: str) -> List[str]:
    """Resolve model/category names to an ordered routing chain."""
    requested = (model_name or "").strip()

    native_routes = {
        "": "auto/smart",
        "auto": "auto/smart",
        "smart": "auto/smart",
        "auto/smart": "auto/smart",
        "coding": "auto/coding",
        "auto/coding": "auto/coding",
        "rapid": "auto/fast",
        "fast": "auto/fast",
        "auto/fast": "auto/fast",
        "vision": "auto/vision",
        "auto/vision": "auto/vision",
        "reasoning": "auto/reasoning",
        "auto/reasoning": "auto/reasoning",
    }

    route = native_routes.get(requested)
    if route:
        return [route] + [m for m in ULTIMATE_FALLBACKS if m != route]

    if requested in SMART_CATEGORIES:
        chain = list(SMART_CATEGORIES[requested])
    else:
        chain = [requested] if requested else [DEFAULT_MODEL]
        chain.extend(FALLBACK_CHAINS.get(requested, []))

    result: List[str] = []
    for model in chain + ULTIMATE_FALLBACKS:
        if model and model not in result:
            result.append(model)
    return result


# =========================================================
# OMNIROUTE STREAMING ENGINE
# =========================================================
async def call_omniroute_stream(
    messages_history: list,
    model_name: str,
    _depth: int = 0,
    _tried: Optional[list] = None,
):
    """Stream from OmniRoute and retry another model when a request fails before text starts."""
    if _tried is None:
        _tried = []

    chain = _resolve_chain(model_name) or [DEFAULT_MODEL]
    selected_model = next(
        (m for m in chain if m not in _tried and not _provider_is_cooling(m)),
        None,
    )
    if selected_model is None:
        selected_model = next((m for m in chain if m not in _tried), None)
    if selected_model is None:
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
    payload = {
        "model": selected_model,
        "messages": payload_messages,
        "stream": True,
    }

    if _depth == 0:
        yield ("badge", selected_model)
    print(f"{LOG_PREFIX} Trying: {selected_model} (depth={_depth})", flush=True)

    fallback_needed = False
    fallback_reason = ""
    received_text = False
    reported_actual_model = False
    rate_or_quota_terms = (
        "too many requests", "rate limit", "rate-limit", "rate_limit",
        "rate_limit_exceeded", "resource_exhausted", "429", "quota",
        "top up", "credits", "payment required", "insufficient",
    )
    fallback_statuses = {400, 402, 404, 408, 409, 422, 429, 500, 502, 503, 504}
    timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload
            ) as response:
                if response.status_code != 200:
                    err_text = (await response.aread()).decode("utf-8", errors="ignore")
                    err_lower = err_text.lower()
                    fallback_needed = (
                        response.status_code in fallback_statuses
                        or any(k in err_lower for k in FALLBACK_KEYWORDS)
                    )
                    fallback_reason = (
                        f"HTTP {response.status_code}: {err_text[:300]}"
                    )
                    print(
                        f"{LOG_PREFIX} Model '{selected_model}' returned "
                        f"HTTP {response.status_code}: {err_text[:200]}",
                        flush=True,
                    )
                    if any(k in err_lower for k in rate_or_quota_terms):
                        _cool_down_provider(selected_model)
                    if not fallback_needed:
                        raise Exception(
                            f"OmniRoute HTTP {response.status_code}: {err_text[:500]}"
                        )
                else:
                    async for line in response.aiter_lines():
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
                            err_text = json.dumps(error_obj, ensure_ascii=False)
                            err_lower = err_text.lower()
                            if received_text:
                                raise Exception(
                                    "Upstream error after partial output; refusing to "
                                    "combine two different model responses. "
                                    + err_text[:300]
                                )
                            fallback_needed = any(
                                k in err_lower for k in FALLBACK_KEYWORDS
                            ) or any(k in err_lower for k in rate_or_quota_terms)
                            fallback_reason = err_text[:300]
                            if any(k in err_lower for k in rate_or_quota_terms):
                                _cool_down_provider(selected_model)
                            if not fallback_needed:
                                raise Exception(
                                    f"OmniRoute stream error for '{selected_model}': "
                                    f"{err_text[:500]}"
                                )
                            print(
                                f"{LOG_PREFIX} Streaming error from '{selected_model}': "
                                f"{err_text[:200]}",
                                flush=True,
                            )
                            break

                        actual_model = data.get("model")
                        if (
                            _depth == 0
                            and actual_model
                            and actual_model != selected_model
                            and not reported_actual_model
                        ):
                            yield ("badge", actual_model)
                            reported_actual_model = True

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

                        lower_content = str(content).lower()
                        looks_like_provider_error = (
                            not received_text
                            and any(k in lower_content for k in rate_or_quota_terms)
                            and len(str(content)) < 1200
                        )
                        if looks_like_provider_error:
                            fallback_needed = True
                            fallback_reason = str(content)[:300]
                            _cool_down_provider(selected_model)
                            print(
                                f"{LOG_PREFIX} Provider error in stream from "
                                f"'{selected_model}': {str(content)[:200]}",
                                flush=True,
                            )
                            break

                        received_text = True
                        yield ("text", str(content))

                    if not received_text and not fallback_needed:
                        fallback_needed = True
                        fallback_reason = (
                            f"Empty response stream from '{selected_model}' "
                            f"(HTTP {response.status_code})"
                        )
                        print(f"{LOG_PREFIX} {fallback_reason}", flush=True)

    except httpx.ConnectError as exc:
        raise Exception(
            f"Cannot connect to OmniRoute at {OMNIROUTE_BASE_URL}. "
            f"Is it running? ({exc})"
        ) from exc
    except httpx.TimeoutException as exc:
        if received_text:
            raise Exception(
                f"Stream timed out after partial output from '{selected_model}'; "
                "response was not restarted to avoid mixing answers."
            ) from exc
        fallback_needed = True
        fallback_reason = f"Timeout while waiting for '{selected_model}': {type(exc).__name__}"
        print(f"{LOG_PREFIX} {fallback_reason}; trying fallback", flush=True)

    if received_text and not fallback_needed:
        return
    if not fallback_needed:
        return

    if selected_model not in _tried:
        _tried.append(selected_model)

    if _depth >= 5:
        raise Exception(
            f"Maximum fallback depth reached for '{model_name}'. "
            f"Last error: {fallback_reason}. Tried: {_tried}"
        )

    next_candidates = [
        m for m in chain
        if m not in _tried and not _provider_is_cooling(m)
    ]
    if not next_candidates:
        next_candidates = [
            m for m in ULTIMATE_FALLBACKS
            if m not in _tried and not _provider_is_cooling(m)
        ]
    if not next_candidates:
        raise Exception(
            f"No fallback candidates available for '{model_name}'. "
            f"Last error: {fallback_reason}. Tried: {_tried}"
        )

    last_error = None
    for fallback_model in next_candidates:
        print(
            f"{LOG_PREFIX} Fallback: '{selected_model}' -> '{fallback_model}'",
            flush=True,
        )
        yield ("badge", f"{fallback_model} (fallback)")
        try:
            async for item in call_omniroute_stream(
                messages_history, fallback_model, _depth + 1, _tried
            ):
                if item[0] == "badge":
                    continue
                yield item
            return
        except Exception as exc:
            last_error = exc
            print(
                f"{LOG_PREFIX} Fallback '{fallback_model}' failed: {exc}",
                flush=True,
            )

    raise Exception(
        f"All fallback attempts failed for '{model_name}'. "
        f"Last error: {last_error or fallback_reason}"
    )
'''

patched = (
    source[:start]
    + replacement.strip()
    + "\n\n# =========================================================\n"
    + "# STREAM GENERATOR (REPAIRED)\n\n"
    + source[stream_function:]
)

# Replace the actual top-level FALLBACK_KEYWORDS assignment using AST spans.
try:
    patched_tree_for_keywords = ast.parse(patched, filename=str(SERVER))
except SyntaxError as exc:
    print(f"ERROR: Routing replacement failed syntax parsing at line {exc.lineno}: {exc.msg}. No changes made.")
    context = patched.splitlines()
    if exc.lineno:
        for number in range(max(1, exc.lineno - 3), min(len(context), exc.lineno + 3) + 1):
            print(f"{number:5}: {context[number - 1]}")
    sys.exit(1)

keyword_node = None
for node in patched_tree_for_keywords.body:
    targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
    if any(isinstance(target, ast.Name) and target.id == "FALLBACK_KEYWORDS" for target in targets):
        keyword_node = node
        break
if keyword_node is None:
    print("ERROR: Top-level FALLBACK_KEYWORDS assignment not found. No changes made.")
    sys.exit(1)

patched_lines = patched.splitlines(keepends=True)
def patched_line_offset(line_number: int) -> int:
    return sum(len(line) for line in patched_lines[:line_number - 1])

kw_start = patched_line_offset(keyword_node.lineno)
kw_end = patched_line_offset(keyword_node.end_lineno + 1) if keyword_node.end_lineno < len(patched_lines) else len(patched)
keywords = '''FALLBACK_KEYWORDS = [
    "not available",
    "too many requests",
    "rate_limit_exceeded",
    "rate_limit",
    "resource_exhausted",
    "not found",
    "no active credentials",
    "invalid model",
    "bad_request",
    "model does not exist",
    "unknown model",
    "no such model",
    "unsupported model",
    "model not supported",
    "not supported",
    "model_not_supported",
    "is not supported",
    "enough credits",
    "top up",
    "quota",
    "insufficient",
    "payment required",
    "rate limit",
    "rate-limit",
    "429",
]'''
patched = patched[:kw_start] + keywords + "\n" + patched[kw_end:]

# Scrub any hard-coded example key from the startup instructions.
patched = re.sub(
    r'(?m)^(\s*print\(\s*["\'][^"\']*OMNIROUTE_API_KEY=)[^"\']*(["\']\s*\))',
    r'\1sk-xxxxxxxx\2',
    patched,
)

# Compile the complete patched source before writing it.
try:
    compile(patched, str(SERVER), "exec")
except SyntaxError as exc:
    print(
        f"ERROR: Patched source did not compile at line {exc.lineno}, "
        f"column {exc.offset}: {exc.msg}. Original file was not overwritten."
    )
    generated_lines = patched.splitlines()
    if exc.lineno:
        for number in range(max(1, exc.lineno - 4), min(len(generated_lines), exc.lineno + 4) + 1):
            print(f"{number:5}: {generated_lines[number - 1]}")
            if number == exc.lineno:
                print("       " + " " * max(0, (exc.offset or 1) - 1) + "^")
    sys.exit(1)

backup = SERVER.with_name(
    f"server.py.pre-repair-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
)
backup.write_bytes(SERVER.read_bytes())
SERVER.write_text(patched, encoding="utf-8", newline="\n")
print("SUCCESS: server.py routing section repaired and Python syntax validated.")
print(f"Updated file size: {SERVER.stat().st_size} bytes")
print(f"Backup saved to: {backup.name}")
print("Next: stop the MONSTER AI server, then restart it from C:\\OmniChat.")
