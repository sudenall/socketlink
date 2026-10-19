"""Unit tests for logging infrastructure and EventBusLogHandler.

OWNER: Nevin
"""

from __future__ import annotations

import logging
import unittest
from logging.handlers import RotatingFileHandler

from socketlink.common.events import EventBus, EventType
from socketlink.common.logger import (
    EventBusLogHandler,
    attach_event_bus_handler,
    get_logger,
)


class TestLogger(unittest.TestCase):
    def test_get_logger_prefix(self) -> None:
        log = get_logger("test_module")
        self.assertTrue(log.name.startswith("socketlink."))
        self.assertEqual(log.name, "socketlink.test_module")

    def test_rotating_file_handler_configured(self) -> None:
        get_logger("check_handlers")
        root = logging.getLogger("socketlink")
        rotating_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        self.assertGreaterEqual(len(rotating_handlers), 1)
        handler = rotating_handlers[0]
        self.assertEqual(handler.maxBytes, 1_000_000)
        self.assertEqual(handler.backupCount, 3)

    def test_event_bus_log_handler_publishes_event(self) -> None:
        bus = EventBus()
        q = bus.subscribe_queue()
        handler = EventBusLogHandler(bus, level=logging.INFO)

        test_logger = logging.getLogger("socketlink.event_test")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        try:
            test_logger.info("Hello through EventBus!")
            event = q.get(timeout=1.0)

            # Must satisfy the Event contract
            event.validate()
            self.assertEqual(event.type, EventType.LOG)
            self.assertEqual(event.data["level"], "INFO")
            self.assertIn("Hello through EventBus!", event.data["message"])
            self.assertEqual(event.source, "logger")
        finally:
            test_logger.removeHandler(handler)

    def test_event_bus_log_handler_level_filtering(self) -> None:
        bus = EventBus()
        q = bus.subscribe_queue()
        # handler set to WARNING level only
        handler = EventBusLogHandler(bus, level=logging.WARNING)

        test_logger = logging.getLogger("socketlink.level_test")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        try:
            test_logger.info("This should be ignored by handler")
            test_logger.warning("This is a warning")

            event = q.get(timeout=1.0)
            event.validate()
            self.assertEqual(event.data["level"], "WARNING")
            self.assertIn("This is a warning", event.data["message"])
            self.assertTrue(q.empty())
        finally:
            test_logger.removeHandler(handler)

    def test_attach_event_bus_handler_helper(self) -> None:
        bus = EventBus()
        q = bus.subscribe_queue()
        handler = attach_event_bus_handler(bus, level=logging.INFO)

        try:
            log = get_logger("attached_test")
            log.info("Testing attach_event_bus_handler")

            event = q.get(timeout=1.0)
            event.validate()
            self.assertEqual(event.type, EventType.LOG)
            self.assertEqual(event.data["level"], "INFO")
            self.assertIn("Testing attach_event_bus_handler", event.data["message"])
        finally:
            root = logging.getLogger("socketlink")
            root.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
