from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    level_name = config.get("system", {}).get("log_level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    base_dir = Path(config.get("_base_dir", ".")).resolve()
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "norm.log"

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("norm")
    logger.info("Logging initialized: %s", log_path)
    return logger
