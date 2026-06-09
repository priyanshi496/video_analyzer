import logging
from pathlib import Path
"""
llm.py — OpenRouter API caller with retry, rate-limiting, and fallback models.
"""

import time
import json
import random
import requests
import threading

from config import CONFIG

api_lock = threading.Lock()
LAST_REQUEST_TIME = 0.0


class NVIDIATokenTracker:
    def __init__(self, log_file="token_usage.log"):
        self.log_file = Path(log_file)
        self.lock = threading.Lock()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def track_usage(self, provider: str, model: str, input_tokens: int, output_tokens: int):
        with self.lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            
            # Log to file
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = (
                f"[{timestamp}] Provider={provider} | Model={model} | "
                f"Input={input_tokens} | Output={output_tokens} | "
                f"Accum_Input={self.total_input_tokens} | Accum_Output={self.total_output_tokens}\n"
            )
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
            except Exception as e:
                logging.warning(f"Failed to write to token log: {e}")

    def get_total_usage(self):
        with self.lock:
            return {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total": self.total_input_tokens + self.total_output_tokens
            }


token_tracker = NVIDIATokenTracker()
# API metrics and health counters
NIM_RETRY_COUNT = 0
OPENROUTER_FALLBACK_COUNT = 0
NVIDIA_FAIL_COUNT = 0
NVIDIA_MAX_FAILS = 3
NVIDIA_UNHEALTHY = False


class NIMRateLimiter:
    def __init__(self, max_rpm=35):
        self.max_rpm = max_rpm
        self.request_times = []
        self.lock = threading.Lock()

    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            # Retain only timestamps from the last 60 seconds
            self.request_times = [t for t in self.request_times if now - t < 60]
            if len(self.request_times) >= self.max_rpm:
                # Sleep until the oldest request falls out of the 60-second window
                wait_dur = 60.0 - (now - self.request_times[0])
                if wait_dur > 0:
                    logging.info(f"  ⏳ NIM rate limit threshold reached ({self.max_rpm} RPM). Pre-emptively throttling for {wait_dur:.2f}s...")
                    time.sleep(wait_dur)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 60]
            self.request_times.append(time.time())


nim_limiter = NIMRateLimiter(max_rpm=35)


def reset_nvidia_health():
    global NVIDIA_FAIL_COUNT, NVIDIA_UNHEALTHY
    NVIDIA_FAIL_COUNT = 0
    NVIDIA_UNHEALTHY = False


def mark_nvidia_failed():
    global NVIDIA_FAIL_COUNT, NVIDIA_UNHEALTHY
    NVIDIA_FAIL_COUNT += 1
    if NVIDIA_FAIL_COUNT >= NVIDIA_MAX_FAILS:
        if not NVIDIA_UNHEALTHY:
            logging.warning(f"⚠️ NVIDIA NIM has failed {NVIDIA_FAIL_COUNT} times consecutively. Tripping circuit breaker: routing to OpenRouter fallbacks.")
            NVIDIA_UNHEALTHY = True


def get_api_metrics():
    return {
        "nim_retries": NIM_RETRY_COUNT,
        "openrouter_fallbacks": OPENROUTER_FALLBACK_COUNT,
        "nvidia_circuit_broken": NVIDIA_UNHEALTHY
    }


def _build_headers(api_key: str) -> dict:
    return {
        "Authorization":  f"Bearer {api_key}",
        "Content-Type":   "application/json",
        "HTTP-Referer":   "https://github.com/video-analyzer",
        "X-Title":        "Video Timeline Analyzer",
    }


RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def backoff_sleep(attempt, retry_after=None, base=2.0, cap=60):
    if retry_after is not None:
        wait = retry_after
    else:
        wait = min(cap, base * (2 ** attempt))
    wait += random.uniform(0, 1.0)
    logging.info(f"  ⏳ Retrying API call in {wait:.2f}s (attempt {attempt+1})...")
    time.sleep(wait)


def _post_with_retry(payload: dict, headers: dict, timeout: int, label: str = "") -> tuple:
    """
    Single-model retry loop with exponential backoff, jitter, rate limiting, and circuit breaker integration.
    Returns (text, None) on success or (None, err) on failure.
    """
    global LAST_REQUEST_TIME, NIM_RETRY_COUNT, OPENROUTER_FALLBACK_COUNT
    last_err = None

    payload_copy = dict(payload)
    model_name = payload_copy.get("model", "")
    
    # Setup reasoning parameters and temperature if it is the Nemotron reasoning model
    if "nemotron-3-nano-omni-30b-a3b-reasoning" in model_name:
        payload_copy["chat_template_kwargs"] = {"enable_thinking": True}
        payload_copy["reasoning_budget"] = 128
        payload_copy["temperature"] = 0.0
        payload_copy["max_tokens"] = min(payload_copy.get("max_tokens", 1200), 1200)

    import os
    # Route request and select appropriate API key based on the model prefix and circuit health
    if model_name.startswith("nvidia/") and not model_name.endswith(":free") and os.getenv("NVIDIA_API_KEY") and not NVIDIA_UNHEALTHY:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        provider = "NVIDIA NIM"
        target_key = os.getenv("NVIDIA_API_KEY")
        
        # Ensure system prompt for formatting rules
        messages = payload_copy.get("messages", [])
        if messages and messages[0].get("role") != "system":
            system_msg = {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema. Include best_segments at the root. No markdown, no code fences, no extra text. Your response must begin with { and end with }."
            }
            payload_copy["messages"] = [system_msg] + messages
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        provider = "OpenRouter"
        target_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        # Check if fallback provider triggered
        if model_name.startswith("nvidia/") and not model_name.endswith(":free") and NVIDIA_UNHEALTHY:
            # We must map to the OpenRouter fallback model equivalent
            payload_copy["model"] = f"{model_name}:free"
            logging.info(f"  🔀 NVIDIA circuit broken! Automatically re-routed to OpenRouter fallback model: {payload_copy['model']}")
        # Also inject system message for OpenRouter route
        messages = payload_copy.get("messages", [])
        if messages and messages[0].get("role") != "system":
            system_msg = {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema. Include best_segments at the root. No markdown, no code fences, no extra text. Your response must begin with { and end with }."
            }
            payload_copy["messages"] = [system_msg] + messages

    # Rebuild headers with the correct API key for this target
    req_headers = dict(headers)
    if target_key:
        req_headers["Authorization"] = f"Bearer {target_key}"

    # Perform retry loop
    max_retries = CONFIG.get("max_retries", 3)
    base_delay = 1.5
    cap_delay = 16.0

    for attempt in range(max_retries):
        # Throttle NIM requests pre-emptively
        if provider == "NVIDIA NIM":
            nim_limiter.wait_if_needed()
        else:
            with api_lock:
                elapsed = time.time() - LAST_REQUEST_TIME
                gap = CONFIG["min_request_gap_sec"]
                if elapsed < gap:
                    time.sleep(gap - elapsed)
                LAST_REQUEST_TIME = time.time()

        if attempt == 0:
            logging.info(f"  ⚡ Routing request to {provider} ({url}) with model {payload_copy.get('model')}")

        try:
            r = requests.post(
                url,
                headers=req_headers,
                data=json.dumps(payload_copy),
                timeout=timeout,
            )

            # Check status codes and raise specific errors
            if r.status_code == 400:
                raise requests.HTTPError("400 Bad Request (Non-retryable)", response=r)
            
            if r.status_code in RETRYABLE_STATUS:
                # Get retry duration from header if present
                ra = r.headers.get("Retry-After")
                if ra and ra.replace(".", "", 1).isdigit():
                    sleep_for = float(ra)
                else:
                    sleep_for = min(cap_delay, base_delay * (2 ** attempt))
                sleep_for += random.uniform(0, 1.0)
                logging.warning(
                    f"  ↻ {provider} [{model_name}] retry {attempt + 1} in {sleep_for:.1f}s — "
                    f"HTTP {r.status_code}: {r.text[:300]}"
                )
                time.sleep(sleep_for)
                if provider == "NVIDIA NIM":
                    NIM_RETRY_COUNT += 1
                    mark_nvidia_failed()
                else:
                    OPENROUTER_FALLBACK_COUNT += 1
                continue
            
            if r.status_code != 200:
                raise requests.HTTPError(f"HTTP {r.status_code} Non-retryable Error", response=r)

            try:
                resp = r.json()
            except (json.JSONDecodeError, ValueError) as je:
                snippet = r.text[:300].replace('\n', ' ')
                raise ValueError(f"Invalid JSON response from server: {je}. Response snippet: {snippet}")

            if "choices" not in resp:
                raise ValueError(f"Missing choices in response object: {str(resp)[:200]}")
            
            message_obj = resp["choices"][0]["message"]
            
            # Print/log the reasoning content if present
            reasoning = message_obj.get("reasoning_content")
            if reasoning:
                logging.info(f"  🧠 Reasoning:\n{reasoning}\n")

            # Track token usage if available in response metadata
            usage = resp.get("usage", {})
            input_toks = usage.get("prompt_tokens", 0)
            output_toks = usage.get("completion_tokens", 0)
            if input_toks or output_toks:
                token_tracker.track_usage(provider, payload_copy.get("model", ""), input_toks, output_toks)

            # Success: reset health counters
            if provider == "NVIDIA NIM":
                reset_nvidia_health()

            content = message_obj.get("content")
            if not content or not content.strip():
                raise ValueError("Model returned empty content")
            # Strip any reasoning preamble before first { (plain-text thinking leak)
            # Some models reason in free text before outputting JSON
            stripped = content.strip()
            first_brace = stripped.find("{")
            if first_brace > 0:
                logging.info(f"  ✂️ Stripping {first_brace} chars of pre-JSON preamble from model response")
                content = stripped[first_brace:]
            return content, None

        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if provider == "NVIDIA NIM":
                NIM_RETRY_COUNT += 1
                mark_nvidia_failed()
            else:
                OPENROUTER_FALLBACK_COUNT += 1

            sleep_for = min(cap_delay, base_delay * (2 ** attempt)) + random.uniform(0, 1.0)
            logging.warning(
                f"  ↻ {provider} [{model_name}] retry {attempt + 1} in {sleep_for:.1f}s — {type(e).__name__}: {e}"
            )
            time.sleep(sleep_for)

        except requests.HTTPError as e:
            last_err = e
            status = e.response.status_code if e.response is not None else None
            
            if status not in RETRYABLE_STATUS:
                # Non-retryable HTTP Error (e.g. 400, 401, 403, 404)
                if provider == "NVIDIA NIM":
                    mark_nvidia_failed()
                break

            # Retryable HTTP Error (e.g. 429, 500, 502, 503, 504)
            if provider == "NVIDIA NIM":
                NIM_RETRY_COUNT += 1
                mark_nvidia_failed()
            else:
                OPENROUTER_FALLBACK_COUNT += 1

            ra = e.response.headers.get("Retry-After") if e.response is not None else None
            if ra and ra.replace(".", "", 1).isdigit():
                sleep_for = float(ra)
            else:
                sleep_for = min(cap_delay, base_delay * (2 ** attempt))
            sleep_for += random.uniform(0, 1.0)
            logging.warning(
                f"  ↻ {provider} [{model_name}] HTTP {status} retryable error (attempt {attempt+1}): {e}"
            )
            time.sleep(sleep_for)

        except Exception as e:
            last_err = e
            sleep_for = min(cap_delay, base_delay * (2 ** attempt)) + random.uniform(0, 1.0)
            logging.warning(
                f"  ↻ {provider} [{model_name}] unexpected exception (attempt {attempt+1}): {e}"
            )
            time.sleep(sleep_for)

    return None, last_err


def call_openrouter_multiimage(
    frame_paths: list,
    prompt: str,
    api_key: str,
    model: str,
) -> str:
    """
    Vision call — tries primary model then each fallback in order.
    frame_paths: local file paths that will be base64-encoded.
    """
    import os
    api_key = os.getenv("NVIDIA_API_KEY") or api_key
    import base64
    import io
    from PIL import Image

    def to_data_url(path):
        img = Image.open(path)
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    limit = CONFIG.get("image_limit_per_request", 8)
    if len(frame_paths) > limit:
        logging.info(f"  ⚠️  Truncating {len(frame_paths)} images → {limit}")
        frame_paths = frame_paths[:limit]

    content = [{"type": "text", "text": prompt}]
    for p in frame_paths:
        content.append({"type": "image_url", "image_url": {"url": to_data_url(p)}})

    headers = _build_headers(api_key)
    models_to_try = [model] + CONFIG.get("fallback_models", [])
    last_err = None

    video_name = Path(frame_paths[0]).name if frame_paths else "unknown"
    if "_frame" in video_name:
        video_name = video_name.split("_frame")[0]
    elif "_" in video_name:
        video_name = video_name.split("_")[0]

    for model_name in models_to_try:
        payload = {
            "model":       model_name,
            "messages":    [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens":  CONFIG.get("max_tokens_vision", 1500),
        }
        display_label = f"{model_name} [{video_name}]"
        logging.info(f"  → Trying: {display_label}")
        result, err = _post_with_retry(payload, headers, timeout=120, label=display_label)
        if result is not None:
            # Validate if the result contains a valid JSON segment structure.
            # If the output is non-JSON or a repetition loop, raise ValueError and fall back.
            try:
                from prompts import parse_json_response
                parsed = parse_json_response(result)
                if not isinstance(parsed, dict) or ("best_segments" not in parsed and "segments" not in parsed and "journey_phase" not in parsed):
                    raise ValueError("Parsed JSON response is missing required highlight segments keys.")
                
                if model_name != model:
                    logging.info(f"  ✓ Fallback succeeded: {display_label}")
                return result
            except Exception as je:
                logging.warning(f"  ✗ {display_label} returned invalid/hallucinated JSON structure: {je}. Attempting repair...")
                try:
                    repaired_raw = repair_json_output_text(result, api_key)
                    parsed = parse_json_response(repaired_raw)
                    if isinstance(parsed, dict) and ("best_segments" in parsed or "segments" in parsed or "journey_phase" in parsed):
                        logging.info(f"  ✓ Repaired JSON successfully for {display_label}!")
                        return repaired_raw
                except Exception as re:
                    logging.warning(f"  ✗ Repair failed for {display_label}: {re}")
                last_err = je
        else:
            last_err = err
        logging.info(f"  ✗ {display_label} failed: {err}")

    raise RuntimeError(f"All models failed for {video_name}. Last error: {last_err}")


def call_openrouter_text(prompt: str, api_key: str, model: str, fallbacks: list = None) -> str:
    """Text-only call — tries primary model then each fallback."""
    import os
    api_key = os.getenv("OPENROUTER_API_KEY") or api_key
    headers = _build_headers(api_key)
    if fallbacks is None:
        fallbacks = CONFIG.get("fallback_models", [])
    models_to_try = [model] + fallbacks
    last_err = None

    for model_name in models_to_try:
        payload = {
            "model":    model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        result, err = _post_with_retry(payload, headers, timeout=30, label=model_name)
        if result is not None:
            return result
        last_err = err
        logging.info(f"  ✗ Text model {model_name} failed: {err}")

    raise RuntimeError(f"All models failed for text call. Last error: {last_err}")


def repair_json_output_text(bad_text: str, api_key: str) -> str:
    """
    Calls OpenRouter's text model to repair and format a malformed JSON string.
    """
    prompt = f"""You are a JSON repair assistant.
We received a malformed, truncated, or incomplete JSON response from a vision model.
Your task is to parse, repair, and format this content into a strictly valid JSON object matching the target schema.

TARGET SCHEMA:
{{
  "video_summary": "string describing the video contents",
  "detected_scenario": "string (A|B|C|D|E|F)",
  "overall_mood": "string",
  "overall_vibe": "string",
  "editor_reasoning": "string",
  "key_moments": [
    {{
      "timestamp_sec": float,
      "description": "string"
    }}
  ],
  "best_segments": [
    {{
      "start_sec": float,
      "end_sec": float,
      "what_happens": "string",
      "mood": "string",
      "energy": integer (1-10),
      "visual_quality": integer (1-10),
      "instagrammable": integer (1-10),
      "story_value": integer (1-10),
      "reason": "string",
      "priority": integer (1-5),
      "narrative_role": "string (setup|action|climax|reaction|payoff)",
      "clip_type_applied": "string",
      "location_tag": "string (snake_case)",
      "journey_phase": "string (approach|arrival|exterior|interior|detail|climax)",
      "scene_category": "string (scenery|people|action|food|vehicle|mixed)",
      "primary_subjects": ["string"]
    }}
  ]
}}

CORRUPT/MALFORMED JSON STRING:
{bad_text}

CRITICAL RULES:
1. Ensure the output is a single, valid JSON object matching the target schema.
2. The root object MUST contain the "best_segments" array. If "best_segments" is empty or missing, extract segment information from other keys (like "segments" or "moments") and map them to "best_segments".
3. Correct any missing closing brackets, brackets mismatch, trailing commas, or quotes.
4. Output ONLY the raw JSON string. Do NOT wrap it in markdown code blocks (like ```json) or add any conversational preamble.
"""
    text_model = CONFIG.get("story_order_model", "openrouter/owl-alpha")
    fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
    try:
        logging.info("  🔧 Attempting early text repair on malformed response...")
        return call_openrouter_text(prompt, api_key, model=text_model, fallbacks=fallbacks)
    except Exception as e:
        logging.warning(f"  ✗ Early text repair failed: {e}")
        raise e
