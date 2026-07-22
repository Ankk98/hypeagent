"""Load and validate hypeagent.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hypeagent.config.schema import HypeagentConfig


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or validated."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return data


def load_config(path: Path | str) -> HypeagentConfig:
    config_path = Path(path)
    try:
        return HypeagentConfig.model_validate(load_yaml(config_path))
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Invalid config in {config_path}: {exc}") from exc
