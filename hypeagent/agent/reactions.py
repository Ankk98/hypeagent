"""Reaction type selection strategies for REACT actions."""

from __future__ import annotations

import json
import logging
import random
import re
from collections.abc import Sequence

from hypeagent.config.schema import PersonaConfig, ReactionsEngagementConfig
from hypeagent.llm.client import LLMClient
from hypeagent.models.content import Thread

logger = logging.getLogger("hypeagent.agent.reactions")


def resolve_allowed_types(
    reaction_cfg: ReactionsEngagementConfig,
    connector_allowed: frozenset[str],
) -> list[str]:
    """Intersect config types (or all) with connector allowlist; preserve config order."""
    if reaction_cfg.types is None:
        return sorted(connector_allowed)
    return [t for t in reaction_cfg.types if t in connector_allowed]


def choose_reaction_type(
    *,
    allowed_types: Sequence[str],
    reaction_cfg: ReactionsEngagementConfig,
    persona: PersonaConfig,
    thread: Thread,
    llm_client: LLMClient | None = None,
    run_id: str = "",
    agent_id: str = "",
) -> str | None:
    """Pick a reaction type using the configured strategy. Returns None if none allowed."""
    types = list(allowed_types)
    if not types:
        return None

    strategy = reaction_cfg.strategy
    if strategy == "random":
        return random.choice(types)
    if strategy == "weighted":
        return _weighted_choice(types, reaction_cfg.weights)
    if strategy == "persona_affinity":
        return _persona_affinity_choice(types, persona)
    if strategy == "llm_choose":
        return _llm_choose(
            types,
            thread=thread,
            persona=persona,
            llm_client=llm_client,
            run_id=run_id,
            agent_id=agent_id,
            fallback_weights=reaction_cfg.weights,
        )
    return _weighted_choice(types, reaction_cfg.weights)


def _weighted_choice(types: list[str], weights: dict[str, float]) -> str:
    pair_weights = [max(0.0, float(weights.get(t, 1.0))) for t in types]
    if sum(pair_weights) <= 0:
        return random.choice(types)
    return random.choices(types, weights=pair_weights, k=1)[0]


def _persona_affinity_choice(types: list[str], persona: PersonaConfig) -> str:
    haystack = " ".join(
        part.lower()
        for part in (persona.brief, persona.extra_info or "")
        if part
    )
    preferred = [t for t in types if re.search(rf"\b{re.escape(t.lower())}\b", haystack)]
    if preferred:
        return random.choice(preferred)
    return random.choice(types)


def _llm_choose(
    types: list[str],
    *,
    thread: Thread,
    persona: PersonaConfig,
    llm_client: LLMClient | None,
    run_id: str,
    agent_id: str,
    fallback_weights: dict[str, float],
) -> str:
    if llm_client is None:
        logger.warning("event=llm_choose_fallback reason=no_llm_client")
        return _weighted_choice(types, fallback_weights)

    type_list = ", ".join(types)
    system = (
        "You pick one reaction type for a social post. "
        f"Reply with JSON only: {{\"reaction\": \"<one of: {type_list}>\"}}"
    )
    preview = thread.content.body.strip()
    if len(preview) > 500:
        preview = preview[:497].rstrip() + "..."
    user = (
        f"Persona brief: {persona.brief.strip()}\n"
        f"Post preview: {preview}\n"
        f"Allowed reactions: {type_list}"
    )
    try:
        response = llm_client.complete(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=32,
            run_id=run_id,
            agent_id=agent_id,
        )
        chosen = _parse_reaction_json(response.content, types)
        if chosen is not None:
            return chosen
        logger.warning(
            "event=llm_choose_fallback reason=invalid_response content=%r",
            response.content,
        )
    except Exception:
        logger.exception("event=llm_choose_fallback reason=llm_error")
    return _weighted_choice(types, fallback_weights)


def _parse_reaction_json(content: str, allowed: Sequence[str]) -> str | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^}]+\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    value = data.get("reaction")
    if not isinstance(value, str):
        return None
    if value in allowed:
        return value
    lowered = {t.lower(): t for t in allowed}
    return lowered.get(value.lower())
