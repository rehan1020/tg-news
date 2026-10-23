"""LLM orchestrator: manages budgets, primary/fallback handoff, and snippet fallback."""

from __future__ import annotations

import re
import time

from src.bot.logger import get_logger
from src.extract.extractor import clean_html_to_text
from src.llm.gemini import GeminiProvider
from src.llm.groq import GroqProvider
from src.llm.provider import LLMProvider
from src.state.manager import BotState

logger = get_logger(__name__)

DAILY_CALL_LIMIT = 50
PER_RUN_CALL_LIMIT = 10


class LLMOrchestrator:
    """Coordinates LLM providers with rate budgeting and fallback degradation."""

    def __init__(
        self,
        gemini_api_key: str,
        groq_api_key: str | None = None,
        daily_limit: int = DAILY_CALL_LIMIT,
        run_limit: int = PER_RUN_CALL_LIMIT,
    ) -> None:
        self._primary: LLMProvider | None = (
            GeminiProvider(gemini_api_key) if gemini_api_key else None
        )
        self._fallback: LLMProvider | None = GroqProvider(groq_api_key) if groq_api_key else None
        self._daily_limit = daily_limit
        self._run_limit = run_limit
        self._calls_this_run = 0

    def _check_and_update_budget(self, state: BotState) -> bool:
        """Verify daily and per-run budgets. Returns True if call is permitted."""
        today = time.strftime("%Y-%m-%d")
        usage = state.llm_usage

        if usage.get("day") != today:
            usage["day"] = today
            usage["calls_today"] = 0
            usage["tokens_today"] = 0

        if usage.get("calls_today", 0) >= self._daily_limit:
            logger.info("daily LLM budget limit reached")
            return False

        if self._calls_this_run >= self._run_limit:
            logger.info("per-run LLM budget limit reached")
            return False

        return True

    def _record_call(self, state: BotState) -> None:
        """Record successful LLM invocation in usage state."""
        self._calls_this_run += 1
        state.llm_usage["calls_today"] = state.llm_usage.get("calls_today", 0) + 1

    async def summarize_story(
        self,
        title: str,
        text: str,
        snippet: str,
        state: BotState,
    ) -> tuple[str, bool]:
        """Summarize story via primary LLM, Groq fallback, or snippet degradation.

        Returns:
            (summary_bullets, is_rss_only)
        """
        if not self._check_and_update_budget(state):
            return self._format_snippet_fallback(snippet, text), True

        # Try Gemini primary
        if self._primary:
            summary = await self._primary.summarize(title, text)
            if summary:
                self._record_call(state)
                return summary, False
            logger.info("primary LLM failed or quota exhausted; trying fallback")

        # Try Groq fallback
        if self._fallback:
            summary = await self._fallback.summarize(title, text)
            if summary:
                self._record_call(state)
                return summary, False
            logger.info("fallback LLM failed; degrading to RSS snippet")

        # Degrade to snippet
        return self._format_snippet_fallback(snippet, text), True

    @staticmethod
    def _format_snippet_fallback(snippet: str, text: str = "") -> str:
        """Format an RSS snippet or extracted text as clean bullet text."""
        clean = clean_html_to_text(snippet).strip() if snippet else ""

        # If snippet was empty or only had an image tag, try extracted article text
        if len(clean) < 15 and text:
            candidate = clean_html_to_text(text).strip()
            if candidate and len(candidate) >= 15:
                clean = candidate

        if not clean or len(clean) < 10:
            return "• Headline report — full text available at the original source."

        # Truncate cleanly without cutting words or breaking mid-sentence
        if len(clean) > 260:
            match = re.search(r"^(.*?[\.!\?])(?:\s|$)", clean[:280])
            if match and len(match.group(1)) >= 50:
                clean = match.group(1).strip()
            else:
                last_space = clean[:250].rfind(" ")
                if last_space > 80:
                    clean = clean[:last_space].rstrip() + "..."
                else:
                    clean = clean[:247].rstrip() + "..."

        return f"• {clean}"
