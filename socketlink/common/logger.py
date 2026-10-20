"""Central logging.

OWNER: Nevin
RULE: Never use print() in socketlink/. Use:

    from socketlink.common.logger import get_logger
    log = get_logger(__name__)
    log.info("Client %s joined", username)

A minimal working version is provided so everyone can log from day 1.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from socketlink.common.constants import LOG_DIR, LOG_FILE
from socketlink.common.events import Event, EventBus, EventType

_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"
_configured = False


class EventBusLogHandler(logging.Handler):
    """Logging handler that publishes EventType.LOG events to an EventBus.

    Used by the server/client GUI dashboards to display live log records.
    """

    def __init__(self, event_bus: EventBus, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.event_bus = event_bus
        self.setFormatter(logging.Formatter(_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            event = Event(
                type=EventType.LOG,
                data={
                    "level": record.levelname,
                    "message": message,
                },
                source="logger",
            )
            self.event_bus.publish(event)
        except Exception:
            self.handleError(record)


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
        # 1 MB x 3 backup files rotating handler
        file_handler = RotatingFileHandler(
            Path(LOG_DIR) / LOG_FILE,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
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


def attach_event_bus_handler(event_bus: EventBus, level: int = logging.INFO) -> EventBusLogHandler:
    """Attach an EventBusLogHandler to the root 'socketlink' logger and return it.

    If an EventBusLogHandler for this event_bus is already registered, updates its
    level and returns the existing handler to prevent duplicate event publishing.
    """
    _configure_root()
    root = logging.getLogger("socketlink")
    for handler in root.handlers:
        if isinstance(handler, EventBusLogHandler) and handler.event_bus is event_bus:
            handler.setLevel(level)
            return handler
    handler = EventBusLogHandler(event_bus, level=level)
    root.addHandler(handler)
    return handler
