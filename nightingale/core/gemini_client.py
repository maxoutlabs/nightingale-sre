"""
Backward-compatibility shim.
Nightingale now uses OpenAI (gpt-4o) instead of Gemini.
All imports from this module still work via re-export.
"""
from nightingale.core.openai_client import (
    OpenAIClient as GeminiClient,
    OpenAIClientError as GeminiClientError,
    QuotaExhaustedError,
    SchemaValidationError,
    ResponseCache,
    get_openai_client as get_gemini_client,
    reset_openai_client as reset_gemini_client,
    verify_api_key,
    SDK_PACKAGE,
    SDK_VERSION,
)

__all__ = [
    "GeminiClient",
    "GeminiClientError",
    "QuotaExhaustedError",
    "SchemaValidationError",
    "ResponseCache",
    "get_gemini_client",
    "reset_gemini_client",
    "verify_api_key",
]
