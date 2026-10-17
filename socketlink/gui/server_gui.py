"""Server dashboard window (Tkinter).

OWNER: Tina
USES:  server/server.py (ChatServer), common/events.py, gui/theme.py

Same GOLDEN RULE as client_gui.py: widgets only from the Tk main thread,
events via subscribe_queue() + root.after polling.

Required widgets (README section 7, Tina's checklist):
- Control panel: bind host, port, TCP/UDP radio, Start/Stop button, status label
- Connected clients table (ttk.Treeview): username, address, connected since,
  last seen, packets in/out; right-click -> Kick
- Live log (EventType.LOG + CLIENT_JOINED/LEFT + ERROR)
- Totals / statistics panel (STATS_UPDATED)
- Network simulation panel (UDP only): loss %, delay ms
"""

from __future__ import annotations

import tkinter as tk

from socketlink.common.events import Event, EventBus


class ServerApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()

    def build_ui(self) -> None:
        raise NotImplementedError("TODO(Tina)")

    def _poll_events(self) -> None:
        raise NotImplementedError("TODO(Tina)")

    def _handle_event(self, event: Event) -> None:
        raise NotImplementedError("TODO(Tina)")

    def on_close(self) -> None:
        """Stop the server cleanly, then root.destroy()."""
        raise NotImplementedError("TODO(Tina)")


def main() -> None:
    root = tk.Tk()
    app = ServerApp(root)
    app.build_ui()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
