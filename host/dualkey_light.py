#!/usr/bin/env python3
"""BLE/USB bridge and Agent hook adapter for DualKey Signal Light."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from integrations import (
    CODEX_EVENTS,
    detect_agents,
    install_codex_hooks,
    reconcile_integrations,
)


VERSION = "0.2.1"
DEVICE_NAME = "DualKey Signal Light"
SERVICE_UUID = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0001"
RX_UUID = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0002"
TX_UUID = "7b7f3d10-7d20-4b8e-a2d7-4d55414c0003"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 37363

PUBLIC_STATES = {"idle", "working", "attention", "blocked", "complete", "off"}
PRIORITY = {"off": -1, "idle": 0, "complete": 0, "working": 1, "attention": 2, "blocked": 3}
URGENT_STATES = {"attention", "blocked"}

EVENT_STATE = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "BeforeAgent": "working",
    "BeforeTool": "working",
    "PostToolUse": "working",
    "AfterTool": "working",
    "PreCompact": "working",
    "PreCompress": "working",
    "SubagentStart": "working",
    "SubagentStop": "working",
    "PostToolUseFailure": "blocked",
    "PermissionRequest": "blocked",
    "Notification": "attention",
}

STATE_DIR = Path.home() / ".dualkey-signal-light"
LOGGER = logging.getLogger("dualkey-signal-light")


class BridgeError(RuntimeError):
    """A concise, user-facing bridge error."""


def configure_logging(log_file: Path | None) -> None:
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)


def console_write(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)
    elif error:
        LOGGER.error(message)
    else:
        LOGGER.info(message)


def describe_ble_error(exc: Exception, platform: str | None = None) -> str:
    """Turn common platform BLE failures into actionable messages."""
    platform = sys.platform if platform is None else platform
    detail = str(exc).strip()
    error_name = type(exc).__name__
    permission_failure = error_name == "BleakBluetoothNotAvailableError" or any(
        marker in detail.lower()
        for marker in ("permission", "not authorized", "not available", "denied")
    )
    if platform == "darwin" and permission_failure:
        suffix = f" ({detail})" if detail else ""
        return (
            "Bluetooth is unavailable or permission was denied on macOS. Enable "
            "DualKey Signal Light (or Terminal/Python for source builds) in System "
            "Settings > Privacy & Security > Bluetooth"
            f"{suffix}"
        )
    return detail or error_name


def _walk_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _first_string(payload: dict[str, Any], keys: set[str]) -> str | None:
    for key, value in _walk_values(payload):
        if key in keys and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def payload_indicates_failure(payload: dict[str, Any]) -> bool:
    failure_values = {"error", "failed", "failure", "exception", "blocked"}
    for key, value in _walk_values(payload):
        normalized_key = key.lower()
        if normalized_key in {"exit_status", "exit_code", "return_code", "returncode"}:
            if isinstance(value, int) and value != 0:
                return True
            if isinstance(value, str) and value.strip().lstrip("-").isdigit() and int(value) != 0:
                return True
        if normalized_key in {"status", "state", "result"} and isinstance(value, str):
            if value.strip().lower() in failure_values:
                return True
        if normalized_key in {"error", "failure", "exception"}:
            if value not in (None, False, "", 0, [], {}):
                return True
    return False


def event_from_payload(payload: dict[str, Any]) -> str | None:
    return _first_string(payload, {"hook_event_name", "event_name", "event", "hook", "type"})


def session_from_payload(payload: dict[str, Any]) -> str:
    value = _first_string(
        payload,
        {
            "turn_id",
            "request_id",
            "session_id",
            "conversation_id",
            "thread_id",
            "chat_id",
            "codex_session_id",
        },
    )
    if value:
        return value
    for key in ("CODEX_TURN_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID"):
        if os.environ.get(key, "").strip():
            return os.environ[key].strip()
    workspace = _first_string(payload, {"cwd", "workspace", "workspace_dir", "project_dir"})
    return f"cwd:{workspace}" if workspace else "global"


# Hook payloads arrive from the agent's own process (Claude Code, Codex,
# Gemini CLI, ...) and can legitimately contain large tool input/output.
# None of that content is needed to decide a signal-light state, and forwarding
# it verbatim over the UDP transport risks EMSGSIZE ("Message too long") once a
# single hook payload exceeds the local datagram size limit. Only a small,
# explicitly-allow-listed subset of fields is ever placed on the wire.
_EXPLICIT_SIGNAL_KEYS = {"signal", "signal_name", "lamp_signal"}
_EXIT_STATUS_KEYS = {"exit_status", "exit_code", "return_code", "returncode"}
_FAILURE_VALUE_KEYS = {"status", "state", "result"}
_FAILURE_PRESENCE_KEYS = {"error", "failure", "exception"}
_HOOK_SIGNAL_KEYS = (
    _EXPLICIT_SIGNAL_KEYS
    | _EXIT_STATUS_KEYS
    | _FAILURE_VALUE_KEYS
    | _FAILURE_PRESENCE_KEYS
)
_FAILURE_VALUES = {"error", "failed", "failure", "exception", "blocked"}
_MAX_HOOK_FIELD_CHARS = 200
_MAX_SESSION_CHARS = 160
MAX_HOOK_ENVELOPE_BYTES = 4096
_MISSING = object()


def _truncate_text(value: str, limit: int = _MAX_HOOK_FIELD_CHARS) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[:limit]


def bounded_session(value: str) -> str:
    """Keep the top-level UDP session key stable and bounded."""
    value = value.strip()
    if len(value) <= _MAX_SESSION_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{value[:_MAX_SESSION_CHARS]}:{digest}"


def _safe_signal_value(key: str, value: Any) -> Any:
    """Return only the decision semantic for a signal or failure field.

    Error messages and successful tool results can contain user data. The
    bridge only needs to know whether they indicate failure, not their text.
    """
    if key in _EXPLICIT_SIGNAL_KEYS:
        if isinstance(value, str) and value.strip().lower() in PUBLIC_STATES:
            return value.strip().lower()
        return _MISSING
    if key in _EXIT_STATUS_KEYS:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            digits = normalized.lstrip("-")
            if digits.isdigit():
                return 0 if not digits.strip("0") else 1
        return _MISSING
    if key in _FAILURE_VALUE_KEYS:
        if isinstance(value, str) and value.strip().lower() in _FAILURE_VALUES:
            return value.strip().lower()
        return _MISSING
    if key in _FAILURE_PRESENCE_KEYS and value not in (None, False, "", 0, [], {}):
        return True
    return _MISSING


def _extract_signal_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract failure semantics without forwarding messages or tool output."""
    found: dict[str, Any] = {}
    for raw_key, value in _walk_values(payload):
        key = raw_key.lower()
        if key not in _HOOK_SIGNAL_KEYS:
            continue
        safe_value = _safe_signal_value(key, value)
        if safe_value is _MISSING:
            continue
        if key in _EXPLICIT_SIGNAL_KEYS:
            found.setdefault(key, safe_value)
            continue
        if key in _EXIT_STATUS_KEYS:
            is_nonzero = safe_value != 0
            existing = found.get(key, _MISSING)
            if existing is _MISSING or (is_nonzero and existing == 0):
                found[key] = safe_value
            continue
        # These keys are emitted only when they already encode a failure.
        found[key] = safe_value
    return found


def build_hook_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded, transport-safe subset of a hook payload.

    Only decision-relevant fields and a bounded tool name are preserved.
    Prompts, file contents, attachments, and full tool input/output are always
    excluded so a single hook payload cannot overflow the UDP transport.
    """
    envelope = _extract_signal_fields(payload)

    tool_name = payload.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        envelope["tool_name"] = _truncate_text(tool_name)

    encoded_size = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
    if encoded_size > MAX_HOOK_ENVELOPE_BYTES:
        # Defense in depth: field-level truncation above should already make
        # this unreachable, but decision-relevant signals always win.
        envelope = _extract_signal_fields(payload)
    return envelope


@dataclass(frozen=True)
class HookDecision:
    action: str
    state: str | None = None


def choose_hook_action(event: str, payload: dict[str, Any]) -> HookDecision:
    explicit = _first_string(payload, {"signal", "signal_name", "lamp_signal"})
    if explicit and explicit.lower() in PUBLIC_STATES:
        return HookDecision("set", explicit.lower())
    if payload_indicates_failure(payload):
        return HookDecision("set", "blocked")
    if event in {"Stop", "AfterAgent"}:
        return HookDecision("turn_end")
    if event == "SessionEnd":
        return HookDecision("session_end")
    return HookDecision("set", EVENT_STATE.get(event, "attention"))


@dataclass
class SessionRecord:
    state: str
    updated_at: float


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}

    def apply(self, session: str, decision: HookDecision) -> bool:
        """Apply a hook decision and return whether a completion cue should play."""
        now = time.monotonic()
        if decision.action == "set" and decision.state:
            self.sessions[session] = SessionRecord(decision.state, now)
            return False
        if decision.action == "turn_end":
            current = self.sessions.get(session)
            if current is not None and current.state not in URGENT_STATES:
                self.sessions.pop(session, None)
            return True
        if decision.action == "session_end":
            existed = session in self.sessions
            self.sessions.pop(session, None)
            return existed
        raise ValueError(f"unknown decision action: {decision.action}")

    def set_direct(self, state: str, session: str = "manual") -> None:
        self.sessions.clear()
        if state != "off":
            self.sessions[session] = SessionRecord(state, time.monotonic())

    def clear(self, session: str | None = None) -> None:
        if session:
            self.sessions.pop(session, None)
        else:
            self.sessions.clear()

    def aggregate(self) -> str:
        self._discard_stale_work()
        if not self.sessions:
            return "idle"
        return max((record.state for record in self.sessions.values()), key=lambda state: PRIORITY[state])

    def _discard_stale_work(self) -> None:
        cutoff = time.monotonic() - 2 * 60 * 60
        stale = [
            session
            for session, record in self.sessions.items()
            if record.state in {"working", "idle"} and record.updated_at < cutoff
        ]
        for session in stale:
            self.sessions.pop(session, None)

    def snapshot(self) -> dict[str, str]:
        return {session: record.state for session, record in self.sessions.items()}


class DeviceTransport:
    name = "unknown"

    def __init__(self, notification_handler: Callable[[str], None]) -> None:
        self.notification_handler = notification_handler

    @property
    def connected(self) -> bool:
        raise NotImplementedError

    async def connect(self) -> None:
        raise NotImplementedError

    async def send(self, command: str) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class BleDeviceTransport(DeviceTransport):
    name = "ble"

    def __init__(self, notification_handler: Callable[[str], None], address: str | None) -> None:
        super().__init__(notification_handler)
        self.address = address
        self.client: Any = None

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    async def connect(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise BridgeError("BLE support is missing; install host/requirements.txt") from exc

        try:
            target: Any = self.address
            if target is None:
                target = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=8.0)
                if target is None:
                    raise BridgeError(f'BLE device "{DEVICE_NAME}" was not found')

            self.client = BleakClient(target, disconnected_callback=lambda _: None)
            await self.client.connect()

            def on_notification(_: Any, data: bytearray) -> None:
                message = bytes(data).decode("utf-8", errors="replace").strip()
                if message:
                    self.notification_handler(message)

            await self.client.start_notify(TX_UUID, on_notification)
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError(describe_ble_error(exc)) from exc

    async def send(self, command: str) -> None:
        if not self.connected:
            raise BridgeError("BLE connection is not active")
        await self.client.write_gatt_char(RX_UUID, command.encode("utf-8"), response=True)

    async def close(self) -> None:
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.client = None


class UsbDeviceTransport(DeviceTransport):
    name = "usb"

    def __init__(self, notification_handler: Callable[[str], None], port: str | None) -> None:
        super().__init__(notification_handler)
        self.requested_port = port
        self.serial: Any = None

    @property
    def connected(self) -> bool:
        return bool(self.serial and self.serial.is_open)

    def _open(self) -> None:
        try:
            import serial
            from serial.tools import list_ports
        except ImportError as exc:
            raise BridgeError("USB serial support is missing; install host/requirements.txt") from exc

        port = self.requested_port
        if port is None:
            candidates = []
            for info in list_ports.comports():
                label = " ".join(
                    str(value or "")
                    for value in (info.description, info.product, info.manufacturer, info.hwid)
                ).lower()
                if "dualkey signal light" in label or (
                    info.vid == 0x303A and info.pid == 0x4010
                ):
                    candidates.append(info.device)
            if not candidates:
                raise BridgeError("DualKey USB CDC port was not found")
            port = candidates[0]
        self.serial = serial.Serial(port, 115200, write_timeout=1.0)

    async def connect(self) -> None:
        await asyncio.to_thread(self._open)

    async def send(self, command: str) -> None:
        if not self.connected:
            raise BridgeError("USB serial connection is not active")
        await asyncio.to_thread(self.serial.write, command.encode("utf-8"))
        await asyncio.to_thread(self.serial.flush)

    async def close(self) -> None:
        if self.serial:
            await asyncio.to_thread(self.serial.close)
        self.serial = None


class DeviceWriter:
    def __init__(self, mode: str, ble_address: str | None, serial_port: str | None) -> None:
        self.mode = mode
        self.ble_address = ble_address
        self.serial_port = serial_port
        self.desired_state = "idle"
        self.adapter: DeviceTransport | None = None
        self.last_error: str | None = None
        self.device_event_handler: Callable[[str], None] | None = None
        self._stopping = False

    @property
    def connected(self) -> bool:
        return bool(self.adapter and self.adapter.connected)

    @property
    def transport_name(self) -> str | None:
        return self.adapter.name if self.adapter else None

    def set_state(self, state: str) -> None:
        if state not in PUBLIC_STATES:
            raise ValueError(f"invalid signal state: {state}")
        self.desired_state = state

    def _on_notification(self, message: str) -> None:
        LOGGER.info("[device] %s", message)
        if message.startswith("EVENT ") and self.device_event_handler:
            self.device_event_handler(message)

    def _transport_candidates(self) -> list[DeviceTransport]:
        if self.mode == "ble":
            return [BleDeviceTransport(self._on_notification, self.ble_address)]
        if self.mode == "usb":
            return [UsbDeviceTransport(self._on_notification, self.serial_port)]
        return [
            BleDeviceTransport(self._on_notification, self.ble_address),
            UsbDeviceTransport(self._on_notification, self.serial_port),
        ]

    async def _connect(self) -> bool:
        for candidate in self._transport_candidates():
            try:
                await candidate.connect()
                self.adapter = candidate
                self.last_error = None
                LOGGER.info("Connected to %s over %s.", DEVICE_NAME, candidate.name)
                return True
            except Exception as exc:  # Hardware/backend errors should trigger fallback.
                self.last_error = str(exc)
                try:
                    await candidate.close()
                except Exception:
                    pass
        self.adapter = None
        return False

    async def run(self) -> None:
        last_sent: str | None = None
        last_write_at = 0.0
        while not self._stopping:
            if not self.connected:
                last_sent = None
                if not await self._connect():
                    LOGGER.warning("Waiting for device: %s", self.last_error)
                    await asyncio.sleep(2.0)
                    continue

            try:
                now = time.monotonic()
                if self.desired_state != last_sent or now - last_write_at >= 5.0:
                    assert self.adapter is not None
                    await self.adapter.send(f"STATE {self.desired_state}\n")
                    last_sent = self.desired_state
                    last_write_at = now
                await asyncio.sleep(0.1)
            except Exception as exc:
                self.last_error = str(exc)
                if self.adapter:
                    try:
                        await self.adapter.close()
                    except Exception:
                        pass
                self.adapter = None

    async def stop(self) -> None:
        self._stopping = True
        if self.adapter:
            await self.adapter.close()
        self.adapter = None


class Bridge:
    def __init__(
        self,
        writer: DeviceWriter,
        shutdown_callback: Callable[[], None] | None = None,
    ) -> None:
        self.writer = writer
        self.store = SessionStore()
        self.completion_generation = 0
        self.shutdown_callback = shutdown_callback
        self.writer.device_event_handler = self.handle_device_event

    def handle_device_event(self, message: str) -> None:
        if message in {"EVENT ACK", "EVENT CLEAR"}:
            self.store.clear()
            self.completion_generation += 1
            self.writer.set_state("off" if message == "EVENT CLEAR" else "idle")

    def _set_aggregate(self) -> None:
        self.writer.set_state(self.store.aggregate())

    def _play_completion(self) -> None:
        self.completion_generation += 1
        generation = self.completion_generation
        self.writer.set_state("complete")

        async def restore() -> None:
            await asyncio.sleep(0.9)
            if generation == self.completion_generation:
                self._set_aggregate()

        asyncio.create_task(restore())

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("op")
        if operation == "hook":
            payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
            event = str(request.get("event") or event_from_payload(payload) or "Stop")
            session = str(request.get("session") or session_from_payload(payload))
            decision = choose_hook_action(event, payload)
            play_completion = self.store.apply(session, decision)
            aggregate = self.store.aggregate()
            # A completion pulse is lower priority than every active session.
            if play_completion and aggregate == "idle":
                self._play_completion()
            else:
                self.completion_generation += 1
                self.writer.set_state(aggregate)
            return {"ok": True, "event": event, "session": session, "display": self.writer.desired_state}

        if operation == "set":
            state = str(request.get("state", "")).lower()
            if state not in PUBLIC_STATES:
                raise BridgeError("state must be idle, working, attention, blocked, complete, or off")
            self.store.set_direct(state, str(request.get("session") or "manual"))
            self.completion_generation += 1
            self.writer.set_state(state)
            return {"ok": True, "display": state}

        if operation == "clear":
            session = request.get("session")
            self.store.clear(str(session) if session else None)
            self.completion_generation += 1
            self._set_aggregate()
            return {"ok": True, "display": self.writer.desired_state}

        if operation == "status":
            return {
                "ok": True,
                "connected": self.writer.connected,
                "transport": self.writer.transport_name,
                "display": self.writer.desired_state,
                "sessions": self.store.snapshot(),
                "last_error": self.writer.last_error,
            }

        if operation == "shutdown":
            if self.shutdown_callback:
                self.shutdown_callback()
            return {"ok": True, "shutting_down": True}

        raise BridgeError(f"unknown operation: {operation}")


class UdpBridgeProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
        asyncio.create_task(self._handle_datagram(data, address))

    async def _handle_datagram(self, data: bytes, address: tuple[str, int]) -> None:
        try:
            request = json.loads(data.decode("utf-8"))
            if not isinstance(request, dict):
                raise BridgeError("request must be a JSON object")
            response = await self.bridge.handle(request)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        if self.transport:
            self.transport.sendto(json.dumps(response, ensure_ascii=False).encode("utf-8"), address)


def send_request(request: dict[str, Any], host: str, port: int, timeout: float) -> dict[str, Any]:
    payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(payload, (host, port))
        data, _ = client.recvfrom(65535)
    response = json.loads(data.decode("utf-8"))
    if not response.get("ok"):
        raise BridgeError(response.get("error", "bridge request failed"))
    return response


def read_stdin_payload() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except json.JSONDecodeError:
        return {"raw": raw}


async def run_server(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    if args.install_integrations:
        try:
            results = reconcile_integrations("auto")
            for result in results:
                action = "updated" if result.changed else "current"
                LOGGER.info("%s integration is %s (%s)", result.display_name, action, result.path)
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not update agent integrations: %s", exc)

    writer = DeviceWriter(args.transport, args.ble_address, args.serial_port)
    shutdown_event = asyncio.Event()
    bridge = Bridge(writer, shutdown_event.set)
    try:
        udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: UdpBridgeProtocol(bridge), local_addr=(args.host, args.port)
        )
    except OSError as exc:
        try:
            send_request({"op": "status"}, args.host, args.port, 0.25)
        except Exception:
            raise BridgeError(
                f"cannot listen on udp://{args.host}:{args.port}: {exc}"
            ) from exc
        LOGGER.info("A DualKey bridge is already running; leaving it in control of the device.")
        return 0
    writer_task = asyncio.create_task(writer.run())
    LOGGER.info(
        "DualKey bridge listening on udp://%s:%s (transport=%s).",
        args.host,
        args.port,
        args.transport,
    )
    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        udp_transport.close()
        await writer.stop()
        writer_task.cancel()
        await asyncio.gather(writer_task, return_exceptions=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DualKey BLE/USB signal-light bridge")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the persistent BLE/USB bridge")
    serve.add_argument("--transport", choices=("auto", "ble", "usb"), default="auto")
    serve.add_argument("--ble-address", help="optional BLE address; normally auto-discovered")
    serve.add_argument("--serial-port", help="optional USB serial port, for example COM5")
    serve.add_argument(
        "--install-integrations",
        action="store_true",
        help="detect agents and reconcile their hooks before serving",
    )
    serve.add_argument("--log-file", type=Path, help="write rotating bridge logs to this file")

    set_parser = subparsers.add_parser("set", help="set a signal directly")
    set_parser.add_argument("state", choices=sorted(PUBLIC_STATES))
    set_parser.add_argument("--session", default="manual")

    hook = subparsers.add_parser("hook", help="accept an agent lifecycle hook event")
    hook.add_argument("event", nargs="?")
    hook.add_argument("--session")
    hook.add_argument(
        "--agent",
        default="unknown",
        help="agent namespace supplied by the installed integration",
    )

    clear = subparsers.add_parser("clear", help="clear all state or one session")
    clear.add_argument("--session")

    subparsers.add_parser("status", help="show bridge, transport, and session status")
    subparsers.add_parser("shutdown", help="stop the running bridge")

    integrations = subparsers.add_parser(
        "install-integrations", help="detect agents and install or update their hooks"
    )
    integrations.add_argument(
        "--agents",
        default="auto",
        help="auto, all, or a comma-separated list: codex,claude,gemini",
    )

    uninstall = subparsers.add_parser(
        "uninstall-integrations", help="remove DualKey hooks while preserving other settings"
    )
    uninstall.add_argument(
        "--agents",
        default="all",
        help="all or a comma-separated list: codex,claude,gemini",
    )

    subparsers.add_parser("detect-agents", help="list detected supported agent environments")

    install = subparsers.add_parser(
        "install-hooks", help="deprecated alias for installing Codex hooks only"
    )
    install.add_argument(
        "--codex-path", type=Path, default=Path.home() / ".codex" / "hooks.json"
    )
    return parser


def print_integration_results(results: list[Any], installing: bool) -> None:
    if not results:
        console_write("No supported agent environment was detected.")
        return
    for result in results:
        if result.changed:
            action = "Installed/updated" if installing else "Removed"
        else:
            action = "Already current" if installing else "Not installed"
        console_write(f"{action}: {result.display_name} ({result.path})")
        if result.backup:
            console_write(f"Backup: {result.backup}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            log_file = args.log_file
            if log_file is None and getattr(sys, "frozen", False):
                log_file = STATE_DIR / "bridge.log"
            configure_logging(log_file)
            return asyncio.run(run_server(args))
        if args.command == "set":
            request = {"op": "set", "state": args.state, "session": args.session}
            console_write(
                json.dumps(send_request(request, args.host, args.port, 1.0), ensure_ascii=False, indent=2)
            )
            return 0
        if args.command == "hook":
            try:
                payload = read_stdin_payload()
                event = args.event or event_from_payload(payload) or "Stop"
                raw_session = args.session or session_from_payload(payload)
                session = f"{bounded_session(args.agent)}:{bounded_session(raw_session)}"
                # Only a bounded, safe subset of the payload ever goes over the
                # wire -- see build_hook_envelope for what is/isn't included.
                envelope = build_hook_envelope(payload)
                request = {"op": "hook", "event": event, "session": session, "payload": envelope}
                send_request(request, args.host, args.port, 0.35)
            except Exception as exc:
                # Hooks must never stall or fail the agent itself. This branch
                # only performs the lamp side effect, so failing open is safe.
                console_write(f"DualKey bridge unavailable: {exc}", error=True)
            return 0
        if args.command == "clear":
            request = {"op": "clear", "session": args.session}
            console_write(
                json.dumps(send_request(request, args.host, args.port, 1.0), ensure_ascii=False, indent=2)
            )
            return 0
        if args.command == "status":
            response = send_request({"op": "status"}, args.host, args.port, 1.0)
            console_write(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if args.command == "shutdown":
            response = send_request({"op": "shutdown"}, args.host, args.port, 1.0)
            console_write(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if args.command == "detect-agents":
            detected = detect_agents()
            if detected:
                for adapter in detected:
                    console_write(f"{adapter.key}: {adapter.display_name}")
            else:
                console_write("No supported agent environment was detected.")
            return 0
        if args.command == "install-integrations":
            results = reconcile_integrations(args.agents, install=True)
            print_integration_results(results, True)
            return 0
        if args.command == "uninstall-integrations":
            results = reconcile_integrations(args.agents, install=False)
            print_integration_results(results, False)
            return 0
        if args.command == "install-hooks":
            backup, added = install_codex_hooks(args.codex_path)
            console_write(f"Installed {added} DualKey hook entries in {args.codex_path}.")
            if backup:
                console_write(f"Backup: {backup}")
            return 0
    except (BridgeError, OSError, ValueError, socket.timeout) as exc:
        console_write(f"error: {exc}", error=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
