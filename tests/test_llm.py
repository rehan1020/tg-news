"""Tests for LLM adapters, output validation, and fallback orchestrator."""

from __future__ import annotations

import pytest
import respx

from src.llm.gemini import GeminiProvider
from src.llm.orchestrator import LLMOrchestrator
from src.llm.provider import validate_summary_output
from src.state.manager import BotState


class TestOutputValidation:
    def test_compliant_output_passes(self):
        valid_text = (
            "• Federal Reserve cuts interest rates by 25 basis points.\n"
            "• Inflation indicators slowed according to government report.\n"
            "• Global market indices responded positively to policy statement."
        )
        is_valid, cleaned = validate_summary_output(valid_text)
        assert is_valid is True
        assert cleaned.count("•") == 3

    def test_output_with_urls_rejected(self):
        injected = (
            "• Story summary point one about the rate cut.\n"
            "• Visit https://malicious.com for more info.\n"
            "• Story summary point three about inflation."
        )
        is_valid, _ = validate_summary_output(injected)
        assert is_valid is False

    def test_output_with_fewer_than_2_bullets_rejected(self):
        single = "• Only one single bullet point in this summary."
        is_valid, _ = validate_summary_output(single)
        assert is_valid is False

    def test_output_with_more_than_4_bullets_rejected(self):
        too_many = "\n".join(f"• Bullet point {i} with some news content" for i in range(6))
        is_valid, _ = validate_summary_output(too_many)
        assert is_valid is False


@pytest.mark.asyncio
@respx.mock
async def test_gemini_adapter_success():
    provider = GeminiProvider(api_key="mock")
    respx.post(url__startswith="https://generativelanguage.googleapis.com").respond(
        status_code=200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    "• Central bank announced a 25 bps policy rate reduction.\n"
                                    "• Decision aimed at sustaining employment stability.\n"
                                    "• Economic projections were revised higher for the quarter."
                                )
                            }
                        ]
                    }
                }
            ]
        },
    )

    summary = await provider.summarize("Rate Decision", "Full text of central bank release...")
    assert summary is not None
    assert summary.count("•") == 3


@pytest.mark.asyncio
@respx.mock
async def test_groq_fallback_when_gemini_fails():
    state = BotState()
    orchestrator = LLMOrchestrator(
        gemini_api_key="mock",
        groq_api_key="mock",
    )

    # Gemini returns 429 quota exhaustion
    respx.post(url__startswith="https://generativelanguage.googleapis.com").respond(status_code=429)

    # Groq returns 200 with valid summary
    respx.post(url__startswith="https://api.groq.com").respond(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            "• Headline event summarized via fallback provider.\n"
                            "• Financial indicators remain steady across sectors.\n"
                            "• Analysts expect gradual monetary adjustments."
                        )
                    }
                }
            ]
        },
    )

    summary, is_fallback = await orchestrator.summarize_story(
        title="Headline",
        text="Full text...",
        snippet="Short RSS snippet",
        state=state,
    )

    assert is_fallback is False
    assert "fallback provider" in summary
    assert state.llm_usage["calls_today"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_budget_exhaustion_degrades_to_snippet():
    state = BotState()
    # Set calls_today to exceed daily limit
    state.llm_usage["calls_today"] = 55

    orchestrator = LLMOrchestrator(
        gemini_api_key="mock",
        daily_limit=50,
    )

    snippet = "Government signs bilateral trade agreement."
    summary, is_fallback = await orchestrator.summarize_story(
        title="Trade Deal",
        text="Full text...",
        snippet=snippet,
        state=state,
    )

    assert is_fallback is True
    assert snippet in summary
