"""Event system (Observer pattern) that connects the network core to the GUI.

OWNER: Sude

How it works:
    network thread --publish(Event)--> EventBus --callback--> subscriber

The GUI NEVER receives callbacks directly from network threads (Tkinter is not
thread-safe). Instead the GUI subscribes with `bus.subscribe_queue(q)`, which puts
every event into a `queue.Queue`; the GUI drains that queue every
GUI_POLL_INTERVAL_MS with `root.after(...)` on the main thread.

RULE: The `data` dict of each event type MUST contain exactly the keys listed in
EVENT_DATA_KEYS below. Adding a key = PR to this file first.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # --- connection lifecycle ---
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STATE_CHANGED = "state_changed"
    # --- server-side client lifecycle ---
    SERVER_STARTED = "server_started"
    SERVER_STOPPED = "server_stopped"
    CLIENT_JOINED = "client_joined"
    CLIENT_LEFT = "client_left"
    # --- chat ---
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    USER_LIST_UPDATED = "user_list_updated"
    # --- files ---
    FILE_OFFERED = "file_offered"
    FILE_PROGRESS = "file_progress"
    FILE_COMPLETED = "file_completed"
    FILE_FAILED = "file_failed"
    # --- packet level (used by the live packet log / statistics) ---
    PACKET_SENT = "packet_sent"
    PACKET_RECEIVED = "packet_received"
    PACKET_DROPPED = "packet_dropped"          # dropped by the loss simulator
    PACKET_RETRANSMITTED = "packet_retransmitted"
    PACKET_CORRUPTED = "packet_corrupted"      # checksum failed
    STATS_UPDATED = "stats_updated"
    # --- misc ---
    ERROR = "error"
    LOG = "log"


# Required keys of Event.data for each EventType (the contract between core and GUI).
# `reason` of DISCONNECTED, CLIENT_LEFT and SERVER_STOPPED must be a DisconnectReason value
# (constants.py); `reason` of FILE_FAILED must be a FileFailReason value. Publish
# `Enum.X.value`, never a free-form string. PACKET_CORRUPTED uses "checksum" or "malformed".
EVENT_DATA_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.CONNECTED: ("host", "port", "mode", "username", "client_id"),
    EventType.DISCONNECTED: ("reason",),
    EventType.STATE_CHANGED: ("old", "new"),
    EventType.SERVER_STARTED: ("host", "port", "mode"),
    EventType.SERVER_STOPPED: ("reason",),
    EventType.CLIENT_JOINED: ("username", "address"),
    EventType.CLIENT_LEFT: ("username", "reason"),
    EventType.MESSAGE_SENT: ("to", "text", "timestamp"),
    EventType.MESSAGE_RECEIVED: ("from", "to", "text", "timestamp"),
    EventType.USER_LIST_UPDATED: ("users",),
    EventType.FILE_OFFERED: ("transfer_id", "from", "filename", "size"),
    EventType.FILE_PROGRESS: ("transfer_id", "direction", "done_bytes", "total_bytes"),
    EventType.FILE_COMPLETED: ("transfer_id", "direction", "path"),
    EventType.FILE_FAILED: ("transfer_id", "direction", "reason"),
    EventType.PACKET_SENT: ("summary",),
    EventType.PACKET_RECEIVED: ("summary",),
    EventType.PACKET_DROPPED: ("summary",),
    EventType.PACKET_RETRANSMITTED: ("summary", "attempt"),
    EventType.PACKET_CORRUPTED: ("reason",),
    EventType.STATS_UPDATED: ("stats",),
    EventType.ERROR: ("code", "message"),
    EventType.LOG: ("level", "message"),
}


@dataclass(frozen=True)
class Event:
    """Immutable event object. Create with Event(EventType.X, {...})."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""                      # "client", "server", "transport", ...
    timestamp: float = field(default_factory=time.time)

    def validate(self) -> None:
        """Raise KeyError if a required data key is missing (used in tests)."""
        missing = [k for k in EVENT_DATA_KEYS[self.type] if k not in self.data]
        if missing:
            raise KeyError(f"{self.type.value} event missing keys: {missing}")


Subscriber = Callable[[Event], None]


class EventBus:
    """Thread-safe publish/subscribe hub (Observer pattern).

    Usage:
        bus = EventBus()
        bus.subscribe(EventType.MESSAGE_RECEIVED, handler)  # specific type
        bus.subscribe(None, handler)                        # all types
        gui_queue = bus.subscribe_queue()                   # for Tkinter
        bus.publish(Event(EventType.LOG, {"level": "INFO", "message": "hi"}))
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[Subscriber]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType | None, callback: Subscriber) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: EventType | None, callback: Subscriber) -> None:
        with self._lock:
            callbacks = self._subscribers.get(event_type, [])
            if callback in callbacks:
                callbacks.remove(callback)

    def subscribe_queue(self, maxsize: int = 0) -> queue.Queue[Event]:
        """Return a Queue that receives every event. Use this from the GUI."""
        q: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self.subscribe(None, q.put)
        return q

    def publish(self, event: Event) -> None:
        """Deliver `event` to subscribers. Never raises: subscriber errors are swallowed."""
        with self._lock:
            callbacks = list(self._subscribers.get(event.type, []))
            callbacks += self._subscribers.get(None, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a bad subscriber must not kill a network thread
                pass
