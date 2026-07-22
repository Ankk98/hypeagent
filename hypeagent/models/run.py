"""Run context and result models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from hypeagent.config.schema import HypeagentConfig
from hypeagent.config.secrets_schema import AccountSecret, Secrets

if TYPE_CHECKING:
    from hypeagent.config.schema import PersonaConfig


class RunMode(StrEnum):
    DRY_RUN = "dry_run"
    APPROVE = "approve"
    AUTO = "auto"


@dataclass
class RunContext:
    run_id: str
    mode: RunMode
    config: HypeagentConfig
    secrets: Secrets
    agent_id: str
    persona: PersonaConfig
    account: AccountSecret
    connector: Any
    db: Any
    logger: logging.Logger
    llm_client: Any
    budget_guard: Any


@dataclass
class RunResult:
    run_id: str
    mode: RunMode
    agent_ids: list[str]
    proposed_actions: list[Any] = field(default_factory=list)
    published_actions: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "completed"
