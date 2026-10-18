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

import queue
import tkinter as tk

from socketlink.common.constants import APP_NAME, GUI_POLL_INTERVAL_MS, ConnectionState
from socketlink.common.events import Event, EventBus, EventType
from socketlink.gui import theme


class ClientApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()
        self._poll_after_id: str | None = None

    def build_ui(self) -> None:
        """Build the initial client window and disconnected status panel."""
        self.root.title(f"{APP_NAME} - Client")
        self.root.geometry(theme.CLIENT_WINDOW_SIZE)
        self.root.configure(bg=theme.COLOR_BG)

        tk.Label(
            self.root,
            text=f"{APP_NAME} Client",
            font=theme.FONT_TITLE,
            bg=theme.COLOR_BG,
            fg=theme.COLOR_TEXT,
        ).pack(anchor="w", padx=theme.PAD, pady=theme.PAD)

        self.connection_panel = tk.LabelFrame(
            self.root,
            text="Connection",
            font=theme.FONT_BOLD,
            bg=theme.COLOR_PANEL,
            fg=theme.COLOR_TEXT,
            padx=theme.PAD,
            pady=theme.PAD,
        )
        self.connection_panel.pack(fill="x", padx=theme.PAD, pady=theme.PAD_SMALL)

        self.status_label = tk.Label(
            self.connection_panel,
            text="Disconnected",
            font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL,
            fg=theme.COLOR_DISCONNECTED,
        )
        self.status_label.pack(anchor="w")
        self._poll_events()

    def _poll_events(self) -> None:
        """Drain self.events without blocking (get_nowait loop), call _handle_event,
        then reschedule with root.after(GUI_POLL_INTERVAL_MS, self._poll_events)."""
        try:
            while True:
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self._poll_after_id = self.root.after(GUI_POLL_INTERVAL_MS, self._poll_events)

    def _handle_event(self, event: Event) -> None:
        """Update the existing status label for connection lifecycle events."""
        if event.type == EventType.STATE_CHANGED:
            state = ConnectionState(event.data["new"])
        elif event.type == EventType.CONNECTED:
            state = ConnectionState.CONNECTED
        elif event.type == EventType.DISCONNECTED:
            state = ConnectionState.DISCONNECTED
        else:
            # Other event types will be handled when their panels are implemented.
            return

        colors = {
            ConnectionState.DISCONNECTED: theme.COLOR_DISCONNECTED,
            ConnectionState.CONNECTING: theme.COLOR_CONNECTING,
            ConnectionState.CONNECTED: theme.COLOR_CONNECTED,
            ConnectionState.RECONNECTING: theme.COLOR_CONNECTING,
            ConnectionState.DISCONNECTING: theme.COLOR_CONNECTING,
        }
        self.status_label.configure(text=state.value.capitalize(), fg=colors[state])

    def on_close(self) -> None:
        """Disconnect cleanly, then root.destroy()."""
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = ClientApp(root)
    app.build_ui()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
