"""Integration tests for the Reddit connector with recorded HTTP fixtures."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hypeagent.config.loader import load_config
from hypeagent.config.schema import HttpConfig, PlatformConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.run import RunContext, RunMode
from hypeagent.platforms.base import PlatformError
from hypeagent.platforms.http_client import HttpClient
from hypeagent.platforms.reddit import RedditConnector

FIXTURES = Path("tests/fixtures/reddit")
EXAMPLE_CONFIG = Path("examples/reddit/hypeagent.yaml")


def _load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _reddit_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/access_token":
            return httpx.Response(200, json=_load_fixture("oauth_token.json"))
        if path == "/r/test/new":
            return httpx.Response(200, json=_load_fixture("listing_new.json"))
        if path == "/comments/abc123":
            return httpx.Response(200, json=_load_fixture("thread.json"))
        if path == "/api/comment":
            return httpx.Response(200, json=_load_fixture("publish_comment.json"))
        return httpx.Response(404, text=f"unexpected path: {path}")

    return httpx.MockTransport(handler)


@pytest.fixture
def reddit_connector() -> RedditConnector:
    config = load_config(EXAMPLE_CONFIG)
    account = AccountSecret(
        user_id="t2_abc123",
        token="refresh_token_test",
        extra={"client_id": "client", "client_secret": "secret"},
    )
    http_client = HttpClient(
        config.http,
        config.platform.user_agent,
        client=httpx.Client(transport=_reddit_transport()),
    )
    connector = RedditConnector(
        config.platform,
        account,
        config.http,
        http_client=http_client,
    )
    yield connector
    connector.close()


@pytest.fixture
def run_context(reddit_connector: RedditConnector) -> RunContext:
    config = load_config(EXAMPLE_CONFIG)
    account = AccountSecret(
        user_id="t2_abc123",
        token="refresh_token_test",
        extra={"client_id": "client", "client_secret": "secret"},
    )
    return RunContext(
        run_id="testrun",
        mode=RunMode.DRY_RUN,
        config=config,
        secrets=Secrets(
            llm={"api_key": "sk-test"},
            accounts={"priya_blr": account},
        ),
        agent_id="priya_blr",
        persona=config.personas["priya_blr"],
        account=account,
        connector=reddit_connector,
        db=None,
        logger=logging.getLogger("test"),
        llm_client=None,
        budget_guard=None,
    )


def test_list_contents_filters_by_since(
    run_context: RunContext,
    reddit_connector: RedditConnector,
) -> None:
    since = datetime(2024, 7, 20, tzinfo=UTC)
    contents = reddit_connector.list_contents(run_context, since=since)

    assert len(contents) == 1
    assert contents[0].id == "abc123"
    assert contents[0].kind == "post"
    assert "evicted" in contents[0].body
    assert contents[0].comment_count == 3


def test_get_thread_returns_nested_comments(
    run_context: RunContext,
    reddit_connector: RedditConnector,
) -> None:
    thread = reddit_connector.get_thread(run_context, "abc123")

    assert thread.content.id == "abc123"
    assert len(thread.comments) == 2
    assert thread.comments[0].id == "cmt001"
    assert thread.comments[0].depth == 0
    assert thread.comments[0].parent_id is None
    assert thread.comments[1].id == "cmt002"
    assert thread.comments[1].depth == 1
    assert thread.comments[1].parent_id == "cmt001"


def test_publish_comment_reply(run_context: RunContext, reddit_connector: RedditConnector) -> None:
    comment = reddit_connector.publish_comment(
        run_context,
        "abc123",
        "Arre bhai disagree, X ki game strong hai",
        parent_comment_id="cmt001",
    )

    assert comment.id == "newcmt"
    assert comment.content_id == "abc123"
    assert "disagree" in comment.body


def test_can_reply_respects_depth(
    reddit_connector: RedditConnector,
    run_context: RunContext,
) -> None:
    thread = reddit_connector.get_thread(run_context, "abc123")
    top_level = thread.comments[0]
    nested = thread.comments[1]

    assert reddit_connector.can_reply(run_context, thread, top_level, reply_depth_max=2)
    assert not reddit_connector.can_reply(run_context, thread, nested, reply_depth_max=1)


def test_requires_subreddit() -> None:
    platform = PlatformConfig(
        connector="reddit",
        base_url="https://oauth.reddit.com",
        user_agent="hypeagent/1.0",
        subreddit=None,
    )
    account = AccountSecret(user_id="t2_x", token="token", extra={})
    with pytest.raises(PlatformError, match="subreddit"):
        RedditConnector(platform, account, HttpConfig())
