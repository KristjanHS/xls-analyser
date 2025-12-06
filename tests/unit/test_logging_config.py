import logging
from pathlib import Path

import backend.config as cfg


def _clear_root():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    root.setLevel(logging.NOTSET)


def _console_handler() -> logging.Handler | None:
    for h in logging.getLogger().handlers:
        if not isinstance(h, logging.FileHandler):
            return h
    return None


def _reset_logging_state():
    _clear_root()
    cfg._logging_configured = False


def test_env_driven_log_level_on_init(monkeypatch):
    _reset_logging_state()
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(cfg.sys.stderr, "isatty", lambda: False, raising=False)
    cfg.configure_logging(force=True)
    assert logging.getLogger().level == logging.DEBUG
    assert _console_handler().level == logging.DEBUG

    # Change env to WARNING and reload; levels should follow
    _reset_logging_state()
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    cfg.configure_logging(force=True)
    assert logging.getLogger().level == logging.WARNING
    assert _console_handler().level == logging.WARNING


def test_file_logging_creates_logfile(tmp_path, monkeypatch):
    _reset_logging_state()
    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(cfg.sys.stderr, "isatty", lambda: False, raising=False)

    # Configure logging and emit a record
    cfg.configure_logging(force=True)
    logging.getLogger("t").info("hello")

    # Expect rotated file handler targeting rag_system.log
    assert (Path(tmp_path) / "rag_system.log").exists()
    assert any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in logging.getLogger().handlers)
