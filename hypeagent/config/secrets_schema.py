"""Pydantic models for secrets.local.yaml."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMSecrets(StrictModel):
    api_key: str = Field(min_length=1)


class AccountSecret(StrictModel):
    user_id: str
    token: str = Field(min_length=1)
    extra: dict[str, Any] = Field(default_factory=dict)


class Secrets(StrictModel):
    llm: LLMSecrets
    accounts: dict[str, AccountSecret] = Field(min_length=1)
