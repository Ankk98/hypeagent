"""OpenAI-compatible LLM client with budget enforcement and usage recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI

from hypeagent.config.schema import LLMConfig
from hypeagent.db.repositories.usage import UsageRepository
from hypeagent.llm.budget import BudgetGuard

# Blended fallback when model-specific pricing is unknown (§9.2).
DEFAULT_COST_PER_TOKEN = 0.000002

# Per-model (input_usd_per_token, output_usd_per_token) estimates.
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.00000015, 0.0000006),
    "openai/gpt-4o": (0.0000025, 0.00001),
    "anthropic/claude-3.5-sonnet": (0.000003, 0.000015),
    "google/gemini-flash-1.5": (0.000000075, 0.0000003),
}


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost from token usage and a static per-model table."""
    rates = MODEL_COSTS.get(model)
    if rates is not None:
        input_rate, output_rate = rates
        return tokens_in * input_rate + tokens_out * output_rate
    total_tokens = tokens_in + tokens_out
    return total_tokens * DEFAULT_COST_PER_TOKEN


class LLMClient:
    """OpenAI-compatible chat completions client with budget checks and usage tracking."""

    def __init__(
        self,
        llm_config: LLMConfig,
        api_key: str,
        budget: BudgetGuard,
        usage: UsageRepository,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = llm_config
        self._budget = budget
        self._usage = usage
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": llm_config.base_url,
        }
        if http_client is not None:
            client_kwargs["http_client"] = http_client
        self._client = OpenAI(**client_kwargs)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        run_id: str,
        agent_id: str,
    ) -> LLMResponse:
        """
        Call POST /chat/completions, record usage, and enforce budget caps.

        Raises BudgetExceededError if a cap is already reached before the call.
        """
        self._budget.check()

        resolved_model = model or self._config.model
        resolved_temperature = (
            self._config.temperature if temperature is None else temperature
        )
        resolved_max_tokens = self._config.max_tokens if max_tokens is None else max_tokens

        response = self._client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "system", "content": system}, *messages],  # type: ignore[list-item]
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
        )

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage is not None else 0
        tokens_out = usage.completion_tokens if usage is not None else 0
        cost_usd = estimate_cost(resolved_model, tokens_in, tokens_out)

        self._usage.record_llm_usage(
            run_id=run_id,
            agent_id=agent_id,
            model=resolved_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

        return LLMResponse(
            content=content,
            model=resolved_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
