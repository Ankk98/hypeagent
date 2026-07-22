"""Unit tests for logging setup."""

from __future__ import annotations

from pathlib import Path

from hypeagent.config.schema import LoggingConfig
from hypeagent.logging.setup import (
    ROTATION_BACKUP_COUNT,
    ROTATION_MAX_BYTES,
    configure_logging,
    resolve_log_file,
)


def test_resolve_log_file_relative_to_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    path = resolve_log_file("./logs/hypeagent.log", config_dir)
    assert path == config_dir / "logs" / "hypeagent.log"


def test_resolve_log_file_default_home() -> None:
    path = resolve_log_file(None, Path("/tmp"))
    assert path == Path.home() / ".hypeagent" / "logs" / "hypeagent.log"


def test_configure_logging_writes_structured_record(tmp_path: Path) -> None:
    config_dir = tmp_path / "project"
    config_dir.mkdir()
    logging_config = LoggingConfig(
        level="info",
        file="./logs/hypeagent.log",
        console=False,
    )
    logger = configure_logging(logging_config, config_dir=config_dir)
    logger.info(
        "run_id=%s agent=%s event=content_picked content_id=%s comment_count=%d",
        "abc123",
        "priya_blr",
        "post1",
        3,
    )

    for handler in logger.handlers:
        handler.flush()

    log_path = config_dir / "logs" / "hypeagent.log"
    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    assert "INFO" in content
    assert "run_id=abc123" in content
    assert "agent=priya_blr" in content
    assert "event=content_picked" in content
    assert content.endswith("\n")


def test_rotation_constants_match_spec() -> None:
    assert ROTATION_MAX_BYTES == 10 * 1024 * 1024
    assert ROTATION_BACKUP_COUNT == 5
