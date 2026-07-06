from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


_LOG_DIR = Path.home() / ".prometheus" / "logs"


def setup_logging(debug: bool = False) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    log_path = (
        _LOG_DIR / f"prometheus-{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.log"
    )
    file_handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    if debug:
        stderr_handler = logging.StreamHandler()
        stderr_handler.setLevel(logging.DEBUG)
        stderr_handler.setFormatter(
            logging.Formatter(
                "[%(levelname)s] %(name)s: %(message)s",
            )
        )
        root.addHandler(stderr_handler)

    logging.getLogger("memory.redis_client").setLevel(logging.WARNING)
    logging.getLogger("agents").setLevel(logging.WARNING)
    logging.getLogger("orchestrator").setLevel(logging.WARNING)
