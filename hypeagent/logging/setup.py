"""File and console logging with rotation (§12)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from hypeagent.config.schema import LoggingConfig

LOG_FORMAT = "%(asctime)s %(levelname)-5s %(message)s"
ROTATION_MAX_BYTES = 10 * 1024 * 1024
ROTATION_BACKUP_COUNT = 5

LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class UTCFormatter(logging.Formatter):
    """ISO-8601 UTC timestamps with millisecond precision."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        from datetime import UTC, datetime

        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


def resolve_log_file(log_file: str | None, config_dir: Path) -> Path:
    """Resolve the log file path relative to the config directory."""
    if log_file:
        path = Path(log_file)
        if not path.is_absolute():
            path = config_dir / path
        return path
    return Path.home() / ".hypeagent" / "logs" / "hypeagent.log"


def configure_logging(
    logging_config: LoggingConfig,
    *,
    config_dir: Path,
    verbose: bool = False,
) -> logging.Logger:
    """Configure the hypeagent root logger with optional file rotation."""
    logger = logging.getLogger("hypeagent")
    logger.handlers.clear()
    logger.propagate = False

    level = logging.DEBUG if verbose else LEVEL_MAP[logging_config.level]
    logger.setLevel(level)

    formatter = UTCFormatter(LOG_FORMAT)

    if logging_config.console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    log_path = resolve_log_file(logging_config.file, config_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=ROTATION_MAX_BYTES,
        backupCount=ROTATION_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
