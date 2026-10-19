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
from datetime import datetime
from tkinter import ttk

from socketlink.common.config import ClientConfig
from socketlink.common.constants import (
    APP_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WINDOW_SIZE,
    GUI_POLL_INTERVAL_MS,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    MAX_WINDOW_SIZE,
    ConnectionState,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import ValidationError
from socketlink.gui import theme


class ClientApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()
        self._poll_after_id: str | None = None

    def build_ui(self) -> None:
        """Build the connection form without enabling network operations."""
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
        self.connection_panel.columnconfigure(1, weight=1)

        self.host_var = tk.StringVar(master=self.root, value=DEFAULT_HOST)
        self.port_var = tk.StringVar(master=self.root, value=str(DEFAULT_PORT))
        self.username_var = tk.StringVar(master=self.root)
        self.mode_var = tk.StringVar(master=self.root, value=TransportMode.TCP.value)

        for row, (label, variable) in enumerate((
            ("Host", self.host_var),
            ("Port", self.port_var),
            ("Username", self.username_var),
        )):
            tk.Label(
                self.connection_panel,
                text=label,
                font=theme.FONT_NORMAL,
                bg=theme.COLOR_PANEL,
                fg=theme.COLOR_TEXT,
            ).grid(row=row, column=0, sticky="w", padx=theme.PAD_SMALL,
                   pady=theme.PAD_SMALL)
            tk.Entry(
                self.connection_panel,
                textvariable=variable,
                font=theme.FONT_NORMAL,
                bg=theme.COLOR_PANEL,
                fg=theme.COLOR_TEXT,
                insertbackground=theme.COLOR_TEXT,
            ).grid(row=row, column=1, sticky="ew", padx=theme.PAD_SMALL,
                   pady=theme.PAD_SMALL)

        mode_panel = tk.Frame(self.connection_panel, bg=theme.COLOR_PANEL)
        mode_panel.grid(row=3, column=1, sticky="w", pady=theme.PAD_SMALL)
        mode_style = ttk.Style(self.root)
        mode_style.configure(
            "SocketLink.TRadiobutton", font=theme.FONT_NORMAL,
            background=theme.COLOR_PANEL, foreground=theme.COLOR_TEXT,
        )
        mode_style.map(
            "SocketLink.TRadiobutton",
            background=[("active", theme.COLOR_PANEL)],
            foreground=[("active", theme.COLOR_TEXT)],
        )
        self.mode_buttons: dict[TransportMode, ttk.Radiobutton] = {}
        for mode in TransportMode:
            button = ttk.Radiobutton(
                mode_panel,
                text=mode.value.upper(),
                variable=self.mode_var,
                value=mode.value,
                style="SocketLink.TRadiobutton",
            )
            button.state(["!disabled"])
            button.pack(side="left", padx=theme.PAD_SMALL)
            self.mode_buttons[mode] = button

        button_panel = tk.Frame(self.connection_panel, bg=theme.COLOR_PANEL)
        button_panel.grid(row=4, column=1, sticky="w", pady=theme.PAD_SMALL)
        self.connect_button = tk.Button(
            button_panel, text="Connect", state=tk.DISABLED,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            disabledforeground=theme.COLOR_MUTED,
        )
        self.connect_button.pack(side="left", padx=theme.PAD_SMALL)
        self.disconnect_button = tk.Button(
            button_panel, text="Disconnect", state=tk.DISABLED,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            disabledforeground=theme.COLOR_MUTED,
        )
        self.disconnect_button.pack(side="left", padx=theme.PAD_SMALL)

        self.status_label = tk.Label(
            self.connection_panel,
            text="Disconnected",
            font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL,
            fg=theme.COLOR_DISCONNECTED,
        )
        self.status_label.grid(row=5, column=0, columnspan=2, sticky="w",
                               padx=theme.PAD_SMALL, pady=theme.PAD_SMALL)
        self.chat_panel = tk.LabelFrame(
            self.root, text="Chat", font=theme.FONT_BOLD,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            padx=theme.PAD, pady=theme.PAD,
        )
        self.chat_panel.pack(fill="both", expand=True, padx=theme.PAD, pady=theme.PAD_SMALL)
        self.chat_panel.rowconfigure(0, weight=1)
        self.chat_panel.columnconfigure(0, weight=1)

        history_panel = tk.Frame(self.chat_panel, bg=theme.COLOR_PANEL)
        history_panel.grid(row=0, column=0, sticky="nsew", padx=theme.PAD_SMALL)
        history_panel.rowconfigure(0, weight=1)
        history_panel.columnconfigure(0, weight=1)
        self.message_history = tk.Text(
            history_panel, height=5, width=40, wrap="word", state=tk.DISABLED,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
        )
        self.message_history.grid(row=0, column=0, sticky="nsew")
        self.message_scrollbar = tk.Scrollbar(
            history_panel, orient="vertical", command=self.message_history.yview,
        )
        self.message_scrollbar.grid(row=0, column=1, sticky="ns")
        self.message_history.configure(yscrollcommand=self.message_scrollbar.set)

        users_panel = tk.LabelFrame(
            self.chat_panel, text="Recipients / Online users", font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
        )
        users_panel.grid(row=0, column=1, sticky="nsew", padx=theme.PAD_SMALL)
        self.user_list = tk.Listbox(
            users_panel, height=5, width=24, exportselection=False,
            selectmode=tk.SINGLE, font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            selectbackground=theme.COLOR_ACCENT, selectforeground=theme.COLOR_PANEL,
        )
        self.user_list.pack(side="left", fill="both", expand=True)
        user_scrollbar = tk.Scrollbar(
            users_panel, orient="vertical", command=self.user_list.yview,
        )
        user_scrollbar.pack(side="right", fill="y")
        self.user_list.configure(yscrollcommand=user_scrollbar.set)
        self.user_list.insert(tk.END, "Everyone")
        self.user_list.selection_set(0)

        self.message_var = tk.StringVar(master=self.root)
        self.message_entry = tk.Entry(
            self.chat_panel, textvariable=self.message_var, font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT, insertbackground=theme.COLOR_TEXT,
        )
        self.message_entry.grid(row=1, column=0, sticky="ew",
                                padx=theme.PAD_SMALL, pady=theme.PAD_SMALL)
        self.send_button = tk.Button(
            self.chat_panel, text="Send", state=tk.DISABLED,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            disabledforeground=theme.COLOR_MUTED,
        )
        self.send_button.grid(row=1, column=1, sticky="e",
                              padx=theme.PAD_SMALL, pady=theme.PAD_SMALL)
        self._build_udp_panel()
        self._poll_events()

    def _build_udp_panel(self) -> None:
        """Build local simulation inputs; no transport is called here."""
        defaults = ClientConfig()
        self.loss_percent_var = tk.IntVar(master=self.root, value=int(defaults.loss_rate * 100))
        self.delay_ms_var = tk.IntVar(master=self.root, value=defaults.delay_ms)
        self.window_size_var = tk.StringVar(master=self.root, value=str(DEFAULT_WINDOW_SIZE))
        self.udp_panel = tk.LabelFrame(
            self.root, text="UDP Simulation", font=theme.FONT_BOLD,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            padx=theme.PAD, pady=theme.PAD_SMALL,
        )
        self.udp_panel.pack(fill="x", before=self.chat_panel,
                            padx=theme.PAD, pady=theme.PAD_SMALL)
        self.udp_controls: list[tk.Scale | tk.Spinbox] = []
        for column, (label, variable, maximum) in enumerate((
            ("Packet Loss (%)", self.loss_percent_var, int(MAX_SIMULATED_LOSS * 100)),
            ("Delay (ms)", self.delay_ms_var, MAX_SIMULATED_DELAY_MS),
        )):
            self.udp_panel.columnconfigure(column, weight=1)
            tk.Label(
                self.udp_panel, text=label, font=theme.FONT_NORMAL,
                bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            ).grid(row=0, column=column, sticky="w", padx=theme.PAD_SMALL)
            control = tk.Scale(
                self.udp_panel, from_=0, to=maximum, resolution=1,
                variable=variable, orient=tk.HORIZONTAL, showvalue=True,
                font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
                troughcolor=theme.COLOR_BG, activebackground=theme.COLOR_ACCENT,
                highlightthickness=0,
            )
            control.grid(row=1, column=column, sticky="ew", padx=theme.PAD_SMALL)
            self.udp_controls.append(control)
        tk.Label(
            self.udp_panel, text="Window Size (packets)", font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
        ).grid(row=0, column=2, sticky="w", padx=theme.PAD_SMALL)
        self.window_size_spinbox = tk.Spinbox(
            self.udp_panel, from_=1, to=MAX_WINDOW_SIZE, increment=1,
            textvariable=self.window_size_var, width=6, font=theme.FONT_NORMAL,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT, insertbackground=theme.COLOR_TEXT,
            disabledbackground=theme.COLOR_BG, disabledforeground=theme.COLOR_MUTED,
        )
        self.window_size_spinbox.grid(row=1, column=2, sticky="w", padx=theme.PAD_SMALL)
        self.udp_controls.append(self.window_size_spinbox)
        self.mode_var.trace_add("write", self._update_udp_controls)
        self._update_udp_controls()

    def _update_udp_controls(self, *_args: str) -> None:
        """Enable simulation inputs only while UDP is selected."""
        state = tk.NORMAL if self.mode_var.get() == TransportMode.UDP.value else tk.DISABLED
        for control in self.udp_controls:
            control.configure(state=state)

    def _build_client_config(self) -> ClientConfig:
        """Read the form without connecting or calling ClientConfig.validate().

        Convert numeric inputs and check control bounds; full configuration
        validation belongs to ClientConfig.
        """
        try:
            port = int(self.port_var.get())
        except ValueError as exc:
            raise ValidationError("Port must be a whole number.") from exc
        try:
            loss_percent = self.loss_percent_var.get()
            delay_ms = self.delay_ms_var.get()
            window_size = int(self.window_size_var.get())
        except (ValueError, tk.TclError) as exc:
            raise ValidationError("UDP settings must be whole numbers.") from exc
        if not 0 <= loss_percent <= MAX_SIMULATED_LOSS * 100:
            raise ValidationError(f"Packet loss must be between 0 and {MAX_SIMULATED_LOSS * 100:g}%.")
        if not 0 <= delay_ms <= MAX_SIMULATED_DELAY_MS:
            raise ValidationError(f"Delay must be between 0 and {MAX_SIMULATED_DELAY_MS} ms.")
        if not 1 <= window_size <= MAX_WINDOW_SIZE:
            raise ValidationError(f"Window size must be between 1 and {MAX_WINDOW_SIZE}.")
        return ClientConfig(
            host=self.host_var.get().strip(),
            port=port,
            username=self.username_var.get().strip(),
            mode=TransportMode(self.mode_var.get()),
            loss_rate=loss_percent / 100,
            delay_ms=delay_ms,
            window_size=window_size,
        )

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
        """Render queued chat, user-list and connection events on the Tk thread."""
        if event.type == EventType.MESSAGE_RECEIVED:
            timestamp = datetime.fromtimestamp(event.data["timestamp"]).strftime("%H:%M:%S")
            recipient = event.data["to"]
            audience = "Everyone" if recipient is None else recipient
            line = f"[{timestamp}] {event.data['from']} -> {audience}: {event.data['text']}\n"
            self.message_history.configure(state=tk.NORMAL)
            try:
                self.message_history.insert(tk.END, line)
                self.message_history.see(tk.END)
            finally:
                self.message_history.configure(state=tk.DISABLED)
            return
        if event.type == EventType.USER_LIST_UPDATED:
            selection = self.user_list.curselection()
            selected = self.user_list.get(selection[0]) if selection else "Everyone"
            users = ["Everyone", *event.data["users"]]
            self.user_list.delete(0, tk.END)
            self.user_list.insert(tk.END, *users)
            self.user_list.selection_set(users.index(selected) if selected in users else 0)
            return
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
