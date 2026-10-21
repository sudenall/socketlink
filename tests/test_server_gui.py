"""Tests for gui/server_gui.py: the demo server, the dashboard's event handling and the
dashboard driving the real ChatServer.

OWNER: Tina

Window tests need a display; they are skipped where Tk cannot start (e.g. headless Linux CI).
Message boxes are replaced so no test ever waits for a click.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable, Iterator

import pytest

tk = pytest.importorskip("tkinter")

from socketlink.common.config import ServerConfig  # noqa: E402
from socketlink.common.constants import (  # noqa: E402
    CONNECT_TIMEOUT,
    DisconnectReason,
    MessageType,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType  # noqa: E402
from socketlink.common.exceptions import ValidationError  # noqa: E402
from socketlink.common.protocol import make_hello  # noqa: E402
from socketlink.common.transport import TcpTransport  # noqa: E402
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


def _wait_for(app: ServerApp, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Pump events and Tk callbacks until `condition()` is true (work done in threads)."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached in time"
        _pump(app)
        app.root.update()
        time.sleep(0.02)


def _close(app: ServerApp) -> None:
    """Call on_close and run Tk until the window is really destroyed."""
    app.on_close()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            app.root.winfo_exists()   # raises once the window is destroyed
        except tk.TclError:
            return
        app.root.update()
        time.sleep(0.02)
    raise AssertionError("window was not closed")


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
    _wait_for(app, lambda: app.status_label.cget("text") == "Stopped")
    assert app.client_table.get_children() == ()
    assert app.server is None
    assert dialogs == []


def test_stop_runs_in_a_worker_thread(root: tk.Tk, dialogs: list[str]) -> None:
    class SlowStopServer(DemoServer):
        def stop(self) -> None:
            time.sleep(0.5)
            super().stop()

    app = _app(root, server_class=SlowStopServer)
    app._on_start()
    _pump(app)
    started = time.monotonic()
    app._on_stop()
    assert time.monotonic() - started < 0.3    # the window did not wait for stop()
    assert app.status_label.cget("text") == "Stopping..."
    _wait_for(app, lambda: app.status_label.cget("text") == "Stopped")


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
    assert f"{name} was kicked by the admin" in _log_text(app)
    _close(app)


@pytest.mark.parametrize(("reason", "text"), [
    (DisconnectReason.USER.value, "left"),
    (DisconnectReason.TIMEOUT.value, "timed out (no traffic)"),
    (DisconnectReason.CONNECTION_LOST.value, "lost the connection"),
    ("something_new", "left (something_new)"),
])
def test_left_text(reason: str, text: str) -> None:
    assert server_gui._left_text(reason) == text


def test_every_disconnect_reason_has_a_text() -> None:
    assert set(server_gui._LEFT_TEXT) == set(DisconnectReason)


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
    _close(app)


def test_rejected_network_conditions_show_error(root: tk.Tk, dialogs: list[str]) -> None:
    class StrictServer(DemoServer):
        def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
            raise ValidationError("loss_rate must be between 0 and 0.5.")

    app = _app(root, server_class=StrictServer)
    app.mode_var.set(TransportMode.UDP.value)
    app._on_start()
    _pump(app)
    app._on_apply_network()
    assert dialogs == ["error"]
    assert "Network conditions" not in _log_text(app)
    _close(app)


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


def test_failing_event_does_not_stop_polling(root: tk.Tk,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(root)
    handled: list[EventType] = []

    def handle(event: Event) -> None:
        if event.type == EventType.ERROR:
            raise KeyError("unknown code")
        handled.append(event.type)

    monkeypatch.setattr(app, "_handle_event", handle)
    app.event_bus.publish(Event(EventType.ERROR, {"code": "NEW_CODE", "message": "x"}))
    app.event_bus.publish(Event(EventType.LOG, {"level": "INFO", "message": "after"}))
    app._poll_events()
    assert handled == [EventType.LOG]
    assert app._poll_after_id is not None
    _close(app)


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
    _close(app)
    assert server is not None and not server.is_running


# ---- real ChatServer ----------------------------------------------------------------
@pytest.mark.integration
def test_real_server_start_join_kick_and_stop(root: tk.Tk, dialogs: list[str]) -> None:
    app = _app(root, server_class=ChatServer)
    ports: list[int] = []
    app.event_bus.subscribe(EventType.SERVER_STARTED, lambda e: ports.append(e.data["port"]))
    app.host_var.set("127.0.0.1")
    app.port_var.set("0")   # the OS picks a free port (D-15)
    app._on_start()
    try:
        _wait_for(app, lambda: app.status_label.cget("text") == "Running")
        client = TcpTransport.connect("127.0.0.1", ports[0])
        try:
            client.send(make_hello("alice"))
            assert client.receive(timeout=CONNECT_TIMEOUT).type == MessageType.WELCOME
            _wait_for(app, lambda: "alice" in app.client_table.get_children())
            assert app.client_count_label.cget("text") == "1"

            app.client_table.selection_set("alice")
            app._on_kick_selected()
            _wait_for(app, lambda: "alice was kicked by the admin" in _log_text(app))
            assert "alice" not in app.client_table.get_children()
        finally:
            client.close()

        app._on_stop()
        _wait_for(app, lambda: app.status_label.cget("text") == "Stopped")
        assert app.server is None
        assert dialogs == ["ask"]
    finally:
        if app.server is not None:
            app.server.stop()
