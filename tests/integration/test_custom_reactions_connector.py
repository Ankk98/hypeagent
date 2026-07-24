"""Integration tests for the documented custom typed-reaction connector."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from hypeagent.agent.planner import Planner
from hypeagent.config.loader import load_config
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.action import (
    ActionKind,
    ActionPayload,
    ActionSpec,
    ActionTarget,
    ActionTargetKind,
)
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import PlatformConnector, PlatformError
from hypeagent.platforms.http_client import HttpClient
from hypeagent.platforms.registry import load_connector

EXAMPLE = Path("examples/custom-reactions")
CONFIG_PATH = EXAMPLE / "hypeagent.yaml"
CONNECTOR_PATH = EXAMPLE / "platforms/community_app.py"

POST: dict[str, Any] = {
    "id": "post-1",
    "author": {"id": "author-1", "displayName": "Riya"},
    "body": "What did everyone think?",
    "createdAt": "2026-07-24T18:30:00Z",
    "commentCount": 1,
    "myReaction": None,
    "reactionCounts": {"agree": 3},
}
COMMENT: dict[str, Any] = {
    "id": "comment-1",
    "postId": "post-1",
    "parentId": None,
    "author": {"id": "author-2", "displayName": "Arjun"},
    "body": "The ending worked for me.",
    "createdAt": "2026-07-24T18:35:00Z",
    "depth": 0,
    "myReaction": "like",
    "reactionCounts": {"like": 2},
}


@pytest.fixture
def api_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def connector(api_requests: list[httpx.Request]) -> PlatformConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        api_requests.append(request)
        if request.method == "GET" and request.url.path == "/api/posts":
            return httpx.Response(200, json={"posts": [POST]})
        if request.method == "GET" and request.url.path == "/api/posts/post-1":
            return httpx.Response(200, json={"post": POST, "comments": [COMMENT]})
        if request.method == "GET" and request.url.path == "/api/messages/uncached":
            return httpx.Response(
                200,
                json={"message": {**COMMENT, "id": "uncached", "myReaction": "agree"}},
            )
        if request.method == "POST" and request.url.path == "/api/reactions":
            return httpx.Response(
                200,
                json={"reaction": {"id": "reaction-1", "type": "insightful"}},
            )
        if request.method == "POST" and request.url.path == "/api/comments":
            submitted = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "comment": {
                        **COMMENT,
                        "id": "new-comment",
                        "body": submitted["body"],
                        "parentId": submitted["parentId"],
                    }
                },
            )
        return httpx.Response(404, text=f"unexpected request: {request.method} {request.url}")

    config = load_config(CONFIG_PATH)
    account = AccountSecret(user_id="user-1", token="community-token")
    http_client = HttpClient(
        config.http,
        config.platform.user_agent,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    connector_cls = load_connector(str(CONNECTOR_PATH))
    instance = connector_cls(
        config.platform,
        account,
        config.http,
        http_client=http_client,
    )
    yield instance
    close = getattr(instance, "close", None)
    if close is not None:
        close()


@pytest.fixture
def run_context(connector: PlatformConnector) -> RunContext:
    config = load_config(CONFIG_PATH)
    account = AccountSecret(user_id="user-1", token="community-token")
    return RunContext(
        run_id="custom-reactions-test",
        mode=RunMode.AUTO,
        config=config,
        secrets=Secrets(
            llm={"api_key": "sk-test"},
            accounts={"reaction_fan": account},
        ),
        agent_id="reaction_fan",
        persona=config.personas["reaction_fan"],
        account=account,
        connector=connector,
        db=None,
        logger=logging.getLogger("test"),
        llm_client=None,
        budget_guard=None,
    )


def test_capabilities_advertise_typed_reactions(connector: PlatformConnector) -> None:
    reactions = connector.capabilities().reactions
    assert reactions is not None
    assert reactions.mode == "toggle"
    assert reactions.target_kinds == {
        ActionTargetKind.CONTENT,
        ActionTargetKind.COMMENT,
    }
    assert {"agree", "insightful", "like"} <= reactions.allowed_types


def test_list_thread_and_current_engagement_use_embedded_state(
    connector: PlatformConnector,
    run_context: RunContext,
    api_requests: list[httpx.Request],
) -> None:
    contents = connector.list_contents(
        run_context,
        since=datetime(2026, 7, 24, tzinfo=UTC),
    )
    thread = connector.get_thread(run_context, contents[0].id)
    before = len(api_requests)

    post_state = connector.current_engagement(
        run_context,
        ActionTarget(ActionTargetKind.CONTENT, "post-1"),
    )
    comment_state = connector.current_engagement(
        run_context,
        ActionTarget(ActionTargetKind.COMMENT, "comment-1"),
    )

    assert post_state["myReaction"] is None
    assert comment_state["myReaction"] == "like"
    assert thread.comments[0].metadata["reactionCounts"] == {"like": 2}
    assert len(api_requests) == before


def test_current_engagement_fetches_uncached_target(
    connector: PlatformConnector,
    run_context: RunContext,
) -> None:
    state = connector.current_engagement(
        run_context,
        ActionTarget(ActionTargetKind.COMMENT, "uncached"),
    )
    assert state["myReaction"] == "agree"


def test_execute_reaction_builds_typed_request(
    connector: PlatformConnector,
    run_context: RunContext,
    api_requests: list[httpx.Request],
) -> None:
    result = connector.execute(
        run_context,
        ActionSpec(
            kind=ActionKind.REACT,
            content_id="post-1",
            target=ActionTarget(ActionTargetKind.CONTENT, "post-1"),
            payload=ActionPayload(reaction_type="insightful"),
        ),
    )

    request = api_requests[-1]
    assert request.url.path == "/api/reactions"
    assert request.headers["Authorization"] == "Bearer community-token"
    assert json.loads(request.content) == {
        "entityType": "post",
        "entityId": "post-1",
        "type": "insightful",
    }
    assert result.platform_object_id == "reaction-1"
    assert connector.current_engagement(
        run_context,
        ActionTarget(ActionTargetKind.CONTENT, "post-1"),
    )["myReaction"] == "insightful"


def test_execute_comment_uses_default_action_routing(
    connector: PlatformConnector,
    run_context: RunContext,
    api_requests: list[httpx.Request],
) -> None:
    result = connector.execute(
        run_context,
        ActionSpec(
            kind=ActionKind.COMMENT,
            content_id="post-1",
            target=ActionTarget(ActionTargetKind.CONTENT, "post-1"),
            payload=ActionPayload(text="A new take"),
        ),
    )

    assert result.platform_object_id == "new-comment"
    assert json.loads(api_requests[-1].content) == {
        "postId": "post-1",
        "parentId": None,
        "body": "A new take",
    }


def test_execute_reaction_rejects_unknown_type(
    connector: PlatformConnector,
    run_context: RunContext,
) -> None:
    spec = ActionSpec(
        kind=ActionKind.REACT,
        content_id="post-1",
        target=ActionTarget(ActionTargetKind.CONTENT, "post-1"),
        payload=ActionPayload(reaction_type="invented"),
    )
    with pytest.raises(PlatformError, match="not in connector .* allowlist"):
        connector.execute(run_context, spec)


def test_planner_skips_all_already_reacted_toggle_targets(
    connector: PlatformConnector,
    run_context: RunContext,
) -> None:
    thread = connector.get_thread(run_context, "post-1")
    connector.execute(
        run_context,
        ActionSpec(
            kind=ActionKind.REACT,
            content_id="post-1",
            target=ActionTarget(ActionTargetKind.CONTENT, "post-1"),
            payload=ActionPayload(reaction_type="insightful"),
        ),
    )

    decision = Planner().decide(run_context.config.run.per_agent, thread, run_context)

    assert decision is None
