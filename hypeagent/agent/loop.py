"""Sequential multi-agent run orchestration."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from hypeagent.agent.approval import ApprovalDecision, ApprovalPrompt, ApprovalQuitError
from hypeagent.agent.drafter import Drafter
from hypeagent.agent.planner import Planner
from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets_schema import Secrets
from hypeagent.db.connection import Database
from hypeagent.db.repositories.agent_memory import AgentMemoryRepository
from hypeagent.db.repositories.runs import RunsRepository
from hypeagent.db.repositories.usage import UsageRepository
from hypeagent.knowledge.static import StaticKnowledgeLoader
from hypeagent.knowledge.tools import ToolExecutor, ToolRegistry
from hypeagent.llm.budget import BudgetExceededError, BudgetGuard
from hypeagent.llm.client import LLMClient
from hypeagent.models.action import ProposedAction, PublishedAction
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
                    proposed, published = self._run_one_agent(
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

                if proposed is not None:
                    proposed_actions.append(proposed)
                if published is not None:
                    published_actions.append(published)

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
    ) -> tuple[ProposedAction | None, PublishedAction | None]:
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
            return None, None

        content = random.choice(candidates)
        self._logger.info(
            "run_id=%s agent=%s event=content_picked content_id=%s comment_count=%d",
            run_id,
            agent_id,
            content.id,
            content.comment_count,
        )

        thread = connector.get_thread(ctx, content.id)
        decision = planner.decide(self._config.run.per_agent, thread, ctx)
        if decision is None:
            self._logger.warning(
                "run_id=%s agent=%s event=no_action_quota content_id=%s",
                run_id,
                agent_id,
                content.id,
            )
            return None, None

        draft_result = drafter.draft(ctx, thread, decision.action_type, decision.parent)
        draft_text = draft_result.final_text
        if not draft_text:
            self._logger.warning(
                "run_id=%s agent=%s event=empty_draft content_id=%s",
                run_id,
                agent_id,
                content.id,
            )
            return None, None

        parent_preview = (
            RunsRepository.preview_text(decision.parent.body)
            if decision.parent is not None
            else None
        )
        proposed = ProposedAction(
            run_id=run_id,
            agent_id=agent_id,
            account_id=persona.account,
            action_type=decision.action_type,
            content_id=content.id,
            content_body_preview=RunsRepository.preview_text(content.body),
            parent_comment_id=decision.parent.id if decision.parent else None,
            parent_comment_preview=parent_preview,
            draft_text=draft_text,
            targeting_strategy=self._config.targeting.strategy,
            llm_model=draft_result.model,
            llm_tokens_in=draft_result.tokens_in,
            llm_tokens_out=draft_result.tokens_out,
            llm_cost_usd=draft_result.cost_usd,
            tool_calls=list(draft_result.tool_calls),
        )
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
        budget_guard.check()
        return proposed, published

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
            if response.draft_text != proposed.draft_text:
                proposed.draft_text = response.draft_text
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
        comment = connector.publish_comment(
            ctx,
            proposed.content_id,
            proposed.draft_text,
            proposed.parent_comment_id,
        )
        runs_repo.mark_published(action_id, comment.id)
        memory_repo.record(
            agent_id=proposed.agent_id,
            content_id=proposed.content_id,
            action_type=proposed.action_type.value,
            text_preview=proposed.draft_text,
        )
        published = PublishedAction(
            proposed=proposed,
            platform_comment_id=comment.id,
            published_at=datetime.now(UTC),
            approved_by=approved_by,  # type: ignore[arg-type]
        )
        self._logger.info(
            "run_id=%s agent=%s event=published action=%s content_id=%s comment_id=%s",
            proposed.run_id,
            proposed.agent_id,
            proposed.action_type.value,
            proposed.content_id,
            comment.id,
        )
        return published
