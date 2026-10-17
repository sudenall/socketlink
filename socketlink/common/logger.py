"""Central logging.

OWNER: Nevin
RULE: Never use print() in socketlink/. Use:

    from socketlink.common.logger import get_logger
    log = get_logger(__name__)
    log.info("Client %s joined", username)

A minimal working version is provided so everyone can log from day 1.

TODO(Nevin):
- Switch the file handler to RotatingFileHandler (1 MB x 3 files).
- Add `EventBusLogHandler(logging.Handler)` that publishes EventType.LOG events
  so the server dashboard can show the live log.
"""

from __future__ import annotations

import logging
from pathlib import Path

from socketlink.common.constants import LOG_DIR, LOG_FILE

_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"
_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("socketlink")
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        Path(LOG_DIR).mkdir(exist_ok=True)
        file_handler = logging.FileHandler(Path(LOG_DIR) / LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Could not create log file; logging to console only")
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'socketlink' hierarchy."""
    _configure_root()
    if not name.startswith("socketlink"):
        name = f"socketlink.{name}"
    return logging.getLogger(name)
