import logging
import time
import json
import random
import requests
import threading
import os
import base64
import io
from PIL import Image

from app.core.config import settings
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

api_lock = threading.Lock()
LAST_REQUEST_TIME = 0.0

class NVIDIATokenTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def track_usage(self, provider: str, model: str, input_tokens: int, output_tokens: int):
        with self.lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

    def get_total_usage(self):
        with self.lock:
            return {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total": self.total_input_tokens + self.total_output_tokens
            }

token_tracker = NVIDIATokenTracker()
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
            self.request_times = [t for t in self.request_times if now - t < 60]
            if len(self.request_times) >= self.max_rpm:
                wait_dur = 60.0 - (now - self.request_times[0])
                if wait_dur > 0:
                    logger.info(f"  ⏳ NIM rate limit threshold reached ({self.max_rpm} RPM). Pre-emptively throttling for {wait_dur:.2f}s...")
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
            logger.warning(f"⚠️ NVIDIA NIM has failed {NVIDIA_FAIL_COUNT} times consecutively. Tripping circuit breaker: routing to OpenRouter fallbacks.")
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

def _post_with_retry(payload: dict, headers: dict, timeout: int, label: str = "") -> tuple:
    global LAST_REQUEST_TIME, NIM_RETRY_COUNT, OPENROUTER_FALLBACK_COUNT
    last_err = None

    payload_copy = dict(payload)
    model_name = payload_copy.get("model", "")
    
    if "nemotron-3-nano-omni-30b-a3b-reasoning" in model_name:
        payload_copy["chat_template_kwargs"] = {"enable_thinking": True}
        payload_copy["reasoning_budget"] = 128
        payload_copy["temperature"] = 0.0
        payload_copy["max_tokens"] = min(payload_copy.get("max_tokens", 2048), 2048)

    if model_name.startswith("nvidia/") and not model_name.endswith(":free") and settings.NVIDIA_API_KEY and not NVIDIA_UNHEALTHY:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        provider = "NVIDIA NIM"
        target_key = settings.NVIDIA_API_KEY
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        provider = "OpenRouter"
        target_key = settings.OPENROUTER_API_KEY or settings.NVIDIA_API_KEY
        if model_name.startswith("nvidia/") and not model_name.endswith(":free") and NVIDIA_UNHEALTHY:
            payload_copy["model"] = f"{model_name}:free"
            logger.info(f"  🔀 NVIDIA circuit broken! Automatically re-routed to OpenRouter fallback model: {payload_copy['model']}")

    req_headers = dict(headers)
    if target_key:
        req_headers["Authorization"] = f"Bearer {target_key}"

    max_retries = 3
    base_delay = 1.5
    cap_delay = 16.0

    for attempt in range(max_retries):
        if provider == "NVIDIA NIM":
            nim_limiter.wait_if_needed()
        else:
            with api_lock:
                elapsed = time.time() - LAST_REQUEST_TIME
                gap = 1.0 # default gap
                if elapsed < gap:
                    time.sleep(gap - elapsed)
                LAST_REQUEST_TIME = time.time()

        if attempt == 0:
            logger.info(f"  ⚡ Routing request to {provider} ({url}) with model {payload_copy.get('model')}")

        try:
            r = requests.post(url, headers=req_headers, data=json.dumps(payload_copy), timeout=timeout)

            if r.status_code == 400:
                raise requests.HTTPError("400 Bad Request (Non-retryable)", response=r)
            
            if r.status_code in RETRYABLE_STATUS:
                ra = r.headers.get("Retry-After")
                if ra and ra.replace(".", "", 1).isdigit():
                    sleep_for = float(ra)
                else:
                    sleep_for = min(cap_delay, base_delay * (2 ** attempt))
                sleep_for += random.uniform(0, 1.0)
                logger.warning(f"  ↻ {provider} [{model_name}] retry {attempt + 1} in {sleep_for:.1f}s — HTTP {r.status_code}")
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
            
            reasoning = message_obj.get("reasoning_content")
            if reasoning:
                logger.info(f"  🧠 Reasoning:\n{reasoning}\n")

            usage = resp.get("usage", {})
            input_toks = usage.get("prompt_tokens", 0)
            output_toks = usage.get("completion_tokens", 0)
            if input_toks or output_toks:
                token_tracker.track_usage(provider, payload_copy.get("model", ""), input_toks, output_toks)

            if provider == "NVIDIA NIM":
                reset_nvidia_health()

            content = message_obj.get("content")
            if not content or not content.strip():
                raise ValueError("Model returned empty content")
            
            stripped = content.strip()
            first_brace = stripped.find("{")
            if first_brace > 0:
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
            logger.warning(f"  ↻ {provider} [{model_name}] retry {attempt + 1} in {sleep_for:.1f}s — {type(e).__name__}: {e}")
            time.sleep(sleep_for)

        except requests.HTTPError as e:
            last_err = e
            status = e.response.status_code if e.response is not None else None
            
            if status not in RETRYABLE_STATUS:
                if provider == "NVIDIA NIM":
                    mark_nvidia_failed()
                break

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
            time.sleep(sleep_for)

        except Exception as e:
            last_err = e
            sleep_for = min(cap_delay, base_delay * (2 ** attempt)) + random.uniform(0, 1.0)
            time.sleep(sleep_for)

    return None, last_err

def call_openrouter_multiimage(
    frame_paths: list,
    prompt: str,
    model: str,
) -> str:
    api_key = settings.OPENROUTER_API_KEY
    def to_data_url(path):
        img = Image.open(path)
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    limit = 8
    if len(frame_paths) > limit:
        frame_paths = frame_paths[:limit]

    # ── DEBUG: confirm frames exist and have real content ──────────────────
    logger.info(f"  🖼  Preparing {len(frame_paths)} frame(s) for vision call:")
    for p in frame_paths:
        from pathlib import Path
        ppath = Path(p)
        exists = ppath.exists()
        size = ppath.stat().st_size if exists else 0
        logger.info(f"      {'✓' if exists and size > 0 else '✗'} {ppath.name}  exists={exists}  size={size}B")
    # ───────────────────────────────────────────────────────────────────────

    content = [{"type": "text", "text": prompt}]
    for p in frame_paths:
        content.append({"type": "image_url", "image_url": {"url": to_data_url(p)}})

    headers = _build_headers(api_key)
    models_to_try = [model, "google/gemini-3.5-flash"]
    last_err = None

    for model_name in models_to_try:
        payload = {
            "model":       model_name,
            "messages":    [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens":  1500,
        }
        result, err = _post_with_retry(payload, headers, timeout=120, label=model_name)
        if result is not None:
            try:
                from app.services.prompts_service import parse_json_response
                parsed = parse_json_response(result)
                if not isinstance(parsed, dict) or ("best_segments" not in parsed and "segments" not in parsed and "journey_phase" not in parsed):
                    raise ValueError("Parsed JSON response is missing required highlight segments keys.")
                return result
            except Exception as je:
                logger.warning(f"  ✗ {model_name} returned invalid structure: {je}. Attempting repair...")
                try:
                    repaired_raw = repair_json_output_text(result)
                    parsed = parse_json_response(repaired_raw)
                    if isinstance(parsed, dict) and ("best_segments" in parsed or "segments" in parsed or "journey_phase" in parsed):
                        return repaired_raw
                except Exception as re:
                    pass
                last_err = je
        else:
            last_err = err

    raise RuntimeError(f"All models failed. Last error: {last_err}")

def call_openrouter_text(prompt: str, model: str, fallbacks: list = None, temperature: float = 0.0) -> str:
    api_key = settings.OPENROUTER_API_KEY
    headers = _build_headers(api_key)
    if fallbacks is None:
        fallbacks = ["openai/gpt-3.5-turbo", "google/gemini-flash-1.5-8b"]
    models_to_try = [model] + fallbacks
    last_err = None

    for model_name in models_to_try:
        payload = {
            "model":    model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        result, err = _post_with_retry(payload, headers, timeout=30, label=model_name)
        if result is not None:
            return result
        last_err = err

    raise RuntimeError(f"All models failed for text call. Last error: {last_err}")

def repair_json_output_text(bad_text: str) -> str:
    prompt = f"You are a JSON repair assistant... (Schema omitted for brevity, fix this: {bad_text})"
    return call_openrouter_text(prompt, model="openrouter/owl-alpha")
