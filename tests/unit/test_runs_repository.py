"""Unit tests for runs and proposed_actions repository."""

from __future__ import annotations

from datetime import UTC, datetime

from hypeagent.db.connection import Database
from hypeagent.db.repositories.runs import RunsRepository
from hypeagent.models.action import ActionType, ProposedAction


def _proposed(*, run_id: str = "run1", agent_id: str = "alice") -> ProposedAction:
    return ProposedAction(
        run_id=run_id,
        agent_id=agent_id,
        account_id=agent_id,
        action_type=ActionType.REPLY,
        content_id="post1",
        content_body_preview="Post preview",
        parent_comment_id="c1",
        parent_comment_preview="Parent preview",
        draft_text="Draft reply text",
        targeting_strategy="recent",
        llm_model="openai/gpt-4o-mini",
        llm_tokens_in=100,
        llm_tokens_out=20,
        llm_cost_usd=0.01,
        created_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC),
    )


class TestRunsRepository:
    def test_run_lifecycle_and_proposed_actions(self, tmp_path) -> None:
        db_path = tmp_path / "runs.db"
        with Database(db_path) as db:
            repo = RunsRepository(db)
            repo.start_run(
                run_id="run1",
                config_name="test-config",
                mode="dry_run",
                agents_total=2,
                started_at="2026-07-22T12:00:00Z",
            )
            action_id = repo.save_proposed(_proposed())
            repo.mark_published(action_id, "platform-comment-1")
            repo.finish_run(
                "run1",
                actions_proposed=1,
                actions_published=1,
                llm_cost_usd=0.01,
                status="completed",
                finished_at="2026-07-22T12:05:00Z",
            )

            stored = repo.get_proposed_for_run("run1")
            assert len(stored) == 1
            assert stored[0].draft_text == "Draft reply text"
            assert stored[0].published is True
            assert stored[0].platform_comment_id == "platform-comment-1"

            row = db.conn.execute(
                "SELECT status, actions_proposed, actions_published FROM runs WHERE run_id = ?",
                ("run1",),
            ).fetchone()
            assert row is not None
            assert row["status"] == "completed"
            assert row["actions_proposed"] == 1
            assert row["actions_published"] == 1

    def test_saves_reaction_payload_fields(self, tmp_path) -> None:
        from hypeagent.models.action import ActionKind, ActionPayload, ActionTargetKind

        db_path = tmp_path / "react.db"
        with Database(db_path) as db:
            repo = RunsRepository(db)
            repo.start_run(
                run_id="run1",
                config_name="test",
                mode="dry_run",
                agents_total=1,
            )
            proposed = ProposedAction(
                run_id="run1",
                agent_id="alice",
                account_id="alice",
                action_type=ActionKind.REACT,
                content_id="post1",
                content_body_preview="Post",
                parent_comment_id=None,
                parent_comment_preview=None,
                draft_text="",
                targeting_strategy="recent",
                llm_model="",
                llm_tokens_in=0,
                llm_tokens_out=0,
                llm_cost_usd=0.0,
                reaction_type="agree",
                target_kind=ActionTargetKind.CONTENT,
                target_id="post1",
                payload_json=ActionPayload(reaction_type="agree").to_json(),
            )
            repo.save_proposed(proposed)
            stored = repo.get_proposed_for_run("run1")
            assert stored[0].action_type == "react"
            assert stored[0].target_kind == "content"
            assert stored[0].target_id == "post1"
            assert stored[0].payload_json is not None
            assert "agree" in stored[0].payload_json

    def test_preview_text_truncates(self) -> None:
        long_text = "x" * 250
        preview = RunsRepository.preview_text(long_text, max_len=200)
        assert len(preview) == 200
        assert preview.endswith("...")
