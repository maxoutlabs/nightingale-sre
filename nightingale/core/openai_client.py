"""
Nightingale OpenAI Client
Replaces the Gemini client with GPT-4o + GPT-4o-mini.

- gpt-4o: main reasoning and fix generation (structured outputs)
- gpt-4o-mini: cheap classification (risk assessment)
- Response caching: same SHA-256 key approach
- Exponential backoff on rate limits
- Drop-in compatible with the old GeminiClient interface
"""
import os
import time
import json
import hashlib
from typing import Optional, Dict, Any, Type, TypeVar, List
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from openai import OpenAI, APIError, RateLimitError, APIConnectionError

from nightingale.config import config
from nightingale.core.logger import logger

T = TypeVar("T", bound=BaseModel)

SDK_PACKAGE = "openai"
try:
    import openai as _openai_pkg
    SDK_VERSION = getattr(_openai_pkg, "__version__", "unknown")
except Exception:
    SDK_VERSION = "unknown"


# ── Exceptions ───────────────────────────────────────────────────────────────

class OpenAIClientError(Exception):
    """Base exception for OpenAI client errors."""


class QuotaExhaustedError(OpenAIClientError):
    """All retries exhausted."""


class SchemaValidationError(OpenAIClientError):
    """Structured output parsing failed."""


# ── Response cache ────────────────────────────────────────────────────────────

class ResponseCache:
    """Persistent SHA-256-keyed response cache."""

    def __init__(self, cache_dir: str = ".nightingale_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = True

    def _key(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()

    def get(self, prompt: str) -> Optional[str]:
        if not self.enabled:
            return None
        path = self.cache_dir / f"{self._key(prompt)}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info("[CACHE HIT] Using cached response", component="openai")
                return data["response"]
            except Exception:
                pass
        return None

    def put(self, prompt: str, response_text: str):
        if not self.enabled:
            return
        path = self.cache_dir / f"{self._key(prompt)}.json"
        try:
            path.write_text(json.dumps({
                "prompt_hash": self._key(prompt),
                "response": response_text,
                "cached_at": datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass


# ── Main client ───────────────────────────────────────────────────────────────

class OpenAIClient:
    """
    Production OpenAI client.

    Features:
    - gpt-4o structured outputs via beta.chat.completions.parse()
    - gpt-4o-mini for cheap risk classification
    - SHA-256 response caching
    - Record mode (replay cached responses, no API calls)
    - Exponential backoff on rate limits / transient errors
    """

    MAX_RETRIES = 3
    INITIAL_DELAY = 2.0
    MAX_DELAY = 30.0
    BACKOFF_FACTOR = 2.0

    def __init__(self, record_mode: bool = False):
        self.record_mode = record_mode
        self.cache = ResponseCache()

        self.api_key = os.getenv("OPENAI_API_KEY", "")

        if not self.api_key and not self.record_mode:
            raise OpenAIClientError(
                "OPENAI_API_KEY not set.\n"
                "Set it using:\n"
                "  PowerShell:   $env:OPENAI_API_KEY = 'sk-...'\n"
                "  Linux/macOS:  export OPENAI_API_KEY='sk-...'"
            )

        self.model_name = config.get("openai.model", "gpt-4o")
        self.mini_model = config.get("openai.mini_model", "gpt-4o-mini")

        self.client: Optional[OpenAI] = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
            masked = self.api_key[:8] + "..." + self.api_key[-4:]
            logger.info(f"OpenAI client initialized", component="openai")
            logger.info(f"  SDK:      {SDK_PACKAGE} v{SDK_VERSION}", component="openai")
            logger.info(f"  Model:    {self.model_name}", component="openai")
            logger.info(f"  Mini:     {self.mini_model}", component="openai")
            logger.info(f"  Key:      {masked}", component="openai")

        # Rate limit tracking
        self.requests_this_minute = 0
        self.minute_start = time.time()

        # Metrics
        self.total_tokens = 0
        self.total_calls = 0

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(self):
        current = time.time()
        if current - self.minute_start >= 60:
            self.requests_this_minute = 0
            self.minute_start = current
        max_rpm = config.get("openai.rate_limit", 60)
        if self.requests_this_minute >= max_rpm:
            sleep_time = 60 - (current - self.minute_start) + 1
            logger.warning(
                f"Rate limit ({self.requests_this_minute}/{max_rpm} RPM), "
                f"sleeping {sleep_time:.1f}s"
            )
            time.sleep(sleep_time)
            self.requests_this_minute = 0
            self.minute_start = time.time()

    # ── Retry with backoff ────────────────────────────────────────────────────

    def _retry_with_backoff(self, func, *args, **kwargs):
        delay = self.INITIAL_DELAY
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._check_rate_limit()
                self.requests_this_minute += 1
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_quota = any(k in error_str for k in ["429", "rate", "quota", "resource_exhausted"])
                is_transient = any(k in error_str for k in ["500", "503", "timeout", "unavailable", "connection"])

                if (is_quota or is_transient) and attempt < self.MAX_RETRIES:
                    label = "Rate limited" if is_quota else "Transient error"
                    logger.warning(f"{label}, retrying in {delay:.0f}s (attempt {attempt}/{self.MAX_RETRIES})")
                    time.sleep(delay)
                    delay = min(delay * self.BACKOFF_FACTOR, self.MAX_DELAY)
                    continue

                if is_quota or is_transient:
                    raise QuotaExhaustedError(
                        f"API quota exhausted after {self.MAX_RETRIES} retries. Last error: {e}"
                    )
                raise  # Non-retryable

        raise QuotaExhaustedError(f"Max retries exceeded: {last_error}")

    # ── Core generation ───────────────────────────────────────────────────────

    def generate(self, prompt: str, model: str = "", incident_id: str = "") -> str:
        """Generate raw text. Caches responses by prompt hash."""
        cached = self.cache.get(prompt)
        if cached is not None:
            self.total_calls += 1
            return cached

        if self.record_mode:
            raise OpenAIClientError(
                "Record mode ON but no cached response for this prompt. "
                "Run once without --record-mode to populate the cache."
            )

        use_model = model or self.model_name
        start_time = time.time()

        def _call():
            return self.client.chat.completions.create(
                model=use_model,
                messages=[
                    {"role": "system", "content": "You are an expert SRE and software engineer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=8192,
            )

        response = self._retry_with_backoff(_call)
        duration_ms = int((time.time() - start_time) * 1000)

        tokens = response.usage.total_tokens if response.usage else 0
        self.total_tokens += tokens
        self.total_calls += 1

        logger.api_call(incident_id, use_model, tokens, duration_ms)

        text = response.choices[0].message.content or ""
        self.cache.put(prompt, text)
        return text

    # ── Structured output generation ──────────────────────────────────────────

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        model: str = "",
        incident_id: str = "",
        max_validation_retries: int = 3,
    ) -> T:
        """
        Generate a validated structured response using OpenAI Structured Outputs.

        Uses beta.chat.completions.parse() with the Pydantic model as response_format.
        Falls back to JSON prompt + manual parsing if structured outputs fail.
        """
        use_model = model or self.model_name
        cache_key = f"structured:{response_model.__name__}:{use_model}:{prompt}"

        # Check cache
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.total_calls += 1
            try:
                data = json.loads(cached)
                return response_model.model_validate(data)
            except Exception:
                pass  # Cache corrupt — fall through to API

        if self.record_mode:
            raise OpenAIClientError("Record mode ON but no cached response.")

        start_time = time.time()

        # Attempt 1: OpenAI Structured Outputs (native Pydantic integration)
        try:
            def _structured_call():
                return self.client.beta.chat.completions.parse(
                    model=use_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert SRE and software engineer. "
                                "Analyze CI/CD failures and provide precise, minimal fixes. "
                                "Always respond with complete file contents, not diffs."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format=response_model,
                    temperature=0.2,
                )

            response = self._retry_with_backoff(_structured_call)
            duration_ms = int((time.time() - start_time) * 1000)

            tokens = response.usage.total_tokens if response.usage else 0
            self.total_tokens += tokens
            self.total_calls += 1
            logger.api_call(incident_id, use_model, tokens, duration_ms)

            parsed = response.choices[0].message.parsed

            if parsed is not None:
                # Cache serialized result
                try:
                    self.cache.put(cache_key, parsed.model_dump_json())
                except Exception:
                    pass
                return parsed

            # Model refused (refusal field set)
            refusal = getattr(response.choices[0].message, "refusal", None)
            if refusal:
                logger.warning(f"Model refused structured output: {refusal}. Falling back to JSON mode.")

        except Exception as e:
            logger.warning(f"Structured output failed ({e}), falling back to JSON prompt mode.")

        # Fallback: JSON prompt mode
        return self._generate_structured_json_fallback(
            prompt, response_model, use_model, incident_id, max_validation_retries
        )

    def _generate_structured_json_fallback(
        self,
        prompt: str,
        response_model: Type[T],
        model: str,
        incident_id: str,
        max_validation_retries: int,
    ) -> T:
        """JSON prompt fallback when structured outputs aren't available."""
        schema = response_model.model_json_schema()
        schema_str = json.dumps(schema, indent=2)

        system_prompt = (
            "You are an expert SRE and software engineer. "
            "Respond ONLY with valid JSON matching the provided schema. "
            "No markdown, no code fences, no extra text."
        )

        user_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL: Respond with ONLY valid JSON matching this schema:\n"
            f"{schema_str}\n\n"
            "For files_to_change, use EXACTLY these field names:\n"
            '  {"file_path": "path/to/file.py", "change_type": "modify", "content": "...full file content..."}\n'
        )

        for attempt in range(max_validation_retries):
            raw = self.generate(user_prompt, model=model, incident_id=incident_id)

            # Strip markdown fences
            cleaned = raw.strip()
            for prefix in ["```json", "```"]:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error (fallback attempt {attempt + 1}): {e}")
                if attempt < max_validation_retries - 1:
                    user_prompt = (
                        f"Your previous response was not valid JSON. Error: {e}\n\n"
                        f"Respond with ONLY raw valid JSON:\n{schema_str}"
                    )
                    self.cache.enabled = False
                    continue
                raise SchemaValidationError(f"JSON parsing failed after {max_validation_retries} attempts: {e}")
            finally:
                self.cache.enabled = True

            try:
                return response_model.model_validate(data)
            except Exception as e:
                logger.warning(f"Pydantic validation error (fallback attempt {attempt + 1}): {e}")
                if attempt < max_validation_retries - 1:
                    user_prompt = (
                        f"Your JSON had wrong fields. Error: {e}\n\n"
                        f"Fix the fields and output ONLY valid JSON:\n{schema_str}"
                    )
                    self.cache.enabled = False
                    continue
                raise SchemaValidationError(f"Schema validation failed: {e}")
            finally:
                self.cache.enabled = True

        raise SchemaValidationError("Max validation retries exceeded")

    # ── Risk classification (gpt-4o-mini) ────────────────────────────────────

    def classify_risk(self, files_changed: List[str], context: str = "") -> str:
        """
        Use gpt-4o-mini to classify the risk level of proposed file changes.
        Returns: 'low', 'medium', 'high', or 'critical'.
        """
        if not files_changed or not self.client:
            return "medium"

        files_summary = "\n".join(f"- {f}" for f in files_changed[:10])
        prompt = (
            f"Classify the deployment risk of these code changes.\n\n"
            f"Files changed:\n{files_summary}\n\n"
            f"Context: {context[:300] if context else 'Python CI fix'}\n\n"
            f"Risk levels:\n"
            f"- low: test files, docs, comments\n"
            f"- medium: utility functions, config files\n"
            f"- high: core logic, main modules, init files\n"
            f"- critical: auth, security, database, deploy scripts\n\n"
            f"Respond with ONLY one word: low, medium, high, or critical."
        )

        cache_key = f"risk:{prompt}"
        cached = self.cache.get(cache_key)
        if cached:
            result = cached.strip().lower()
            return result if result in {"low", "medium", "high", "critical"} else "medium"

        try:
            response = self.client.chat.completions.create(
                model=self.mini_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            )
            risk = (response.choices[0].message.content or "medium").strip().lower()
            risk = risk if risk in {"low", "medium", "high", "critical"} else "medium"
            self.cache.put(cache_key, risk)
            return risk
        except Exception as e:
            logger.warning(f"Risk classification failed, using default: {e}")
            return "medium"

    # ── Metrics ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "requests_this_minute": self.requests_this_minute,
            "model": self.model_name,
            "mini_model": self.mini_model,
        }


# ── Global singleton ──────────────────────────────────────────────────────────

_client: Optional[OpenAIClient] = None


def get_openai_client(record_mode: bool = False) -> OpenAIClient:
    """Get or create the global OpenAI client."""
    global _client
    if _client is None:
        _client = OpenAIClient(record_mode=record_mode)
    return _client


def reset_openai_client():
    """Reset the global client (for testing or re-init)."""
    global _client
    _client = None


def verify_api_key() -> Dict[str, Any]:
    """
    Verify the OpenAI API key with one minimal request.
    Returns dict with reachable, model, latency_ms, tokens, response.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {"reachable": False, "error": "OPENAI_API_KEY not set"}

    model_name = config.get("openai.model", "gpt-4o")
    client = OpenAI(api_key=api_key)

    start = time.time()
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Respond with the word OK."}],
            max_tokens=5,
            temperature=0,
        )
        latency_ms = int((time.time() - start) * 1000)
        tokens = response.usage.total_tokens if response.usage else 0
        return {
            "reachable": True,
            "model": model_name,
            "sdk": f"{SDK_PACKAGE} v{SDK_VERSION}",
            "latency_ms": latency_ms,
            "tokens": tokens,
            "response": (response.choices[0].message.content or "").strip(),
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        error_str = str(e).lower()
        is_quota = any(k in error_str for k in ["429", "quota", "rate"])
        return {
            "reachable": False,
            "quota_exhausted": is_quota,
            "error": str(e),
            "latency_ms": latency_ms,
            "model": model_name,
            "sdk": f"{SDK_PACKAGE} v{SDK_VERSION}",
        }
