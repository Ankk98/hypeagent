"""Load and validate secrets.local.yaml."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hypeagent.config.loader import ConfigError, load_yaml
from hypeagent.config.schema import PersonaConfig
from hypeagent.config.secrets_schema import Secrets


class SecretsError(Exception):
    """Raised when secrets cannot be loaded or validated."""


def load_secrets(path: Path | str) -> Secrets:
    secrets_path = Path(path)
    try:
        return Secrets.model_validate(load_yaml(secrets_path))
    except ConfigError as exc:
        raise SecretsError(str(exc)) from exc
    except Exception as exc:
        raise SecretsError(f"Invalid secrets in {secrets_path}: {exc}") from exc


def validate_account_refs(
    personas: Mapping[str, PersonaConfig],
    secrets: Secrets,
) -> list[str]:
    """Return list of validation error messages for persona account references."""
    errors: list[str] = []
    for persona_id, persona in personas.items():
        account_id = persona.account
        if account_id not in secrets.accounts:
            errors.append(
                f"persona {persona_id!r} references unknown account {account_id!r} "
                f"(available: {', '.join(sorted(secrets.accounts)) or 'none'})"
            )
    return errors
