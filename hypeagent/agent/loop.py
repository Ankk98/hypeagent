"""Sequential multi-agent run orchestration."""

from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from hypeagent.agent.approval import ApprovalDecision, ApprovalPrompt, ApprovalQuitError
from hypeagent.agent.drafter import Drafter
from hypeagent.agent.planner import Planner
from hypeagent.config.schema import HypeagentConfig, PerAgentConfig
from hypeagent.config.secrets_schema import Secrets
from hypeagent.db.connection import Database
from hypeagent.db.repositories.agent_memory import AgentMemoryRepository
from hypeagent.db.repositories.runs import RunsRepository
from hypeagent.db.repositories.usage import UsageRepository
from hypeagent.knowledge.static import StaticKnowledgeLoader
from hypeagent.knowledge.tools import ToolExecutor, ToolRegistry
from hypeagent.llm.budget import BudgetExceededError, BudgetGuard
from hypeagent.llm.client import LLMClient
from hypeagent.models.action import (
    ActionKind,
    ActionPayload,
    ActionSpec,
    ActionTargetKind,
    ProposedAction,
    PublishedAction,
)
from hypeagent.models.content import Comment, Content, Thread
from hypeagent.models.run import RunContext, RunMode, RunResult
from hypeagent.platforms.base import PlatformConnector, PlatformError
from hypeagent.platforms.registry import load_connector


class AgentRunner:
    """Run configured personas sequentially against platform content (§10)."""

    def __init__(
        self,
        config: HypeagentConfig,
        secrets: Secrets,
        db: Database,
        *,
        base_dir: Path | str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._db = db
        self._base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self._logger = logger or logging.getLogger("hypeagent.agent")

    def run_all(self, mode: RunMode) -> RunResult:
        """Execute all configured agents in order and persist run results."""
        run_id = uuid4().hex
        runs_repo = RunsRepository(self._db)
        usage_repo = UsageRepository(self._db)
        budget_guard = BudgetGuard(self._config.budgets, usage_repo)
        llm_client = LLMClient(
            self._config.llm,
            self._secrets.llm.api_key,
            budget_guard,
            usage_repo,
        )
        tool_registry = ToolRegistry(self._config.knowledge.tools)
        tool_executor = ToolExecutor(tool_registry, llm_client)
        static_loader = StaticKnowledgeLoader(self._base_dir)
        drafter = Drafter(static_loader, tool_executor)
        planner = Planner()
        approval = ApprovalPrompt()
        memory_repo = AgentMemoryRepository(self._db)

        agent_ids = list(self._config.run.agents)
        runs_repo.start_run(
            run_id=run_id,
            config_name=self._config.name,
            mode=mode.value,
            agents_total=len(agent_ids),
        )

        proposed_actions: list[ProposedAction] = []
        published_actions: list[PublishedAction] = []
        errors: list[str] = []
        status = "completed"

        try:
            for agent_id in agent_ids:
                if len(proposed_actions) >= self._config.budgets.max_actions_per_run:
                    self._logger.warning(
                        "run_id=%s event=max_actions_reached cap=%d",
                        run_id,
                        self._config.budgets.max_actions_per_run,
                    )
                    break

                try:
                    agent_proposed, agent_published = self._run_one_agent(
                        run_id=run_id,
                        agent_id=agent_id,
                        mode=mode,
                        llm_client=llm_client,
                        budget_guard=budget_guard,
                        runs_repo=runs_repo,
                        memory_repo=memory_repo,
                        planner=planner,
                        drafter=drafter,
                        approval=approval,
                        actions_so_far=len(proposed_actions),
                    )
                except ApprovalQuitError:
                    status = "failed"
                    raise
                except BudgetExceededError as exc:
                    status = "budget_exceeded"
                    errors.append(str(exc))
                    break
                except PlatformError as exc:
                    status = "failed"
                    errors.append(f"{agent_id}: {exc}")
                    self._logger.error(
                        "run_id=%s agent=%s event=platform_error error=%s",
                        run_id,
                        agent_id,
                        exc,
                    )
                    continue
                except Exception as exc:
                    status = "failed"
                    errors.append(f"{agent_id}: {exc}")
                    self._logger.exception(
                        "run_id=%s agent=%s event=agent_error",
                        run_id,
                        agent_id,
                    )
                    continue

                proposed_actions.extend(agent_proposed)
                published_actions.extend(agent_published)

            if errors and status == "completed":
                status = "failed"
        finally:
            llm_cost = runs_repo.get_run_llm_cost(run_id)
            runs_repo.finish_run(
                run_id,
                actions_proposed=len(proposed_actions),
                actions_published=len(published_actions),
                llm_cost_usd=llm_cost,
                status=status,
            )

        return RunResult(
            run_id=run_id,
            mode=mode,
            agent_ids=agent_ids,
            proposed_actions=proposed_actions,
            published_actions=published_actions,
            errors=errors,
            status=status,
        )

    def _run_one_agent(
        self,
        *,
        run_id: str,
        agent_id: str,
        mode: RunMode,
        llm_client: LLMClient,
        budget_guard: BudgetGuard,
        runs_repo: RunsRepository,
        memory_repo: AgentMemoryRepository,
        planner: Planner,
        drafter: Drafter,
        approval: ApprovalPrompt,
        actions_so_far: int,
    ) -> tuple[list[ProposedAction], list[PublishedAction]]:
        persona = self._config.personas[agent_id]
        account = self._secrets.accounts[persona.account]
        connector_cls = load_connector(self._config.platform.connector)
        connector: PlatformConnector = connector_cls(
            self._config.platform,
            account,
            self._config.http,
        )

        ctx = RunContext(
            run_id=run_id,
            mode=mode,
            config=self._config,
            secrets=self._secrets,
            agent_id=agent_id,
            persona=persona,
            account=account,
            connector=connector,
            db=self._db,
            logger=self._logger,
            llm_client=llm_client,
            budget_guard=budget_guard,
        )

        since_hours = int(self._config.targeting.params.get("since_hours", 24))
        since = datetime.now(UTC) - timedelta(hours=since_hours)
        contents = connector.list_contents(ctx, since=since)
        candidates = connector.filter_candidates(ctx, contents, self._config.targeting)
        if not candidates:
            self._logger.warning(
                "run_id=%s agent=%s event=no_candidates strategy=%s",
                run_id,
                agent_id,
                self._config.targeting.strategy,
            )
            return [], []

        content = random.choice(candidates)
        self._logger.info(
            "run_id=%s agent=%s event=content_picked content_id=%s comment_count=%d",
            run_id,
            agent_id,
            content.id,
            content.comment_count,
        )

        thread = connector.get_thread(ctx, content.id)
        remaining = self._config.run.per_agent.model_copy(deep=True)
        proposed_actions: list[ProposedAction] = []
        published_actions: list[PublishedAction] = []
        max_actions = self._config.budgets.max_actions_per_run

        while actions_so_far + len(proposed_actions) < max_actions:
            decision = planner.decide(remaining, thread, ctx)
            if decision is None:
                if not proposed_actions:
                    self._logger.warning(
                        "run_id=%s agent=%s event=no_action_quota content_id=%s",
                        run_id,
                        agent_id,
                        content.id,
                    )
                break

            spec = decision.spec
            proposed = self._propose_from_spec(
                run_id=run_id,
                agent_id=agent_id,
                persona_account=persona.account,
                content=content,
                thread=thread,
                spec=spec,
                ctx=ctx,
                drafter=drafter,
            )
            if proposed is None:
                # Empty draft or failed propose — consume quota so we do not loop forever.
                remaining = _consume_quota(remaining, spec.kind)
                continue

            action_id = runs_repo.save_proposed(proposed)
            published = self._handle_publish_mode(
                ctx=ctx,
                connector=connector,
                proposed=proposed,
                action_id=action_id,
                mode=mode,
                approval=approval,
                memory_repo=memory_repo,
                runs_repo=runs_repo,
            )
            proposed_actions.append(proposed)
            if published is not None:
                published_actions.append(published)
            remaining = _consume_quota(remaining, spec.kind)
            budget_guard.check()

        return proposed_actions, published_actions

    def _propose_from_spec(
        self,
        *,
        run_id: str,
        agent_id: str,
        persona_account: str,
        content: Content,
        thread: Thread,
        spec: ActionSpec,
        ctx: RunContext,
        drafter: Drafter,
    ) -> ProposedAction | None:
        if spec.kind == ActionKind.REACT:
            return self._build_react_proposed(
                run_id=run_id,
                agent_id=agent_id,
                persona_account=persona_account,
                content=content,
                spec=spec,
            )
        if spec.kind == ActionKind.VOTE:
            return self._build_vote_proposed(
                run_id=run_id,
                agent_id=agent_id,
                persona_account=persona_account,
                content=content,
                spec=spec,
            )

        parent = _resolve_parent(thread, spec)
        draft_result = drafter.draft(ctx, thread, spec.kind, parent)
        draft_text = draft_result.final_text
        if not draft_text:
            self._logger.warning(
                "run_id=%s agent=%s event=empty_draft content_id=%s kind=%s",
                run_id,
                agent_id,
                content.id,
                spec.kind.value,
            )
            return None

        filled = replace(spec, payload=ActionPayload(text=draft_text))
        parent_preview = (
            RunsRepository.preview_text(parent.body) if parent is not None else None
        )
        return ProposedAction(
            run_id=run_id,
            agent_id=agent_id,
            account_id=persona_account,
            action_type=filled.kind,
            content_id=content.id,
            content_body_preview=RunsRepository.preview_text(content.body),
            parent_comment_id=parent.id if parent else None,
            parent_comment_preview=parent_preview,
            draft_text=draft_text,
            targeting_strategy=self._config.targeting.strategy,
            llm_model=draft_result.model,
            llm_tokens_in=draft_result.tokens_in,
            llm_tokens_out=draft_result.tokens_out,
            llm_cost_usd=draft_result.cost_usd,
            tool_calls=list(draft_result.tool_calls),
            target_kind=filled.target.kind,
            target_id=filled.target.id,
            payload_json=filled.payload.to_json(),
        )

    def _build_react_proposed(
        self,
        *,
        run_id: str,
        agent_id: str,
        persona_account: str,
        content: Content,
        spec: ActionSpec,
    ) -> ProposedAction:
        reaction_type = spec.payload.reaction_type or ""
        parent_comment_id = (
            spec.target.id if spec.target.kind == ActionTargetKind.COMMENT else None
        )
        parent_preview = (
            spec.target.preview if spec.target.kind == ActionTargetKind.COMMENT else None
        )
        return ProposedAction(
            run_id=run_id,
            agent_id=agent_id,
            account_id=persona_account,
            action_type=ActionKind.REACT,
            content_id=content.id,
            content_body_preview=RunsRepository.preview_text(content.body),
            parent_comment_id=parent_comment_id,
            parent_comment_preview=parent_preview,
            draft_text="",
            targeting_strategy=self._config.targeting.strategy,
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            reaction_type=reaction_type,
            target_kind=spec.target.kind,
            target_id=spec.target.id,
            payload_json=spec.payload.to_json(),
        )

    def _build_vote_proposed(
        self,
        *,
        run_id: str,
        agent_id: str,
        persona_account: str,
        content: Content,
        spec: ActionSpec,
    ) -> ProposedAction:
        vote_value = spec.payload.vote_value
        parent_comment_id = (
            spec.target.id if spec.target.kind == ActionTargetKind.COMMENT else None
        )
        parent_preview = (
            spec.target.preview if spec.target.kind == ActionTargetKind.COMMENT else None
        )
        return ProposedAction(
            run_id=run_id,
            agent_id=agent_id,
            account_id=persona_account,
            action_type=ActionKind.VOTE,
            content_id=content.id,
            content_body_preview=RunsRepository.preview_text(content.body),
            parent_comment_id=parent_comment_id,
            parent_comment_preview=parent_preview,
            draft_text="",
            targeting_strategy=self._config.targeting.strategy,
            llm_model="",
            llm_tokens_in=0,
            llm_tokens_out=0,
            llm_cost_usd=0.0,
            vote_value=vote_value,
            target_kind=spec.target.kind,
            target_id=spec.target.id,
            payload_json=spec.payload.to_json(),
        )

    def _handle_publish_mode(
        self,
        *,
        ctx: RunContext,
        connector: PlatformConnector,
        proposed: ProposedAction,
        action_id: int,
        mode: RunMode,
        approval: ApprovalPrompt,
        memory_repo: AgentMemoryRepository,
        runs_repo: RunsRepository,
    ) -> PublishedAction | None:
        if mode == RunMode.DRY_RUN:
            if proposed.action_type == ActionKind.REACT:
                self._logger.info(
                    "run_id=%s agent=%s event=dry_run action=%s content_id=%s "
                    "reaction=%s target_kind=%s target_id=%s",
                    proposed.run_id,
                    proposed.agent_id,
                    proposed.action_type.value,
                    proposed.content_id,
                    proposed.reaction_type,
                    proposed.target_kind.value if proposed.target_kind else None,
                    proposed.target_id,
                )
            elif proposed.action_type == ActionKind.VOTE:
                self._logger.info(
                    "run_id=%s agent=%s event=dry_run action=%s content_id=%s "
                    "vote=%s target_kind=%s target_id=%s",
                    proposed.run_id,
                    proposed.agent_id,
                    proposed.action_type.value,
                    proposed.content_id,
                    proposed.vote_value,
                    proposed.target_kind.value if proposed.target_kind else None,
                    proposed.target_id,
                )
            else:
                self._logger.info(
                    "run_id=%s agent=%s event=dry_run action=%s content_id=%s draft=%r",
                    proposed.run_id,
                    proposed.agent_id,
                    proposed.action_type.value,
                    proposed.content_id,
                    proposed.draft_text,
                )
            return None

        if mode == RunMode.APPROVE:
            response = approval.prompt(ctx, proposed)
            if response.decision == ApprovalDecision.QUIT:
                raise ApprovalQuitError("User quit during approval")
            if response.decision == ApprovalDecision.SKIP:
                self._logger.info(
                    "run_id=%s agent=%s event=approval_skipped content_id=%s",
                    proposed.run_id,
                    proposed.agent_id,
                    proposed.content_id,
                )
                return None
            if proposed.action_type == ActionKind.REACT:
                if response.reaction_type and response.reaction_type != proposed.reaction_type:
                    proposed.reaction_type = response.reaction_type
                    proposed.payload_json = ActionPayload(
                        reaction_type=response.reaction_type
                    ).to_json()
                    runs_repo.update_reaction(action_id, proposed.payload_json)
            elif proposed.action_type == ActionKind.VOTE:
                if (
                    response.vote_value is not None
                    and response.vote_value != proposed.vote_value
                ):
                    proposed.vote_value = response.vote_value
                    proposed.payload_json = ActionPayload(
                        vote_value=response.vote_value
                    ).to_json()
                    runs_repo.update_reaction(action_id, proposed.payload_json)
            elif response.draft_text != proposed.draft_text:
                proposed.draft_text = response.draft_text
                proposed.payload_json = ActionPayload(text=response.draft_text).to_json()
                runs_repo.update_draft_text(action_id, response.draft_text)
            return self._publish(
                ctx=ctx,
                connector=connector,
                proposed=proposed,
                action_id=action_id,
                approved_by="human",
                memory_repo=memory_repo,
                runs_repo=runs_repo,
            )

        return self._publish(
            ctx=ctx,
            connector=connector,
            proposed=proposed,
            action_id=action_id,
            approved_by="auto",
            memory_repo=memory_repo,
            runs_repo=runs_repo,
        )

    def _publish(
        self,
        *,
        ctx: RunContext,
        connector: PlatformConnector,
        proposed: ProposedAction,
        action_id: int,
        approved_by: str,
        memory_repo: AgentMemoryRepository,
        runs_repo: RunsRepository,
    ) -> PublishedAction:
        result = connector.execute(ctx, proposed.to_action_spec())
        platform_id = result.platform_object_id or ""
        runs_repo.mark_published(action_id, platform_id)
        memory_repo.record(
            agent_id=proposed.agent_id,
            content_id=proposed.content_id,
            action_type=proposed.action_type.value,
            text_preview=proposed.display_preview(),
        )
        published = PublishedAction(
            proposed=proposed,
            platform_comment_id=platform_id,
            published_at=datetime.now(UTC),
            approved_by=approved_by,  # type: ignore[arg-type]
        )
        self._logger.info(
            "run_id=%s agent=%s event=published action=%s content_id=%s comment_id=%s",
            proposed.run_id,
            proposed.agent_id,
            proposed.action_type.value,
            proposed.content_id,
            platform_id,
        )
        return published


def _consume_quota(remaining: PerAgentConfig, kind: ActionKind) -> PerAgentConfig:
    """Decrement the quota matching the planned action kind."""
    if kind == ActionKind.COMMENT:
        return remaining.model_copy(update={"comments": max(0, remaining.comments - 1)})
    if kind == ActionKind.REPLY:
        return remaining.model_copy(update={"replies": max(0, remaining.replies - 1)})
    if kind == ActionKind.REACT:
        return remaining.model_copy(update={"reactions": max(0, remaining.reactions - 1)})
    if kind == ActionKind.VOTE:
        return remaining.model_copy(update={"votes": max(0, remaining.votes - 1)})
    return remaining


def _resolve_parent(thread: Thread, spec: ActionSpec) -> Comment | None:
    """Look up reply parent from the thread using ActionSpec.target.id."""
    if spec.kind != ActionKind.REPLY:
        return None
    for comment in thread.comments:
        if comment.id == spec.target.id:
            return comment
    return None
