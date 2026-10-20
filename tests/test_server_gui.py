"""Tests for gui/server_gui.py: the demo server and the dashboard's event handling.

OWNER: Tina

Window tests need a display; they are skipped where Tk cannot start (e.g. headless Linux CI).
Message boxes are replaced so no test ever waits for a click.
"""

from __future__ import annotations

import queue
from collections.abc import Iterator

import pytest

tk = pytest.importorskip("tkinter")

from socketlink.common.config import ServerConfig  # noqa: E402
from socketlink.common.constants import DisconnectReason, TransportMode  # noqa: E402
from socketlink.common.events import Event, EventBus, EventType  # noqa: E402
from socketlink.gui import server_gui  # noqa: E402
from socketlink.gui.server_gui import DemoServer, ServerApp  # noqa: E402
from socketlink.server.server import ChatServer, ClientInfo  # noqa: E402


def _drain(q: queue.Queue[Event]) -> list[Event]:
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


# ---- DemoServer (no window needed) ----------------------------------------------------
def test_demo_server_events_follow_the_contract() -> None:
    bus = EventBus()
    q = bus.subscribe_queue()
    server = DemoServer(bus, ServerConfig(mode=TransportMode.UDP, loss_rate=0.3))
    server.start()
    for _ in range(30):
        server._tick()
    for name in [c.username for c in server.get_clients()]:
        server.kick(name)
    server.stop()
    server.stop()   # second call is a no-op

    events = _drain(q)
    for event in events:
        event.validate()
    types = [e.type for e in events]
    assert types[0] == EventType.SERVER_STARTED
    assert types[-1] == EventType.SERVER_STOPPED
    assert types.count(EventType.SERVER_STOPPED) == 1
    assert EventType.CLIENT_JOINED in types and EventType.STATS_UPDATED in types
    assert server.get_clients() == []
    assert not server.is_running


def test_demo_server_kick_removes_client() -> None:
    bus = EventBus()
    q = bus.subscribe_queue()
    server = DemoServer(bus)
    server._tick()
    name = server.get_clients()[0].username
    _drain(q)

    server.kick(name)
    server.kick(name)   # unknown now: nothing happens
    assert name not in [c.username for c in server.get_clients()]
    assert [e.data for e in _drain(q)] == [
        {"username": name, "reason": DisconnectReason.KICKED_BY_ADMIN.value}]


# ---- window ----------------------------------------------------------------------
@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk cannot start here: {exc}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass   # on_close already destroyed it


@pytest.fixture
def dialogs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record message boxes instead of showing them; askyesno answers yes."""
    shown: list[str] = []

    def record(kind: str, answer: bool | None = None):  # noqa: ANN202
        def show(title: str, message: str, **_: object) -> bool | None:
            shown.append(kind)
            return answer
        return show

    monkeypatch.setattr(server_gui.messagebox, "showerror", record("error"))
    monkeypatch.setattr(server_gui.messagebox, "showinfo", record("info"))
    monkeypatch.setattr(server_gui.messagebox, "askyesno", record("ask", True))
    return shown


def _app(root: tk.Tk, server_class: type[ChatServer] = DemoServer) -> ServerApp:
    app = ServerApp(root, EventBus(), server_class=server_class)
    app.build_ui()
    return app


def _pump(app: ServerApp) -> None:
    """Handle every queued event now (what root.after polling does every 50 ms)."""
    for event in _drain(app.events):
        app._handle_event(event)


def _log_text(app: ServerApp) -> str:
    return app.log_text.get("1.0", tk.END)


def test_initial_state_is_stopped(root: tk.Tk) -> None:
    app = _app(root)
    assert app.status_label.cget("text") == "Stopped"
    assert app.start_button.cget("state") == tk.NORMAL
    assert app.stop_button.cget("state") == tk.DISABLED
    assert app.apply_button.cget("state") == tk.DISABLED   # TCP is the default


def test_demo_start_fill_table_and_stop(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root)
    app._on_start()
    _pump(app)
    assert app.status_label.cget("text") == "Running"
    assert app.start_button.cget("state") == tk.DISABLED
    assert app.stop_button.cget("state") == tk.NORMAL

    assert isinstance(app.server, DemoServer)
    app.server._tick()
    app.server._tick()
    _pump(app)
    rows = app.client_table.get_children()
    assert len(rows) >= 2
    assert app.client_count_label.cget("text") == str(len(rows))
    assert "joined from 127.0.0.1:" in _log_text(app)

    app._on_stop()
    _pump(app)
    assert app.status_label.cget("text") == "Stopped"
    assert app.client_table.get_children() == ()
    assert app.server is None
    assert dialogs == []


def test_kick_selected_client(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root)
    app._on_start()
    app.server._tick()
    _pump(app)
    name = app.client_table.get_children()[0]

    app.client_table.selection_set(name)
    app._on_kick_selected()
    _pump(app)
    assert dialogs == ["ask"]
    assert name not in app.client_table.get_children()
    assert f"{name} left ({DisconnectReason.KICKED_BY_ADMIN.value})" in _log_text(app)
    app.on_close()


def test_server_not_ready_shows_info(root: tk.Tk, dialogs: list[str]) -> None:
    class NotReadyServer(DemoServer):
        def start(self) -> None:
            raise NotImplementedError("not ready")

    app = _app(root, server_class=NotReadyServer)
    app._on_start()
    assert dialogs == ["info"]
    assert app.server is None
    assert app.start_button.cget("state") == tk.NORMAL


def test_bad_port_shows_error(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root)
    app.port_var.set("abc")
    app._on_start()
    assert dialogs == ["error"]
    assert app.server is None


def test_port_busy_shows_error(root: tk.Tk, dialogs: list[str]) -> None:
    class BusyServer(DemoServer):
        def start(self) -> None:
            raise OSError("address already in use")

    app = _app(root, server_class=BusyServer)
    app._on_start()
    assert dialogs == ["error"]
    assert app.server is None


def test_udp_mode_enables_apply_only_while_running(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root)
    app.mode_var.set(TransportMode.UDP.value)
    assert app.udp_controls[0].cget("state") == tk.NORMAL
    assert app.apply_button.cget("state") == tk.DISABLED
    app._on_start()
    _pump(app)
    assert app.apply_button.cget("state") == tk.NORMAL

    app.loss_percent_var.set(20)
    app.delay_ms_var.set(150)
    app._on_apply_network()
    assert app.server.config.loss_rate == pytest.approx(0.2)
    assert app.server.config.delay_ms == 150
    app.on_close()


def test_log_error_and_stats_events_are_shown(root: tk.Tk) -> None:
    app = _app(root)
    app.event_bus.publish(Event(EventType.LOG, {"level": "WARNING", "message": "careful"}))
    app.event_bus.publish(Event(EventType.ERROR, {"code": "USERNAME_TAKEN", "message": "dup"}))
    app.event_bus.publish(Event(EventType.STATS_UPDATED, {"stats": {
        "packets_sent": 12, "avg_rtt_ms": 3.25}}))
    _pump(app)
    log = _log_text(app)
    assert "[WARNING] careful" in log and "[ERROR] USERNAME_TAKEN: dup" in log
    assert app.stat_labels["packets_sent"].cget("text") == "12"
    assert app.stat_labels["avg_rtt_ms"].cget("text") == "3.2"
    assert app.stat_labels["retransmissions"].cget("text") == "0"


def test_log_keeps_only_last_lines(root: tk.Tk) -> None:
    app = _app(root)
    for number in range(server_gui._MAX_LOG_LINES + 50):
        app._append_log("INFO", f"line {number}")
    lines = _log_text(app).strip().splitlines()
    assert len(lines) == server_gui._MAX_LOG_LINES
    assert lines[-1].endswith(f"line {server_gui._MAX_LOG_LINES + 49}")


def test_show_clients_keeps_selection(root: tk.Tk) -> None:
    app = _app(root)
    clients = [ClientInfo("bob", ("127.0.0.1", 50001), 0.0, 0.0, 1, 2),
               ClientInfo("alice", ("127.0.0.1", 50002), 0.0, 0.0, 3, 4)]
    app._show_clients(clients)
    assert app.client_table.get_children() == ("alice", "bob")
    app.client_table.selection_set("bob")
    app._show_clients(clients)
    assert app.client_table.selection() == ("bob",)
    assert app.client_table.item("alice")["values"][4:] == [4, 3]   # packets in, out


def test_on_close_stops_running_server(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root)
    app._on_start()
    server = app.server
    app.on_close()
    assert server is not None and not server.is_running
