"""Client GUI integration and responsiveness checks.

OWNER: İlayda
GUI cases skip when Tk cannot open a display; sockets always use localhost port 0.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator

import pytest

tk = pytest.importorskip("tkinter")

from socketlink.client.client import ChatClient  # noqa: E402
from socketlink.common.config import ClientConfig  # noqa: E402
from socketlink.common.constants import (  # noqa: E402
    ConnectionState,
    DisconnectReason,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType  # noqa: E402
from socketlink.common.exceptions import ValidationError  # noqa: E402
from socketlink.common.transport import TcpListener  # noqa: E402
from socketlink.gui.client_gui import ClientApp, DemoClient  # noqa: E402


def _exists(root: tk.Tk) -> bool:
    try:
        return bool(root.winfo_exists())
    except tk.TclError:
        return False


def _wait(app: ClientApp, condition: Callable[[], bool], timeout: float = 8.0) -> None:
    """Use the real Tk mainloop rather than nested update() calls on macOS."""
    if condition():
        return
    deadline = time.monotonic() + timeout
    timed_out = False

    def check() -> None:
        nonlocal timed_out
        if condition():
            app.root.quit()
        elif time.monotonic() >= deadline:
            timed_out = True
            app.root.quit()
        else:
            app.root.after(10, check)

    app.root.after(10, check)
    app.root.mainloop()
    assert not timed_out and condition(), "GUI condition was not reached"


@pytest.fixture
def app() -> Iterator[ClientApp]:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk cannot start here: {exc}")
    root.withdraw()
    callback_errors: list[BaseException] = []
    root.report_callback_exception = lambda _kind, error, _tb: callback_errors.append(error)
    window = ClientApp(root)
    window.build_ui()
    yield window
    if _exists(root):
        window.on_close()
        _wait(window, lambda: not _exists(root))
    assert not callback_errors


def _configure(app: ClientApp, host: str, port: int, mode: TransportMode,
               username: str = "ilayda") -> None:
    app.host_var.set(host)
    app.port_var.set(str(port))
    app.mode_var.set(mode.value)
    app.username_var.set(username)


def test_initial_controls_and_invalid_input(app: ClientApp) -> None:
    assert app.connect_button["state"] == tk.NORMAL
    assert app.disconnect_button["state"] == app.send_button["state"] == tk.DISABLED
    app.port_var.set("not-a-port")
    app.connect_button.invoke()
    assert "whole number" in app.notice_label["text"]
    app.port_var.set("5050")
    app.connect_button.invoke()
    assert "username" in app.notice_label["text"].lower()
    assert app.client.state == ConnectionState.DISCONNECTED


@pytest.mark.integration
@pytest.mark.parametrize("running_server", [TransportMode.TCP, TransportMode.UDP], indirect=True)
def test_real_connect_broadcast_private_message_and_disconnect(app: ClientApp,
                                                              running_server) -> None:
    server = running_server
    # Everyone is also a valid username; only row zero must mean broadcast.
    peer_bus = EventBus()
    peer_events: list[Event] = []
    peer_bus.subscribe(None, peer_events.append)
    peer = ChatClient(peer_bus, ClientConfig(
        host=server.host, port=server.port, mode=server.mode, username="Everyone",
        auto_reconnect=False,
    ))
    peer.connect()
    try:
        _wait(app, lambda: peer.state == ConnectionState.CONNECTED)
        _configure(app, server.host, server.port, server.mode)
        app.connect_button.invoke()
        assert app.connect_button["state"] == tk.DISABLED
        _wait(app, lambda: app.status_label["text"] == "Connected"
              and len(app.user_list.get(0, tk.END)) >= 3)
        assert app.send_button["state"] == app.disconnect_button["state"] == tk.NORMAL
        assert all(entry["state"] == tk.DISABLED for entry in app.config_entries)

        app.message_var.set("broadcast from GUI")
        app.send_button.invoke()
        _wait(app, lambda: "broadcast from GUI" in app.message_history.get("1.0", "end-1c"))
        history = app.message_history.get("1.0", "end-1c")
        assert history.count("broadcast from GUI") == 1
        assert app.message_var.get() == ""

        users = app.user_list.get(0, tk.END)
        app.user_list.selection_clear(0, tk.END)
        app.user_list.selection_set(users[1:].index("Everyone") + 1)
        app.message_var.set("private from GUI")
        _wait(app, lambda: app.send_button["state"] == tk.NORMAL)
        app.send_button.invoke()
        _wait(app, lambda: any(e.type == EventType.MESSAGE_RECEIVED
                              and e.data["text"] == "private from GUI" for e in peer_events))
        received = next(e for e in peer_events if e.type == EventType.MESSAGE_RECEIVED
                        and e.data["text"] == "private from GUI")
        assert received.data["to"] == "Everyone"
        app.disconnect_button.invoke()
        _wait(app, lambda: app.status_label["text"] == "Disconnected"
              and app.connect_button["state"] == tk.NORMAL)
        assert app.send_button["state"] == tk.DISABLED
        assert app.user_list.get(0, tk.END) == ("Everyone",)
    finally:
        peer.disconnect()


@pytest.mark.integration
def test_rejected_username_keeps_error_detail(app: ClientApp, running_server) -> None:
    server = running_server
    peer = ChatClient(EventBus(), ClientConfig(
        host=server.host, port=server.port, username="taken", auto_reconnect=False,
    ))
    peer.connect()
    try:
        _wait(app, lambda: peer.state == ConnectionState.CONNECTED)
        _configure(app, server.host, server.port, server.mode, "taken")
        app.connect_button.invoke()
        _wait(app, lambda: "already in use" in app.notice_label["text"]
              and app.status_label["text"] == "Disconnected")
        assert app.connect_button["state"] == tk.NORMAL
        assert app.send_button["state"] == tk.DISABLED
    finally:
        peer.disconnect()


@pytest.mark.integration
def test_connection_refused_is_visible(app: ClientApp) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    _configure(app, "127.0.0.1", port, TransportMode.TCP)
    app.connect_button.invoke()
    _wait(app, lambda: "refused" in app.notice_label["text"].lower()
          and app.status_label["text"] == "Disconnected")
    assert app.connect_button["state"] == tk.NORMAL


def test_send_and_disconnect_workers_do_not_block_tk(app: ClientApp,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    started = threading.Event()
    worker_ids: list[int] = []

    def slow_action(*_args: object) -> None:
        worker_ids.append(threading.get_ident())
        started.set()
        release.wait(timeout=3)

    app._handle_event(Event(EventType.STATE_CHANGED, {
        "old": ConnectionState.DISCONNECTED, "new": ConnectionState.CONNECTED,
    }))
    monkeypatch.setattr(app.client, "send_chat", slow_action)
    monkeypatch.setattr(app.client, "disconnect", slow_action)
    app.message_var.set("do not freeze")
    begin = time.monotonic()
    app.send_button.invoke()
    assert time.monotonic() - begin < 0.3
    assert started.wait(timeout=1)
    app.event_bus.publish(Event(EventType.LOG, {"level": "INFO", "message": "Tk is responsive"}))
    _wait(app, lambda: "Tk is responsive" in app.log_text.get("1.0", "end-1c"))
    started.clear()
    begin = time.monotonic()
    app.disconnect_button.invoke()
    assert time.monotonic() - begin < 0.3
    assert started.wait(timeout=1)
    release.set()
    _wait(app, lambda: not app._send_thread.is_alive()
          and not app._disconnect_thread.is_alive())
    assert all(worker_id != threading.get_ident() for worker_id in worker_ids)


def test_worker_validation_failure_and_bad_event_keep_polling(app: ClientApp,
                                                             monkeypatch) -> None:
    def invalid_send(*_args: object) -> None:
        raise ValidationError("Invalid recipient")

    app._handle_event(Event(EventType.STATE_CHANGED, {"old": "disconnected", "new": "connected"}))
    monkeypatch.setattr(app.client, "send_chat", invalid_send)
    app.message_var.set("keep this draft")
    app.send_button.invoke()
    app.event_bus.publish(Event(EventType.STATS_UPDATED, {}))
    app.event_bus.publish(Event(EventType.LOG, {"level": "INFO", "message": "after bad event"}))
    _wait(app, lambda: "Invalid recipient" in app.notice_label["text"]
          and "after bad event" in app.log_text.get("1.0", "end-1c"))
    assert app.message_var.get() == "keep this draft"


@pytest.mark.integration
def test_close_cleans_up_real_connection(app: ClientApp, running_server) -> None:
    server = running_server
    _configure(app, server.host, server.port, server.mode)
    app.connect_button.invoke()
    _wait(app, lambda: app.status_label["text"] == "Connected")
    app.on_close()
    app.on_close()  # idempotent while shutdown is pending
    _wait(app, lambda: not _exists(app.root))
    assert app.client.state == ConnectionState.DISCONNECTED
    assert app._poll_after_id is None and app._close_after_id is None
    assert app.events.put not in app.event_bus._subscribers.get(None, [])


@pytest.mark.integration
def test_close_cancels_pending_handshake(app: ClientApp) -> None:
    listener = TcpListener()
    listener.start("127.0.0.1", 0)
    try:
        _configure(app, *listener.bound_address, TransportMode.TCP)
        app.connect_button.invoke()
        assert app.client.state == ConnectionState.CONNECTING
        begin = time.monotonic()
        app.on_close()
        assert time.monotonic() - begin < 0.3
        _wait(app, lambda: not _exists(app.root))
        assert app.client.state == ConnectionState.DISCONNECTED
    finally:
        listener.close()


def test_demo_stays_server_free_and_closes(app: ClientApp, monkeypatch) -> None:
    def forbidden_connect(*_args: object) -> None:
        pytest.fail("demo attempted a real connection")

    monkeypatch.setattr(app.client, "connect", forbidden_connect)
    app.demo = DemoClient(app.root, app.event_bus, ClientConfig(username="demo_client"))
    app.demo.start()
    _wait(app, lambda: "Demo message" in app.message_history.get("1.0", "end-1c"))
    assert all(button["state"] == tk.DISABLED for button in (
        app.connect_button, app.disconnect_button, app.send_button,
    ))
    app._on_connect()
    app.on_close()
    _wait(app, lambda: not _exists(app.root))
    assert app.demo._after_id is None
    assert app.client.state == ConnectionState.DISCONNECTED


def test_reconnecting_disables_send_and_allows_cancel(app: ClientApp) -> None:
    app._handle_event(Event(EventType.STATE_CHANGED, {"old": "connected", "new": "reconnecting"}))
    assert app.connect_button["state"] == app.send_button["state"] == tk.DISABLED
    assert app.disconnect_button["state"] == tk.NORMAL
    app._handle_event(Event(EventType.DISCONNECTED, {"reason": DisconnectReason.USER.value}))
    assert app.connect_button["state"] == tk.NORMAL
