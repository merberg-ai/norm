from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


def setup_logging(config: dict[str, Any], logs_dir: Path) -> logging.Logger:
    level_name = str(config.get("logging", {}).get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("norm")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logging_config = config.get("logging", {})

    if logging_config.get("console_enabled", True):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(level)
        logger.addHandler(console)

    if logging_config.get("file_enabled", True):
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_name = logging_config.get("file_name", "norm-beta2.log")
        file_handler = logging.FileHandler(logs_dir / file_name, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    return logger
