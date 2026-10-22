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

import argparse
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from datetime import datetime
from tkinter import ttk

from socketlink.client.client import ChatClient
from socketlink.common.config import ClientConfig
from socketlink.common.constants import (
    APP_NAME,
    CONNECT_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WINDOW_SIZE,
    GUI_POLL_INTERVAL_MS,
    MAX_CHAT_LENGTH,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    MAX_WINDOW_SIZE,
    STATS_UPDATE_INTERVAL,
    ClientErrorCode,
    ConnectionState,
    DisconnectReason,
    ErrorCode,
    FileFailReason,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import InvalidStateError, ValidationError
from socketlink.common.logger import get_logger
from socketlink.common.stats import TransportStats
from socketlink.gui import theme

log = get_logger(__name__)


class ClientApp:
    def __init__(self, root: tk.Tk, event_bus: EventBus | None = None) -> None:
        self.root = root
        self.event_bus = event_bus or EventBus()
        self.events = self.event_bus.subscribe_queue()
        self._poll_after_id: str | None = None
        self.demo: DemoClient | None = None
        self.client = ChatClient(self.event_bus)
        self._connection_state = ConnectionState.DISCONNECTED
        self._send_thread: threading.Thread | None = None
        self._disconnect_thread: threading.Thread | None = None
        self._action_errors: queue.Queue[Exception] = queue.Queue()
        self._closing = False
        self._close_after_id: str | None = None

    def build_ui(self) -> None:
        """Build the panels and connect user actions to the client core."""
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

        self.config_entries: list[tk.Entry] = []
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
            entry = tk.Entry(
                self.connection_panel,
                textvariable=variable,
                font=theme.FONT_NORMAL,
                bg=theme.COLOR_PANEL,
                fg=theme.COLOR_TEXT,
                insertbackground=theme.COLOR_TEXT,
            )
            entry.grid(row=row, column=1, sticky="ew", padx=theme.PAD_SMALL,
                       pady=theme.PAD_SMALL)
            self.config_entries.append(entry)

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
            )
            button.state(["!disabled"])
            button.pack(side="left", padx=theme.PAD_SMALL)
            self.mode_buttons[mode] = button

        button_panel = tk.Frame(self.connection_panel, bg=theme.COLOR_PANEL)
        button_panel.grid(row=4, column=1, sticky="w", pady=theme.PAD_SMALL)
        self.connect_button = tk.Button(
            button_panel, text="Connect", command=self._on_connect,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            disabledforeground=theme.COLOR_MUTED,
        )
        self.connect_button.pack(side="left", padx=theme.PAD_SMALL)
        self.disconnect_button = tk.Button(
            button_panel, text="Disconnect", state=tk.DISABLED, command=self._on_disconnect,
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
        self.notice_label = tk.Label(
            self.root, text="", anchor="w", font=theme.FONT_NORMAL,
            bg=theme.COLOR_BG, fg=theme.COLOR_TEXT,
        )
        self.notice_label.pack(fill="x", padx=theme.PAD)
        self.notice_label.bind(
            "<Configure>", lambda event: self.notice_label.configure(wraplength=event.width)
        )
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=theme.PAD, pady=theme.PAD_SMALL)
        self.chat_panel = tk.LabelFrame(
            self.notebook, text="Chat", font=theme.FONT_BOLD,
            bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            padx=theme.PAD, pady=theme.PAD,
        )
        self.notebook.add(self.chat_panel, text="Chat")
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
        self.message_entry.bind("<Return>", self._on_send)
        self.send_button = tk.Button(
            self.chat_panel, text="Send", state=tk.DISABLED, command=self._on_send,
            font=theme.FONT_NORMAL, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            disabledforeground=theme.COLOR_MUTED,
        )
        self.send_button.grid(row=1, column=1, sticky="e",
                              padx=theme.PAD_SMALL, pady=theme.PAD_SMALL)
        self._build_udp_panel()
        self._build_monitor_panels()
        self._refresh_controls()
        self._poll_events()

    def _on_connect(self) -> None:
        """Validate local input; ChatClient.connect starts its own network worker."""
        if self._closing or self.demo is not None or self.connect_button["state"] == tk.DISABLED:
            return
        try:
            config = self._build_client_config()
            self.client.connect(config)
        except (ValidationError, InvalidStateError) as exc:
            self._report_action_error(exc)
            return
        self.notice_label.configure(text="")
        self._connection_state = self.client.state
        self._refresh_controls()

    def _on_disconnect(self) -> None:
        """Disconnect outside Tk: BYE and transport shutdown may block."""
        if self.demo is not None:
            return
        if self._disconnect_thread is None or not self._disconnect_thread.is_alive():
            self._disconnect_thread = threading.Thread(
                target=self._run_client_action, args=(self.client.disconnect,),
                name="gui-client-disconnect", daemon=True,
            )
            self._disconnect_thread.start()
        self._refresh_controls()

    def _on_send(self, _event: tk.Event | None = None) -> str:
        """Capture the draft and recipient on Tk, then send in a worker thread."""
        if self.send_button["state"] == tk.DISABLED or self._closing or self.demo is not None:
            return "break"
        text = self.message_var.get()
        if not text.strip() or len(text) > MAX_CHAT_LENGTH:
            self._report_action_error(ValidationError(
                f"Enter a non-empty message of at most {MAX_CHAT_LENGTH} characters."
            ))
            return "break"
        selection = self.user_list.curselection()
        # Row zero represents broadcast; a real user named Everyone remains selectable.
        recipient = self.user_list.get(selection[0]) if selection and selection[0] else None
        self._send_thread = threading.Thread(
            target=self._run_client_action,
            args=(lambda: self.client.send_chat(text, recipient),),
            name="gui-client-send", daemon=True,
        )
        self._send_thread.start()
        self._refresh_controls()
        return "break"

    def _run_client_action(self, action: Callable[[], None]) -> None:
        """Workers never touch Tk; local exceptions return through a private queue."""
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - keep worker failures visible on the GUI
            log.exception("Client GUI action failed")
            self._action_errors.put(exc)

    def _report_action_error(self, exc: Exception) -> None:
        """Show a local action failure without introducing new event error codes."""
        if isinstance(exc, ValidationError):
            message = str(exc)
        elif isinstance(exc, InvalidStateError):
            message = self._error_message(ClientErrorCode.INVALID_STATE)
        else:
            message = self._error_message(ErrorCode.INTERNAL_ERROR)
        self.notice_label.configure(text=message, fg=theme.COLOR_DISCONNECTED)
        self._append_log("ERROR", message, time.time())

    def _refresh_controls(self) -> None:
        """Enable only actions valid for the last connection state and active workers."""
        sending = self._send_thread is not None and self._send_thread.is_alive()
        stopping = self._disconnect_thread is not None and self._disconnect_thread.is_alive()
        real = self.demo is None and not self._closing
        idle = self._connection_state == ConnectionState.DISCONNECTED
        connected = self._connection_state == ConnectionState.CONNECTED
        self.connect_button.configure(state=tk.NORMAL if real and idle
                                      and not sending and not stopping else tk.DISABLED)
        self.disconnect_button.configure(state=tk.NORMAL if real and not stopping
                                         and self._connection_state in (
                                             ConnectionState.CONNECTING, ConnectionState.CONNECTED,
                                             ConnectionState.RECONNECTING,
                                         ) else tk.DISABLED)
        self.send_button.configure(state=tk.NORMAL if real and connected
                                   and not sending and not stopping else tk.DISABLED)
        self.message_entry.configure(state=tk.NORMAL if real and connected
                                     and not stopping else tk.DISABLED)
        for entry in self.config_entries:
            entry.configure(state=tk.NORMAL if real and idle else tk.DISABLED)
        for button in self.mode_buttons.values():
            button.state(["!disabled"] if real and idle else ["disabled"])
        self._update_udp_controls()

    def _build_monitor_panels(self) -> None:
        """Build event-driven statistics and a bounded, read-only live log."""
        self.stats_panel = tk.Frame(self.notebook, bg=theme.COLOR_PANEL)
        self.notebook.add(self.stats_panel, text="Statistics")
        self.stat_labels: dict[str, tk.Label] = {}
        rows = (
            ("packets_sent", "Packets sent"), ("packets_received", "Packets received"),
            ("bytes_sent", "Bytes sent"), ("bytes_received", "Bytes received"),
            ("retransmissions", "Retransmissions"),
            ("packets_dropped_simulated", "Simulated drops"),
            ("duplicates_received", "Duplicates received"),
            ("checksum_errors", "Checksum errors"), ("avg_rtt_ms", "Average RTT (ms)"),
        )
        for index, (key, title) in enumerate(rows):
            row, group = divmod(index, 3)
            column = group * 2
            tk.Label(
                self.stats_panel, text=title, font=theme.FONT_NORMAL,
                bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            ).grid(row=row, column=column, sticky="w", padx=theme.PAD, pady=theme.PAD_SMALL)
            label = tk.Label(
                self.stats_panel, text="—", font=theme.FONT_BOLD,
                bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
            )
            label.grid(row=row, column=column + 1, sticky="e", padx=theme.PAD)
            self.stat_labels[key] = label
            self.stats_panel.columnconfigure(column, weight=1)

        self.log_panel = tk.Frame(self.notebook, bg=theme.COLOR_PANEL)
        self.notebook.add(self.log_panel, text="Live log")
        self.log_panel.columnconfigure(0, weight=1)
        self.log_panel.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_panel, height=5, width=40, wrap="word", state=tk.DISABLED,
            font=theme.FONT_MONO, bg=theme.COLOR_PANEL, fg=theme.COLOR_TEXT,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(self.log_panel, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        colors = {
            "INFO": theme.COLOR_TEXT, "DEBUG": theme.COLOR_MUTED,
            "JOINED": theme.COLOR_CONNECTED, "LEFT": theme.COLOR_CONNECTING,
            "WARNING": theme.COLOR_CONNECTING, "ERROR": theme.COLOR_DISCONNECTED,
            "CRITICAL": theme.COLOR_DISCONNECTED,
            "SENT": theme.COLOR_PKT_SENT, "RECEIVED": theme.COLOR_PKT_RECEIVED,
            "DROPPED": theme.COLOR_PKT_DROPPED,
            "RETRANSMITTED": theme.COLOR_PKT_RETRANSMITTED,
        }
        for tag, color in colors.items():
            self.log_text.tag_configure(tag, foreground=color)

    def _append_log(self, level: str, message: str, timestamp: float) -> None:
        """Keep the latest 500 physical lines, including multiline event messages."""
        level = str(level).upper()
        tag = level if level in self.log_text.tag_names() else "INFO"
        clock = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        try:
            for line in str(message).splitlines() or [""]:
                self.log_text.insert(tk.END, f"{clock} [{tag}] {line}\n", tag)
            lines = int(self.log_text.index("end-1c").split(".")[0]) - 1
            if lines > 500:
                self.log_text.delete("1.0", f"{lines - 500 + 1}.0")
            self.log_text.see(tk.END)
        finally:
            self.log_text.configure(state=tk.DISABLED)

    def _show_notice(self, message: str, level: str, event: Event) -> None:
        """Keep user-facing diagnostics visible even when the log tab is hidden."""
        color = theme.COLOR_DISCONNECTED if level == "ERROR" else theme.COLOR_CONNECTING
        self.notice_label.configure(text=message, fg=color)
        self._append_log(level, message, event.timestamp)

    @staticmethod
    def _disconnect_message(reason: object) -> str:
        """Translate existing enum values without inventing new reason codes."""
        messages = {
            DisconnectReason.USER: "You left",
            DisconnectReason.SERVER_SHUTDOWN: "You were disconnected (server shutdown)",
            DisconnectReason.KICKED_BY_ADMIN: "You were kicked by the admin",
            DisconnectReason.TIMEOUT: "Your connection timed out (no traffic)",
            DisconnectReason.CONNECTION_LOST: "You lost the connection",
            DisconnectReason.REJECTED: "Your connection was rejected",
            DisconnectReason.CONNECT_FAILED: "Could not connect to the server",
            DisconnectReason.INTERNAL_ERROR: "You left after an internal error",
        }
        return messages.get(getattr(reason, "value", reason), "Connection ended")

    @staticmethod
    def _error_message(code: object) -> str:
        """Resolve client codes first, then protocol codes; hide unknown details."""
        value = getattr(code, "value", code)
        try:
            known = ClientErrorCode(value)
        except (ValueError, TypeError):
            try:
                known = ErrorCode(value)
            except (ValueError, TypeError):
                return "An unexpected error occurred"
        messages = {
            ClientErrorCode.CONNECTION_REFUSED: "The server refused the connection",
            ClientErrorCode.CONNECT_TIMEOUT: "The connection attempt timed out",
            ClientErrorCode.CONNECTION_LOST: "You lost the connection",
            ClientErrorCode.PROTOCOL_ERROR: "Received invalid data from the server",
            ClientErrorCode.INVALID_STATE: "This action is unavailable in the current state",
            ErrorCode.BAD_CHECKSUM: "Data integrity check failed",
            ErrorCode.MALFORMED_PACKET: "Received a malformed packet",
            ErrorCode.VERSION_MISMATCH: "Protocol versions do not match",
            ErrorCode.NOT_AUTHENTICATED: "Connect to the server first",
            ErrorCode.INVALID_USERNAME: "Invalid username",
            ErrorCode.USERNAME_TAKEN: "This username is already in use",
            ErrorCode.UNKNOWN_USER: "The recipient is not connected",
            ErrorCode.PAYLOAD_TOO_LARGE: "The data exceeds the size limit",
            ErrorCode.SERVER_FULL: "The server is full",
            ErrorCode.FILE_REJECTED: "The file was rejected",
            ErrorCode.INTERNAL_ERROR: "An unexpected server error occurred",
        }
        return messages[known]

    @staticmethod
    def _file_failure_message(reason: object) -> str:
        """Describe file failures without starting a transfer or adding file controls."""
        messages = {
            FileFailReason.INVALID_FILE: "Invalid file",
            FileFailReason.READ_ERROR: "Could not read the file",
            FileFailReason.SEND_ERROR: "Could not send the file",
            FileFailReason.CANCELLED: "File transfer cancelled",
            FileFailReason.FILE_TOO_LARGE: "The file exceeds the size limit",
            FileFailReason.BAD_PACKET: "Invalid file transfer packet",
            FileFailReason.BAD_CHUNK: "Invalid file chunk",
            FileFailReason.TRANSFER_ID_CONFLICT: "File transfer ID conflict",
            FileFailReason.MISSING_CHUNKS: "File chunks are missing",
            FileFailReason.CHECKSUM_MISMATCH: "File integrity check failed",
            FileFailReason.WRITE_ERROR: "Could not save the file",
            FileFailReason.CONNECTION_LOST: "Connection lost during file transfer",
        }
        return messages.get(getattr(reason, "value", reason), "File transfer failed")

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
        self.udp_panel.pack(fill="x", before=self.notebook,
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
        """Simulation settings are captured on connect; lock them during a session."""
        enabled = (self.mode_var.get() == TransportMode.UDP.value and not self._closing
                   and (self.demo is not None
                        or self._connection_state == ConnectionState.DISCONNECTED))
        state = tk.NORMAL if enabled else tk.DISABLED
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
            raise ValidationError(
                f"Packet loss must be between 0 and {MAX_SIMULATED_LOSS * 100:g}%."
            )
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
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(event)
            except Exception:  # noqa: BLE001 - one bad event must not stop queue polling
                log.exception("Could not show %s event", event.type.value)
        while True:
            try:
                exc = self._action_errors.get_nowait()
            except queue.Empty:
                break
            self._report_action_error(exc)
        self._refresh_controls()
        self._poll_after_id = self.root.after(GUI_POLL_INTERVAL_MS, self._poll_events)

    def _handle_event(self, event: Event) -> None:
        """Render queued chat, user-list and connection events on the Tk thread."""
        data = event.data
        if event.type == EventType.MESSAGE_SENT:
            # Acceptance is not delivery: only the server echo is added to history.
            if self.message_var.get() == data["text"]:
                self.message_var.set("")
            return
        if event.type == EventType.STATS_UPDATED:
            for key, label in self.stat_labels.items():
                value = data["stats"].get(key)
                label.configure(text=(f"{value:.1f}" if key == "avg_rtt_ms"
                                      and isinstance(value, (int, float))
                                      else str(value) if value is not None else "—"))
            return
        if event.type == EventType.LOG:
            self._append_log(data["level"], data["message"], event.timestamp)
            return
        packet_tags = {
            EventType.PACKET_SENT: "SENT", EventType.PACKET_RECEIVED: "RECEIVED",
            EventType.PACKET_DROPPED: "DROPPED",
            EventType.PACKET_RETRANSMITTED: "RETRANSMITTED",
        }
        if event.type in packet_tags:
            description = str(data["summary"])
            if event.type == EventType.PACKET_RETRANSMITTED:
                description += f" (attempt {data['attempt']})"
            self._append_log(packet_tags[event.type], description, event.timestamp)
            return
        if event.type == EventType.PACKET_CORRUPTED:
            description = {"checksum": "Packet integrity check failed",
                           "malformed": "Received a malformed packet"}.get(
                               data["reason"], "Received an invalid packet")
            self._append_log("ERROR", description, event.timestamp)
            return
        if event.type == EventType.ERROR:
            self._show_notice(self._error_message(data["code"]), "ERROR", event)
            return
        if event.type == EventType.FILE_FAILED:
            self._show_notice(self._file_failure_message(data["reason"]), "ERROR", event)
            return
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
            selected = self.user_list.get(selection[0]) if selection and selection[0] else None
            users = ["Everyone", *event.data["users"]]
            self.user_list.delete(0, tk.END)
            self.user_list.insert(tk.END, *users)
            kept = users[1:].index(selected) + 1 if selected in users[1:] else 0
            self.user_list.selection_set(kept)
            return
        if event.type == EventType.STATE_CHANGED:
            state = ConnectionState(event.data["new"])
        elif event.type == EventType.CONNECTED:
            state = ConnectionState.CONNECTED
            self.notice_label.configure(text="")
        elif event.type == EventType.DISCONNECTED:
            state = ConnectionState.DISCONNECTED
            message = self._disconnect_message(data["reason"])
            if data["reason"] in (DisconnectReason.REJECTED, DisconnectReason.CONNECT_FAILED):
                detail = self.notice_label["text"]
                if detail:
                    message += f": {detail}"
            self._show_notice(message, "WARNING", event)
            self.user_list.delete(0, tk.END)
            self.user_list.insert(tk.END, "Everyone")
            self.user_list.selection_set(0)
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
        self._connection_state = state
        self._refresh_controls()

    def on_close(self) -> None:
        """Keep Tk responsive while the client cancels or closes its connection."""
        if self._closing:
            return
        self._closing = True
        if self.demo is not None:
            self.demo.stop()
        else:
            self._on_disconnect()
        self._refresh_controls()
        self._close_when_disconnected(time.monotonic() + CONNECT_TIMEOUT)

    def _close_when_disconnected(self, deadline: float) -> None:
        """Wait without joining on Tk; core daemon workers own their transport cleanup."""
        workers = (self._send_thread, self._disconnect_thread)
        waiting = (self.client.state != ConnectionState.DISCONNECTED
                   or any(worker is not None and worker.is_alive() for worker in workers))
        if waiting and time.monotonic() < deadline:
            self._close_after_id = self.root.after(
                GUI_POLL_INTERVAL_MS, self._close_when_disconnected, deadline,
            )
            return
        if waiting:
            log.warning("GUI closed while client shutdown is still finishing")
        self._close_after_id = None
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self.event_bus.unsubscribe(None, self.events.put)
        self.root.destroy()


class DemoClient:
    """Publish invented traffic through EventBus; never open a socket.

    Short ticks run on the Tk thread and only publish events. ClientApp renders
    them through its existing queue. stop() cancels the pending tick on close.
    """

    def __init__(self, root: tk.Tk, event_bus: EventBus, config: ClientConfig) -> None:
        self.root = root
        self.event_bus = event_bus
        self.config = config
        self._after_id: str | None = None
        self._running = False
        self._sequence = 0
        self._stats = TransportStats()

    def start(self) -> None:
        """Start one clearly identified, server-free demonstration session."""
        if self._running:
            return
        self._running = True
        self._publish(EventType.STATE_CHANGED, {
            "old": ConnectionState.DISCONNECTED.value,
            "new": ConnectionState.CONNECTING.value,
        })
        self._publish(EventType.STATE_CHANGED, {
            "old": ConnectionState.CONNECTING.value,
            "new": ConnectionState.CONNECTED.value,
        })
        self._publish(EventType.CONNECTED, {
            "host": self.config.host, "port": self.config.port,
            "mode": self.config.mode.value, "username": self.config.username, "client_id": 1,
        })
        self._publish(EventType.USER_LIST_UPDATED, {
            "users": ["alice", "bob", self.config.username],
        })
        self._publish(EventType.LOG, {
            "level": "INFO", "message": "DEMO: invented traffic; no server connection.",
        })
        self._tick()

    def _tick(self) -> None:
        """Emit one small batch with the real event payload keys."""
        if not self._running:
            return
        self._sequence += 1
        sender = "alice" if self._sequence % 2 else "bob"
        text = f"Demo message {self._sequence} from {sender}"
        summary = f"DEMO CHAT seq={self._sequence}"
        self._publish(EventType.PACKET_SENT, {"summary": summary})
        if self.config.mode == TransportMode.UDP and self._sequence % 3 == 0:
            self._publish(EventType.PACKET_DROPPED, {"summary": summary})
            self._publish(EventType.PACKET_RETRANSMITTED, {"summary": summary, "attempt": 1})
            self._stats.add(packets_dropped_simulated=1, retransmissions=1)
        self._publish(EventType.PACKET_RECEIVED, {"summary": summary})
        self._publish(EventType.MESSAGE_RECEIVED, {
            "from": sender, "to": None, "text": text, "timestamp": time.time(),
        })
        size = len(text.encode("utf-8"))
        self._stats.add(packets_sent=1, packets_received=1, bytes_sent=size, bytes_received=size)
        self._publish(EventType.STATS_UPDATED, {"stats": self._stats.snapshot()})
        self._publish(EventType.LOG, {
            "level": "DEBUG", "message": f"DEMO: delivered message {self._sequence}",
        })
        self._after_id = self.root.after(int(STATS_UPDATE_INTERVAL * 1000), self._tick)

    def stop(self) -> None:
        """Cancel future demo events before the Tk window is destroyed."""
        if not self._running:
            return
        self._running = False
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._publish(EventType.DISCONNECTED, {"reason": DisconnectReason.USER.value})

    def _publish(self, event_type: EventType, data: dict[str, object]) -> None:
        self.event_bus.publish(Event(event_type, data, source="client"))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} client GUI")
    parser.add_argument("--demo", action="store_true",
                        help="show invented client traffic without connecting to a server")
    args = parser.parse_args(argv)
    root = tk.Tk()
    app = ClientApp(root)
    app.build_ui()
    if args.demo:
        root.title(f"{APP_NAME} - Client (DEMO)")
        app.username_var.set("demo_client")
        app.mode_var.set(TransportMode.UDP.value)
        app.demo = DemoClient(root, app.event_bus, app._build_client_config())
        app.demo.start()
        app._refresh_controls()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
