"""Client window (Tkinter).

OWNER: İlayda
USES:  client/client.py (ChatClient), common/events.py, gui/theme.py

GOLDEN RULE: only the Tk main thread touches widgets. Network results arrive via
`self.events = event_bus.subscribe_queue()` and are handled in `_poll_events()`,
which reschedules itself with `self.root.after(GUI_POLL_INTERVAL_MS, ...)`.

Required widgets (README section 7, İlayda's checklist):
- Connection panel: host, port, username, TCP/UDP radio, Connect/Disconnect button,
  coloured status label (DISCONNECTED / CONNECTING / CONNECTED / RECONNECTING)
- Chat panel: message list, input box + Send, recipient combobox ("Everyone" + users)
- Online users list
- "Send file..." button + progress bar
- Network simulation panel (UDP only, disabled in TCP): loss % slider,
  delay ms slider, window size spinbox
- Statistics panel (updated from STATS_UPDATED)
- Packet log (sent / received / dropped / retransmitted rows, coloured from theme.py)
"""

from __future__ import annotations

import tkinter as tk

from socketlink.common.events import Event, EventBus


class ClientApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()

    def build_ui(self) -> None:
        raise NotImplementedError("TODO(İlayda)")

    def _poll_events(self) -> None:
        """Drain self.events without blocking (get_nowait loop), call _handle_event,
        then reschedule with root.after(GUI_POLL_INTERVAL_MS, self._poll_events)."""
        raise NotImplementedError("TODO(İlayda)")

    def _handle_event(self, event: Event) -> None:
        raise NotImplementedError("TODO(İlayda)")

    def on_close(self) -> None:
        """Disconnect cleanly, then root.destroy()."""
        raise NotImplementedError("TODO(İlayda)")


def main() -> None:
    root = tk.Tk()
    app = ClientApp(root)
    app.build_ui()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
