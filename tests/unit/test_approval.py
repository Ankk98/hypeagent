"""Unit tests for approval prompts."""

from __future__ import annotations

from hypeagent.agent.approval import ApprovalDecision, ApprovalPrompt, ApprovalResponse
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets
from hypeagent.models.action import ActionTargetKind, ActionType, ProposedAction
from hypeagent.models.run import RunContext, RunMode


def _proposed(*, action_type: ActionType = ActionType.REPLY) -> ProposedAction:
    return ProposedAction(
        run_id="run1",
        agent_id="rohan_del",
        account_id="rohan_del",
        action_type=action_type,
        content_id="post-1",
        content_body_preview="I think X will get evicted this week",
        parent_comment_id="c1" if action_type == ActionType.REPLY else None,
        parent_comment_preview="Same bro X is playing dirty"
        if action_type == ActionType.REPLY
        else None,
        draft_text="Arre bhai disagree 😂 X ki game strong hai",
        targeting_strategy="recent",
        llm_model="openai/gpt-4o-mini",
        llm_tokens_in=10,
        llm_tokens_out=5,
        llm_cost_usd=0.001,
    )


def _ctx() -> RunContext:
    config = HypeagentConfig.model_validate(
        {
            "version": 1,
            "name": "approval-test",
            "platform": {
                "connector": "reddit",
                "base_url": "https://oauth.reddit.com",
                "user_agent": "hypeagent/1.0",
            },
            "llm": {
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openai/gpt-4o-mini",
            },
            "budgets": {"llm_daily_usd": 2.0, "llm_total_usd": 50.0},
            "run": {
                "agents": ["rohan_del"],
                "per_agent": {"comments": 0, "replies": 1},
            },
            "targeting": {"strategy": "recent"},
            "personas": {
                "rohan_del": {
                    "account": "rohan_del",
                    "city": "Delhi",
                    "languages": ["hinglish", "en"],
                    "brief": "Casual Delhi persona.",
                }
            },
        }
    )
    secrets = Secrets(
        llm={"api_key": "key"},
        accounts={"rohan_del": AccountSecret(user_id="t2_x", token="tok")},
    )
    persona = config.personas["rohan_del"]
    return RunContext(
        run_id="run1",
        mode=RunMode.APPROVE,
        config=config,
        secrets=secrets,
        agent_id="rohan_del",
        persona=persona,
        account=secrets.accounts["rohan_del"],
        connector=None,
        db=None,
        logger=__import__("logging").getLogger("test"),
        llm_client=None,
        budget_guard=None,
    )


class TestApprovalPrompt:
    def test_renders_reply_preview(self) -> None:
        lines: list[str] = []

        def capture(text: str) -> None:
            lines.append(text)

        prompt = ApprovalPrompt(output_fn=capture, input_fn=lambda _: "y")
        response = prompt.prompt(_ctx(), _proposed())

        assert response == ApprovalResponse(
            ApprovalDecision.PUBLISH,
            "Arre bhai disagree 😂 X ki game strong hai",
        )
        rendered = "\n".join(lines)
        assert "Agent: rohan_del (Delhi, hinglish, en)" in rendered
        assert "Action: REPLY" in rendered
        assert "I think X will get evicted this week" in rendered
        assert "Same bro X is playing dirty" in rendered
        assert "Arre bhai disagree" in rendered

    def test_skip_on_n(self) -> None:
        prompt = ApprovalPrompt(input_fn=lambda _: "n")
        response = prompt.prompt(_ctx(), _proposed())
        assert response.decision == ApprovalDecision.SKIP

    def test_quit_on_q(self) -> None:
        prompt = ApprovalPrompt(input_fn=lambda _: "q")
        response = prompt.prompt(_ctx(), _proposed())
        assert response.decision == ApprovalDecision.QUIT

    def test_edit_then_publish(self) -> None:
        inputs = iter(["e", "", "y"])

        def read(_: str) -> str:
            return next(inputs)

        prompt = ApprovalPrompt(input_fn=read)
        response = prompt.prompt(_ctx(), _proposed())

        assert response.decision == ApprovalDecision.PUBLISH
        assert response.draft_text == "Arre bhai disagree 😂 X ki game strong hai"

    def test_edit_with_new_text(self) -> None:
        inputs = iter(["e", "Edited draft text", "y"])

        def read(_: str) -> str:
            return next(inputs)

        prompt = ApprovalPrompt(input_fn=read)
        response = prompt.prompt(_ctx(), _proposed())

        assert response.decision == ApprovalDecision.PUBLISH
        assert response.draft_text == "Edited draft text"

    def test_comment_action_omits_parent_block(self) -> None:
        lines: list[str] = []

        prompt = ApprovalPrompt(
            output_fn=lines.append,
            input_fn=lambda _: "n",
        )
        prompt.prompt(_ctx(), _proposed(action_type=ActionType.COMMENT))
        rendered = "\n".join(lines)
        assert "Replying to:" not in rendered

    def test_react_renders_reaction_not_draft(self) -> None:
        lines: list[str] = []
        proposed = ProposedAction(
            run_id="run1",
            agent_id="rohan_del",
            account_id="rohan_del",
            action_type=ActionType.REACT,
            content_id="post-1",
            content_body_preview="I think X will get evicted this week",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="",
            targeting_strategy="recent",
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            reaction_type="insightful",
            target_kind=ActionTargetKind.CONTENT,
            target_id="post-1",
        )
        prompt = ApprovalPrompt(
            output_fn=lines.append,
            input_fn=lambda _: "y",
        )
        response = prompt.prompt(_ctx(), proposed)
        rendered = "\n".join(lines)
        assert "Action: REACT" in rendered
        assert "Reaction: insightful" in rendered
        assert "Draft:" not in rendered
        assert response.reaction_type == "insightful"

    def test_react_edit_updates_type(self) -> None:
        inputs = iter(["e", "like", "y"])

        def read(_: str) -> str:
            return next(inputs)

        proposed = ProposedAction(
            run_id="run1",
            agent_id="rohan_del",
            account_id="rohan_del",
            action_type=ActionType.REACT,
            content_id="post-1",
            content_body_preview="preview",
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
            target_id="post-1",
        )
        # No connector → edit accepts any type when allowlist empty
        response = ApprovalPrompt(input_fn=read).prompt(_ctx(), proposed)
        assert response.decision == ApprovalDecision.PUBLISH
        assert response.reaction_type == "like"

    def test_vote_renders_value_not_draft(self) -> None:
        lines: list[str] = []
        proposed = ProposedAction(
            run_id="run1",
            agent_id="rohan_del",
            account_id="rohan_del",
            action_type=ActionType.VOTE,
            content_id="post-1",
            content_body_preview="I think X will get evicted this week",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="",
            targeting_strategy="recent",
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            vote_value=1,
            target_kind=ActionTargetKind.CONTENT,
            target_id="post-1",
        )
        response = ApprovalPrompt(
            output_fn=lines.append,
            input_fn=lambda _: "y",
        ).prompt(_ctx(), proposed)
        rendered = "\n".join(lines)
        assert "Action: VOTE" in rendered
        assert "Vote: 1" in rendered
        assert "Draft:" not in rendered
        assert response.vote_value == 1

    def test_vote_edit_updates_value(self) -> None:
        inputs = iter(["e", "-1", "y"])

        def read(_: str) -> str:
            return next(inputs)

        proposed = ProposedAction(
            run_id="run1",
            agent_id="rohan_del",
            account_id="rohan_del",
            action_type=ActionType.VOTE,
            content_id="post-1",
            content_body_preview="preview",
            parent_comment_id=None,
            parent_comment_preview=None,
            draft_text="",
            targeting_strategy="recent",
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            vote_value=1,
            target_kind=ActionTargetKind.CONTENT,
            target_id="post-1",
        )
        response = ApprovalPrompt(input_fn=read).prompt(_ctx(), proposed)
        assert response.decision == ApprovalDecision.PUBLISH
        assert response.vote_value == -1

    def test_invalid_choice_reprompts(self) -> None:
        inputs = iter(["maybe", "y"])

        def read(_: str) -> str:
            return next(inputs)

        prompt = ApprovalPrompt(input_fn=read)
        response = prompt.prompt(_ctx(), _proposed())
        assert response.decision == ApprovalDecision.PUBLISH
