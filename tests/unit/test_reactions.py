"""Unit tests for reaction type strategies."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from hypeagent.agent.reactions import (
    choose_reaction_type,
    resolve_allowed_types,
)
from hypeagent.config.schema import PersonaConfig, ReactionsEngagementConfig
from hypeagent.llm.client import LLMResponse
from hypeagent.models.content import Content, Thread


def _thread() -> Thread:
    return Thread(
        content=Content(
            id="post1",
            kind="post",
            author_id="author",
            author_display="author",
            body="Great episode this week",
            created_at=datetime.now(UTC),
            comment_count=0,
            metadata={},
        ),
        comments=[],
    )


def _persona(**kwargs: object) -> PersonaConfig:
    data: dict[str, object] = {"account": "alice", "brief": "Casual fan."}
    data.update(kwargs)
    return PersonaConfig.model_validate(data)


class TestResolveAllowedTypes:
    def test_intersects_config_with_connector(self) -> None:
        cfg = ReactionsEngagementConfig(types=["agree", "nope", "like"])
        assert resolve_allowed_types(cfg, frozenset({"agree", "like", "funny"})) == [
            "agree",
            "like",
        ]

    def test_all_connector_types_when_unset(self) -> None:
        cfg = ReactionsEngagementConfig()
        assert resolve_allowed_types(cfg, frozenset({"b", "a"})) == ["a", "b"]


class TestChooseReactionType:
    def test_random_picks_from_allowed(self) -> None:
        cfg = ReactionsEngagementConfig(strategy="random")
        chosen = choose_reaction_type(
            allowed_types=["agree", "like"],
            reaction_cfg=cfg,
            persona=_persona(),
            thread=_thread(),
        )
        assert chosen in {"agree", "like"}

    def test_weighted_prefers_heavy_weight(self) -> None:
        cfg = ReactionsEngagementConfig(
            strategy="weighted",
            weights={"agree": 1_000_000.0, "like": 0.000001},
        )
        counts = {"agree": 0, "like": 0}
        for _ in range(40):
            chosen = choose_reaction_type(
                allowed_types=["agree", "like"],
                reaction_cfg=cfg,
                persona=_persona(),
                thread=_thread(),
            )
            assert chosen is not None
            counts[chosen] += 1
        assert counts["agree"] > counts["like"]

    def test_persona_affinity_matches_brief(self) -> None:
        cfg = ReactionsEngagementConfig(strategy="persona_affinity")
        chosen = choose_reaction_type(
            allowed_types=["agree", "insightful", "like"],
            reaction_cfg=cfg,
            persona=_persona(brief="I leave insightful takes on every post."),
            thread=_thread(),
        )
        assert chosen == "insightful"

    def test_llm_choose_parses_json(self) -> None:
        cfg = ReactionsEngagementConfig(strategy="llm_choose")
        llm = MagicMock()
        llm.complete.return_value = LLMResponse(
            content='{"reaction": "like"}',
            model="m",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
        )
        chosen = choose_reaction_type(
            allowed_types=["agree", "like"],
            reaction_cfg=cfg,
            persona=_persona(),
            thread=_thread(),
            llm_client=llm,
            run_id="r1",
            agent_id="alice",
        )
        assert chosen == "like"
        llm.complete.assert_called_once()

    def test_llm_choose_falls_back_on_invalid(self) -> None:
        cfg = ReactionsEngagementConfig(
            strategy="llm_choose",
            weights={"agree": 1.0, "like": 0.0},
        )
        llm = MagicMock()
        llm.complete.return_value = LLMResponse(
            content="not json",
            model="m",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
        )
        chosen = choose_reaction_type(
            allowed_types=["agree", "like"],
            reaction_cfg=cfg,
            persona=_persona(),
            thread=_thread(),
            llm_client=llm,
            run_id="r1",
            agent_id="alice",
        )
        assert chosen == "agree"

    def test_empty_allowed_returns_none(self) -> None:
        cfg = ReactionsEngagementConfig(strategy="random")
        assert (
            choose_reaction_type(
                allowed_types=[],
                reaction_cfg=cfg,
                persona=_persona(),
                thread=_thread(),
            )
            is None
        )
