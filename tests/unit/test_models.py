"""Unit tests for canonical models."""

from __future__ import annotations

from datetime import UTC, datetime

from hypeagent.models.action import ActionKind, ActionType, ProposedAction, ToolCallRecord
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunMode


def test_content_is_frozen() -> None:
    content = Content(
        id="c1",
        kind="post",
        author_id="a1",
        author_display="alice",
        body="hello",
        created_at=datetime.now(UTC),
        comment_count=0,
        metadata={},
    )
    assert content.kind == "post"


def test_thread_holds_content_and_comments() -> None:
    now = datetime.now(UTC)
    content = Content(
        id="c1",
        kind="post",
        author_id="a1",
        author_display="alice",
        body="post body",
        created_at=now,
        comment_count=1,
        metadata={},
    )
    comment = Comment(
        id="cm1",
        content_id="c1",
        parent_id=None,
        author_id="a2",
        author_display="bob",
        body="reply",
        created_at=now,
        depth=0,
        metadata={},
    )
    thread = Thread(content=content, comments=[comment])
    assert thread.comments[0].depth == 0


def test_proposed_action_fields() -> None:
    action = ProposedAction(
        run_id="run1",
        agent_id="alice",
        account_id="alice",
        action_type=ActionType.REPLY,
        content_id="c1",
        content_body_preview="preview",
        parent_comment_id="cm1",
        parent_comment_preview="parent",
        draft_text="draft",
        targeting_strategy="recent",
        llm_model="openai/gpt-4o-mini",
        llm_tokens_in=100,
        llm_tokens_out=20,
        llm_cost_usd=0.01,
        tool_calls=[
            ToolCallRecord(
                tool_name="show_context",
                arguments={"show_id": "1"},
                result_preview="Show 1",
                duration_ms=12,
            ),
        ],
    )
    assert action.action_type == ActionKind.REPLY
    assert ActionType is ActionKind


def test_run_mode_values() -> None:
    assert RunMode.DRY_RUN.value == "dry_run"
