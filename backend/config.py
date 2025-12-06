import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from rich.logging import RichHandler

# Load environment variables from the project root .env (if present)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Model names (single source of truth)
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_OLLAMA_MODEL = "cas/mistral-7b-instruct-v0.3"

# Working model names (with environment variable overrides)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
RERANKER_MODEL = os.getenv("RERANK_MODEL", DEFAULT_RERANKER_MODEL)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

# Model paths and caching
HF_CACHE_DIR = os.getenv("HF_HOME", "/data/hf")


# --- Logging Configuration ---
# runtime scripts should use logging.getLogger(...) and env LOG_LEVEL
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_logging_configured = False


def _parse_level(value: int | str | None, default: int = logging.INFO) -> int:
    """Convert a user-supplied level (int or name) to a logging constant."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    name = str(value).strip().upper()
    return getattr(logging, name, default)


def _build_console_handler(level: int) -> logging.Handler:
    """Return a console handler. Use Rich in TTY, plain stream otherwise."""
    if sys.stderr.isatty():
        handler = RichHandler(
            show_time=False,
            show_path=False,
            rich_tracebacks=True,
            show_level=True,
            log_time_format="[%X]",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(level)
    return handler


def _add_file_handler(root: logging.Logger, log_dir: Path, level: int, backup_count: int) -> None:
    """Attach a rotating file handler to the root logger."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / "rag_system.log",
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except (PermissionError, OSError) as exc:
        logging.warning("Failed to configure file logging to '%s'. Error: %s", log_dir, exc)


def configure_logging(
    level: int | str | None = None,
    app_log_dir: str | Path | None = None,
    backup_count: int | None = None,
    *,
    force: bool = False,
) -> logging.Logger:
    """Configure root logging once with console and optional file handler.

    Args:
        level: Explicit log level (int or name). Defaults to LOG_LEVEL env or INFO.
        app_log_dir: Optional directory for TimedRotatingFileHandler. Defaults to APP_LOG_DIR env.
        backup_count: Number of rotated files to keep (>=0). Defaults to APP_LOG_BACKUP_COUNT env or 5.
        force: Reconfigure even if logging was already set up (useful in tests).

    Returns:
        The configured root logger.
    """
    global _logging_configured
    if _logging_configured and not force:
        return logging.getLogger()

    numeric_level = _parse_level(level or os.getenv("LOG_LEVEL"), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Clear existing handlers when forcing a reconfigure to avoid duplicates
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    root.addHandler(_build_console_handler(numeric_level))

    # Optional file logging
    log_dir_value = app_log_dir or os.getenv("APP_LOG_DIR")
    if log_dir_value:
        backup_env = backup_count if backup_count is not None else os.getenv("APP_LOG_BACKUP_COUNT", "5")
        try:
            parsed_backup = max(0, int(str(backup_env).strip()))
        except (TypeError, ValueError):
            parsed_backup = 5
            logging.warning("Invalid APP_LOG_BACKUP_COUNT=%r. Defaulting to 5.", backup_env)

        _add_file_handler(root, Path(log_dir_value), numeric_level, parsed_backup)

    # Reduce noise from common libraries
    for noisy in (
        "httpx",
        "urllib3",
        "requests",
        "sentence_transformers",
        "transformers",
        "torch",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    logging.getLogger("pypdf.generic._base").setLevel(logging.ERROR)

    logging.captureWarnings(True)
    _logging_configured = True
    return root


# Backwards compatibility alias
setup_logging = configure_logging

# --- End Logging Configuration ---
