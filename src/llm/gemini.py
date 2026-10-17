"""Google Gemini API adapter (primary summarizer)."""

from __future__ import annotations

import httpx

from src.bot.logger import get_logger
from src.llm.provider import SYSTEM_PROMPT, LLMProvider, validate_summary_output

logger = get_logger(__name__)

GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    """Summarizer using Google Gemini REST API."""

    def __init__(self, api_key: str, timeout: float = 12.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def summarize(self, title: str, text: str) -> str | None:
        """Call Gemini to summarize the article."""
        if not self._api_key:
            return None

        url = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={self._api_key}"

        user_content = (
            f"Title: {title}\n\n"
            f"Article text:\n{text[:3000]}\n\n"
            "Please provide a 2 to 4 bullet factual summary."
        )

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 250,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        cand_parts = candidates[0].get("content", {}).get("parts", [{}])
                        raw_text = cand_parts[0].get("text", "")
                        is_valid, validated = validate_summary_output(raw_text)
                        if is_valid:
                            return validated
                        logger.warning("gemini output failed validation")
                elif resp.status_code == 429:
                    logger.warning("gemini quota exhausted (429)")
                else:
                    logger.warning("gemini returned non-200", extra={"status": resp.status_code})
        except Exception as e:
            logger.warning("gemini request exception", extra={"error": str(e)})

        return None
