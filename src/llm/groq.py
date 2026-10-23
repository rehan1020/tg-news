"""Groq API adapter (fallback summarizer)."""

from __future__ import annotations

import httpx

from src.bot.logger import get_logger
from src.llm.provider import SYSTEM_PROMPT, LLMProvider, validate_summary_output

logger = get_logger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
)


class GroqProvider(LLMProvider):
    """Summarizer using Groq OpenAI-compatible API."""

    def __init__(self, api_key: str, timeout: float = 12.0) -> None:
        self._api_key = api_key.strip().strip("'\"") if api_key else ""
        self._timeout = timeout

    async def summarize(self, title: str, text: str) -> str | None:
        """Call Groq to summarize the article."""
        if not self._api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        user_content = (
            f"Title: {title}\n\n"
            f"Article text:\n{text[:3000]}\n\n"
            "Please provide a 2 to 4 bullet factual summary."
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for model in GROQ_MODELS:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 250,
                    }
                    resp = await client.post(GROQ_API_URL, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            raw_text = choices[0].get("message", {}).get("content", "")
                            is_valid, validated = validate_summary_output(raw_text)
                            if is_valid:
                                return validated
                            logger.warning("groq output failed validation")
                        return None
                    elif resp.status_code == 404:
                        logger.info(
                            "groq model not found, trying alternate model",
                            extra={"model": model, "body": resp.text[:150]},
                        )
                        continue
                    elif resp.status_code == 429:
                        logger.warning(
                            "groq quota exhausted (429)", extra={"body": resp.text[:150]}
                        )
                        return None
                    else:
                        logger.warning(
                            "groq returned non-200",
                            extra={"status": resp.status_code, "body": resp.text[:150]},
                        )
                        return None
        except Exception as e:
            logger.warning("groq request exception", extra={"error": str(e)})

        return None
