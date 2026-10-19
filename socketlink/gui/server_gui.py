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

Demo mode (`python run_server.py --demo`): `DemoServer` replaces ChatServer and
publishes fake events from a background thread, so the dashboard can be used and shown
before the real server exists. It goes through the same EventBus queue as the real one.
"""

from __future__ import annotations

import argparse
import queue
import random
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from socketlink.common.config import ServerConfig
from socketlink.common.constants import (
    APP_NAME,
    GUI_POLL_INTERVAL_MS,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    STATS_UPDATE_INTERVAL,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import ValidationError
from socketlink.common.stats import TransportStats
from socketlink.gui import theme
from socketlink.server.server import ChatServer, ClientInfo

# Same limit as the client packet log (README section 7).
# TODO(Sude): move to constants.py as MAX_LOG_LINES if approved.
_MAX_LOG_LINES = 500

# (column id, heading, widest typical value -> sets the column width)
_CLIENT_COLUMNS = (
    ("username", "Username", "abcdefghijklmnop"),
    ("address", "Address", "192.168.100.100:65535"),
    ("connected_at", "Connected", "00:00:00"),
    ("last_seen", "Last seen", "00:00:00"),
    ("packets_received", "Pkts in", "999999"),
    ("packets_sent", "Pkts out", "999999"),
)

_STAT_ROWS = (
    ("packets_sent", "Packets sent"),
    ("packets_received", "Packets received"),
    ("bytes_sent", "Bytes sent"),
    ("bytes_received", "Bytes received"),
    ("retransmissions", "Retransmissions"),
    ("packets_dropped_simulated", "Dropped (simulated)"),
    ("duplicates_received", "Duplicates"),
    ("checksum_errors", "Checksum errors"),
    ("avg_rtt_ms", "Avg RTT (ms)"),
)


class ServerApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None,
                 server_class: type[ChatServer] = ChatServer) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()
        self.server_class = server_class
        self.server: ChatServer | None = None
        self._poll_after_id: str | None = None

    def build_ui(self) -> None:
        """Build every panel and start polling the event queue."""
        demo = " (demo)" if self.server_class is not ChatServer else ""
        self.root.title(f"{APP_NAME} - Server{demo}")
        self.root.geometry(theme.SERVER_WINDOW_SIZE)
        self.root.configure(bg=theme.COLOR_BG)

        tk.Label(
            self.root, text=f"{APP_NAME} Server{demo}", font=theme.FONT_TITLE,
            bg=theme.COLOR_BG, fg=theme.COLOR_TEXT,
        ).pack(anchor="w", padx=theme.PAD, pady=theme.PAD)

        top = tk.Frame(self.root, bg=theme.COLOR_BG)
        top.pack(fill="x", padx=theme.PAD, pady=theme.PAD_SMALL)
        self._build_control_panel(top)
        self._build_udp_panel(top)

        # The log is packed before the middle row so it always keeps its own height.
        self._build_log_panel()

        middle = tk.Frame(self.root, bg=theme.COLOR_BG)
        middle.pack(fill="both", expand=True, padx=theme.PAD, pady=theme.PAD_SMALL)
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(0, weight=1)
        self._build_clients_panel(middle)
        self._build_stats_panel(middle)

        self._set_running(False)
        self._poll_events()

    # ---- panels -------------------------------------------------------------
    def _panel(self, parent: tk.Misc, title: str) -> tk.LabelFrame:
        return tk.LabelFrame(
            parent, text=title, font=theme.FONT_BOLD,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            padx=theme.PAD, pady=theme.PAD_SMALL,
        )

    def _label(self, parent: tk.Misc, text: str, fg: str = theme.COLOR_TEXT) -> tk.Label:
        return tk.Label(parent, text=text, font=theme.FONT_NORMAL,
                        bg=theme.COLOR_PANEL, fg=fg)

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(parent, text=text, command=command, font=theme.FONT_NORMAL,
                         bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
                         disabledforeground=theme.COLOR_MUTED)

    def _build_control_panel(self, parent: tk.Frame) -> None:
        defaults = ServerConfig()
        panel = self._panel(parent, "Server")
        panel.pack(side="left", fill="both", expand=True, padx=(0, theme.PAD_SMALL))

        self.host_var = tk.StringVar(master=self.root, value=defaults.host)
        self.port_var = tk.StringVar(master=self.root, value=str(defaults.port))
        self.mode_var = tk.StringVar(master=self.root, value=defaults.mode.value)

        self.config_entries: list[tk.Entry] = []
        for column, (label, variable, width) in enumerate((
            ("Bind host", self.host_var, 16),
            ("Port", self.port_var, 7),
        )):
            self._label(panel, label).grid(row=0, column=2 * column, sticky="w",
                                           padx=theme.PAD_SMALL, pady=theme.PAD_SMALL)
            entry = tk.Entry(panel, textvariable=variable, width=width, font=theme.FONT_NORMAL,
                             bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
                             insertbackground=theme.COLOR_TEXT,
                             disabledbackground=theme.COLOR_BG,
                             disabledforeground=theme.COLOR_MUTED)
            entry.grid(row=0, column=2 * column + 1, sticky="w", padx=theme.PAD_SMALL)
            self.config_entries.append(entry)

        style = ttk.Style(self.root)
        style.configure("SocketLink.TRadiobutton", font=theme.FONT_NORMAL,
                        background=theme.COLOR_PANEL, foreground=theme.COLOR_TEXT)
        self.mode_buttons: list[ttk.Radiobutton] = []
        for offset, mode in enumerate(TransportMode):
            button = ttk.Radiobutton(panel, text=mode.name, value=mode.value,
                                     variable=self.mode_var, style="SocketLink.TRadiobutton")
            button.grid(row=0, column=4 + offset, sticky="w", padx=theme.PAD_SMALL)
            self.mode_buttons.append(button)

        buttons = tk.Frame(panel, bg=theme.COLOR_PANEL)
        buttons.grid(row=1, column=0, columnspan=4, sticky="w", pady=theme.PAD_SMALL)
        self.start_button = self._button(buttons, "Start", self._on_start)
        self.start_button.pack(side="left", padx=theme.PAD_SMALL)
        self.stop_button = self._button(buttons, "Stop", self._on_stop)
        self.stop_button.pack(side="left", padx=theme.PAD_SMALL)

        self.status_label = self._label(panel, "Stopped", fg=theme.COLOR_DISCONNECTED)
        self.status_label.configure(font=theme.FONT_BOLD)
        self.status_label.grid(row=1, column=4, columnspan=2, sticky="w", padx=theme.PAD_SMALL)

    def _build_udp_panel(self, parent: tk.Frame) -> None:
        defaults = ServerConfig()
        panel = self._panel(parent, "UDP Simulation")
        panel.pack(side="left", fill="both", padx=(theme.PAD_SMALL, 0))

        self.loss_percent_var = tk.IntVar(master=self.root, value=int(defaults.loss_rate * 100))
        self.delay_ms_var = tk.IntVar(master=self.root, value=defaults.delay_ms)
        self.udp_controls: list[tk.Scale | tk.Button] = []
        for column, (label, variable, maximum) in enumerate((
            ("Packet Loss (%)", self.loss_percent_var, int(MAX_SIMULATED_LOSS * 100)),
            ("Delay (ms)", self.delay_ms_var, MAX_SIMULATED_DELAY_MS),
        )):
            self._label(panel, label).grid(row=0, column=column, sticky="w",
                                           padx=theme.PAD_SMALL)
            control = tk.Scale(
                panel, from_=0, to=maximum, resolution=1, variable=variable,
                orient=tk.HORIZONTAL, showvalue=True, length=140,
                font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
                troughcolor=theme.COLOR_BG, activebackground=theme.COLOR_ACCENT,
                highlightthickness=0,
            )
            control.grid(row=1, column=column, sticky="ew", padx=theme.PAD_SMALL)
            self.udp_controls.append(control)
        self.apply_button = self._button(panel, "Apply", self._on_apply_network)
        self.apply_button.grid(row=1, column=2, sticky="s", padx=theme.PAD_SMALL)
        self.udp_controls.append(self.apply_button)
        self.mode_var.trace_add("write", self._update_udp_controls)

    def _build_clients_panel(self, parent: tk.Frame) -> None:
        panel = self._panel(parent, "Connected clients (right-click to kick)")
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, theme.PAD_SMALL))
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)

        # Row height and column widths follow the font, so nothing overlaps on high-DPI screens.
        normal_font = tkfont.Font(root=self.root, font=theme.FONT_NORMAL)
        bold_font = tkfont.Font(root=self.root, font=theme.FONT_BOLD)
        style = ttk.Style(self.root)
        style.configure("SocketLink.Treeview", font=theme.FONT_NORMAL,
                        background=theme.COLOR_PANEL, fieldbackground=theme.COLOR_PANEL,
                        foreground=theme.COLOR_TEXT,
                        rowheight=normal_font.metrics("linespace") + theme.PAD_SMALL)
        style.configure("SocketLink.Treeview.Heading", font=theme.FONT_BOLD)
        self.client_table = ttk.Treeview(
            panel, columns=[key for key, _, _ in _CLIENT_COLUMNS], show="headings",
            selectmode="browse", style="SocketLink.Treeview", height=8,
        )
        for key, heading, sample in _CLIENT_COLUMNS:
            width = max(bold_font.measure(heading), normal_font.measure(sample)) + 2 * theme.PAD
            self.client_table.heading(key, text=heading, anchor="w")
            self.client_table.column(key, width=width, minwidth=width, anchor="w")
        self.client_table.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(panel, orient="vertical", command=self.client_table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.client_table.configure(yscrollcommand=scrollbar.set)

        self.client_menu = tk.Menu(self.root, tearoff=False, font=theme.FONT_NORMAL)
        self.client_menu.add_command(label="Kick", command=self._on_kick_selected)
        self.client_table.bind("<Button-3>", self._on_table_right_click)
        self.client_table.bind("<Button-2>", self._on_table_right_click)   # macOS

    def _build_stats_panel(self, parent: tk.Frame) -> None:
        panel = self._panel(parent, "Statistics")
        panel.grid(row=0, column=1, sticky="nsew", padx=(theme.PAD_SMALL, 0))
        self.client_count_label = self._label(panel, "0")
        self._label(panel, "Clients").grid(row=0, column=0, sticky="w", padx=theme.PAD_SMALL)
        self.client_count_label.grid(row=0, column=1, sticky="e", padx=theme.PAD_SMALL)
        self.stat_labels: dict[str, tk.Label] = {}
        for row, (key, text) in enumerate(_STAT_ROWS, start=1):
            self._label(panel, text).grid(row=row, column=0, sticky="w", padx=theme.PAD_SMALL)
            value = self._label(panel, "0")
            value.grid(row=row, column=1, sticky="e", padx=theme.PAD_SMALL)
            self.stat_labels[key] = value

    def _build_log_panel(self) -> None:
        panel = self._panel(self.root, "Live log")
        panel.pack(side="bottom", fill="both", padx=theme.PAD, pady=(theme.PAD_SMALL, theme.PAD))
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)
        self.log_text = tk.Text(panel, height=8, wrap="none", state=tk.DISABLED,
                                font=theme.FONT_MONO, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(panel, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.tag_configure("INFO", foreground=theme.COLOR_TEXT)
        self.log_text.tag_configure("DEBUG", foreground=theme.COLOR_MUTED)
        self.log_text.tag_configure("JOINED", foreground=theme.COLOR_CONNECTED)
        self.log_text.tag_configure("LEFT", foreground=theme.COLOR_CONNECTING)
        self.log_text.tag_configure("WARNING", foreground=theme.COLOR_CONNECTING)
        self.log_text.tag_configure("ERROR", foreground=theme.COLOR_DISCONNECTED)
        self.log_text.tag_configure("CRITICAL", foreground=theme.COLOR_DISCONNECTED)

    # ---- user actions -----------------------------------------------------------
    def _build_server_config(self) -> ServerConfig:
        """Read the control panel. Raises ValidationError for bad input."""
        try:
            port = int(self.port_var.get())
        except ValueError as exc:
            raise ValidationError("Port must be a whole number.") from exc
        config = ServerConfig(
            host=self.host_var.get().strip(),
            port=port,
            mode=TransportMode(self.mode_var.get()),
            loss_rate=self.loss_percent_var.get() / 100,
            delay_ms=self.delay_ms_var.get(),
        )
        try:
            config.validate()
        except NotImplementedError:
            pass  # TODO(Tina): remove once Nevin's ServerConfig.validate() is on main
        return config

    def _on_start(self) -> None:
        try:
            config = self._build_server_config()
        except ValidationError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return
        server = self.server_class(self.event_bus, config)
        try:
            server.start()
        except NotImplementedError:
            messagebox.showinfo(
                "Server not ready",
                "ChatServer is not implemented yet.\n"
                "Start the dashboard with --demo to try it with fake clients.",
                parent=self.root,
            )
            return
        except OSError as exc:
            messagebox.showerror("Cannot start server",
                                 f"Port {config.port} could not be opened:\n{exc}",
                                 parent=self.root)
            return
        self.server = server
        self.start_button.configure(state=tk.DISABLED)   # SERVER_STARTED enables the rest

    def _on_stop(self) -> None:
        if self.server is not None:
            self.stop_button.configure(state=tk.DISABLED)
            self.server.stop()

    def _on_apply_network(self) -> None:
        if self.server is not None:
            self.server.set_network_conditions(self.loss_percent_var.get() / 100,
                                               self.delay_ms_var.get())
            self._append_log("INFO", f"Network conditions: loss {self.loss_percent_var.get()}%,"
                                     f" delay {self.delay_ms_var.get()} ms")

    def _on_table_right_click(self, event: tk.Event[ttk.Treeview]) -> None:
        row = self.client_table.identify_row(event.y)
        if row:
            self.client_table.selection_set(row)
            self.client_menu.tk_popup(event.x_root, event.y_root)

    def _on_kick_selected(self) -> None:
        selection = self.client_table.selection()
        if self.server is None or not selection:
            return
        username = selection[0]
        if messagebox.askyesno("Kick client", f"Disconnect '{username}'?", parent=self.root):
            self.server.kick(username)

    # ---- events ------------------------------------------------------------------
    def _poll_events(self) -> None:
        """Drain self.events without blocking, then reschedule with root.after."""
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self._poll_after_id = self.root.after(GUI_POLL_INTERVAL_MS, self._poll_events)

    def _handle_event(self, event: Event) -> None:
        """Render one queued event on the Tk thread."""
        data = event.data
        if event.type == EventType.SERVER_STARTED:
            self._set_running(True)
            self._append_log("INFO", f"Server started on {data['host']}:{data['port']}"
                                     f" ({data['mode']})")
        elif event.type == EventType.SERVER_STOPPED:
            self.server = None
            self._set_running(False)
            self._show_clients([])
            self._append_log("INFO", f"Server stopped ({data['reason']})")
        elif event.type == EventType.CLIENT_JOINED:
            self._append_log("JOINED", f"{data['username']} joined from "
                                       f"{_format_address(data['address'])}")
            self._refresh_clients()
        elif event.type == EventType.CLIENT_LEFT:
            self._append_log("LEFT", f"{data['username']} left ({data['reason']})")
            self._refresh_clients()
        elif event.type == EventType.STATS_UPDATED:
            self._show_stats(data["stats"])
            self._refresh_clients()
        elif event.type == EventType.LOG:
            self._append_log(data["level"], data["message"])
        elif event.type == EventType.ERROR:
            self._append_log("ERROR", f"{data['code']}: {data['message']}")

    def _set_running(self, running: bool) -> None:
        """Enable the controls that make sense for the current server state."""
        idle = tk.DISABLED if running else tk.NORMAL
        self.start_button.configure(state=idle)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        for entry in self.config_entries:
            entry.configure(state=idle)
        for button in self.mode_buttons:
            button.configure(state=idle)
        self.status_label.configure(
            text="Running" if running else "Stopped",
            fg=theme.COLOR_CONNECTED if running else theme.COLOR_DISCONNECTED,
        )
        self._update_udp_controls()

    def _update_udp_controls(self, *_args: str) -> None:
        """Simulation controls only work in UDP mode; Apply also needs a running server."""
        is_udp = self.mode_var.get() == TransportMode.UDP.value
        for control in self.udp_controls:
            enabled = is_udp and (control is not self.apply_button or self.server is not None)
            control.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _refresh_clients(self) -> None:
        if self.server is not None:
            self._show_clients(self.server.get_clients())

    def _show_clients(self, clients: Sequence[ClientInfo]) -> None:
        """Replace the table rows, keeping the selection if that client is still there."""
        selection = self.client_table.selection()
        self.client_table.delete(*self.client_table.get_children())
        for client in sorted(clients, key=lambda c: c.username.lower()):
            self.client_table.insert("", tk.END, iid=client.username, values=(
                client.username,
                _format_address(client.address),
                _format_time(client.connected_at),
                _format_time(client.last_seen),
                client.packets_received,
                client.packets_sent,
            ))
        kept = [iid for iid in selection if self.client_table.exists(iid)]
        if kept:
            self.client_table.selection_set(kept)
        self.client_count_label.configure(text=str(len(clients)))

    def _show_stats(self, stats: dict[str, int | float]) -> None:
        for key, label in self.stat_labels.items():
            value = stats.get(key, 0)
            label.configure(text=f"{value:.1f}" if isinstance(value, float) else str(value))

    def _append_log(self, level: str, message: str) -> None:
        """Add one coloured line; keep only the last _MAX_LOG_LINES lines."""
        line = f"{datetime.now():%H:%M:%S} [{level}] {message}\n"
        tag = level if level in self.log_text.tag_names() else "INFO"
        self.log_text.configure(state=tk.NORMAL)
        try:
            self.log_text.insert(tk.END, line, tag)
            lines = int(self.log_text.index("end-1c").split(".")[0]) - 1
            if lines > _MAX_LOG_LINES:
                self.log_text.delete("1.0", f"{lines - _MAX_LOG_LINES + 1}.0")
            self.log_text.see(tk.END)
        finally:
            self.log_text.configure(state=tk.DISABLED)

    def on_close(self) -> None:
        """Stop the server cleanly, then root.destroy()."""
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.root.destroy()


class DemoServer(ChatServer):
    """Fake ChatServer for `--demo`: invents clients and traffic, no sockets.

    Same public API and same events as the real server, published from a
    background thread like real network code.
    """

    _NAMES = ("alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi")

    def __init__(self, event_bus: EventBus, config: ServerConfig | None = None) -> None:
        super().__init__(event_bus, config)
        self._fake_clients: dict[str, ClientInfo] = {}
        self._stats = TransportStats()
        self._thread: threading.Thread | None = None
        self._random = random.Random()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="demo-server", daemon=True)
        self._thread.start()
        self._publish(EventType.SERVER_STARTED, {"host": self.config.host,
                                                 "port": self.config.port,
                                                 "mode": self.config.mode.value})

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=STATS_UPDATE_INTERVAL * 2)
        with self._clients_lock:
            self._fake_clients.clear()
        self._publish(EventType.SERVER_STOPPED, {"reason": "user"})

    @property
    def is_running(self) -> bool:
        return self._thread is not None and not self._stop_event.is_set()

    def get_clients(self) -> list[ClientInfo]:
        with self._clients_lock:
            return list(self._fake_clients.values())

    def kick(self, username: str, reason: str = "kicked_by_admin") -> None:
        with self._clients_lock:
            removed = self._fake_clients.pop(username, None)
        if removed is not None:
            self._publish(EventType.CLIENT_LEFT, {"username": username, "reason": reason})

    def get_stats(self) -> dict[str, int | float]:
        return self._stats.snapshot()

    def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
        self.config.loss_rate = loss_rate
        self.config.delay_ms = delay_ms

    # ---- fake traffic -------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.wait(STATS_UPDATE_INTERVAL):
            self._tick()

    def _tick(self) -> None:
        """One second of invented activity."""
        now = time.time()
        with self._clients_lock:
            online = list(self._fake_clients)
        free = [name for name in self._NAMES if name not in online]
        roll = self._random.random()
        if free and (len(online) < 2 or roll < 0.25):
            self._join(self._random.choice(free), now)
        elif online and roll > 0.92:
            name = self._random.choice(online)
            reason = self._random.choice(("user", "timeout", "connection_lost"))
            with self._clients_lock:
                self._fake_clients.pop(name, None)
            self._publish(EventType.CLIENT_LEFT, {"username": name, "reason": reason})

        self._fake_traffic(now)
        self._publish(EventType.STATS_UPDATED, {"stats": self._stats.snapshot()})

    def _join(self, name: str, now: float) -> None:
        address = ("127.0.0.1", self._random.randint(49152, 65535))
        with self._clients_lock:
            self._fake_clients[name] = ClientInfo(name, address, now, now, 0, 0)
        self._publish(EventType.CLIENT_JOINED, {"username": name, "address": address})

    def _fake_traffic(self, now: float) -> None:
        with self._clients_lock:
            for name, info in list(self._fake_clients.items()):
                received = self._random.randint(0, 4)
                sent = received * max(1, len(self._fake_clients) - 1)
                self._fake_clients[name] = ClientInfo(
                    name, info.address, info.connected_at,
                    now if received else info.last_seen,
                    info.packets_sent + sent, info.packets_received + received,
                )
                self._stats.add(packets_received=received, packets_sent=sent,
                                bytes_received=received * 60, bytes_sent=sent * 80)
        if self.config.mode == TransportMode.UDP and self.config.loss_rate > 0:
            dropped = sum(self._random.random() < self.config.loss_rate for _ in range(10))
            self._stats.add(packets_dropped_simulated=dropped, retransmissions=dropped)
        if self._random.random() < 0.3:
            self._publish(EventType.LOG, {"level": "INFO",
                                          "message": "Relayed CHAT to everyone"})

    def _publish(self, event_type: EventType, data: dict[str, object]) -> None:
        self.event_bus.publish(Event(event_type, data, source="server"))


def _format_address(address: Sequence[object]) -> str:
    host, port = address[0], address[1]
    return f"{host}:{port}"


def _format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} server dashboard")
    parser.add_argument("--demo", action="store_true",
                        help="use fake clients instead of the real ChatServer")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = ServerApp(root, server_class=DemoServer if args.demo else ChatServer)
    app.build_ui()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

