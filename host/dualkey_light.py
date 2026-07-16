#!/usr/bin/env python3
"""BLE/USB bridge and Agent hook adapter for DualKey Signal Light."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


VERSION = "0.1.0"
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
    "PostToolUse": "working",
    "PreCompact": "working",
    "SubagentStart": "working",
    "SubagentStop": "working",
    "PostToolUseFailure": "blocked",
    "PermissionRequest": "blocked",
    "Notification": "attention",
}

CODEX_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Stop",
    "SessionEnd",
)


class BridgeError(RuntimeError):
    """A concise, user-facing bridge error."""


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
            "Terminal or Python in System Settings > Privacy & Security > Bluetooth"
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
    if event == "Stop":
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
        print(f"[device] {message}", flush=True)
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
                print(f"Connected to {DEVICE_NAME} over {candidate.name}.", flush=True)
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
                    print(f"Waiting for device: {self.last_error}", file=sys.stderr, flush=True)
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
    def __init__(self, writer: DeviceWriter) -> None:
        self.writer = writer
        self.store = SessionStore()
        self.completion_generation = 0
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
            if self.store.apply(session, decision):
                self._play_completion()
            else:
                self.completion_generation += 1
                self._set_aggregate()
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
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    except json.JSONDecodeError:
        return {"raw": raw}


def hook_command(event: str) -> str:
    parts = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "hook", event]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def install_codex_hooks(path: Path) -> tuple[Path | None, int]:
    data: dict[str, Any]
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeError(f"cannot read existing hooks file: {exc}") from exc
        if not isinstance(data, dict):
            raise BridgeError("existing hooks.json is not a JSON object")
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BridgeError('existing hooks.json field "hooks" is not an object')

    added = 0
    for event in CODEX_EVENTS:
        event_entries = hooks.setdefault(event, [])
        if not isinstance(event_entries, list):
            raise BridgeError(f'existing hook event "{event}" is not a list')
        command = hook_command(event)
        already_present = any(
            isinstance(group, dict)
            and any(
                isinstance(item, dict) and item.get("command") == command
                for item in group.get("hooks", [])
            )
            for group in event_entries
        )
        if not already_present:
            event_entries.append(
                {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
            )
            added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if path.exists() and added:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        backup.write_bytes(path.read_bytes())
    if added:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    return backup, added


async def run_server(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    writer = DeviceWriter(args.transport, args.ble_address, args.serial_port)
    bridge = Bridge(writer)
    udp_transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpBridgeProtocol(bridge), local_addr=(args.host, args.port)
    )
    writer_task = asyncio.create_task(writer.run())
    print(f"DualKey bridge listening on udp://{args.host}:{args.port} (transport={args.transport}).")
    try:
        await asyncio.Future()
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
    serve.add_argument("--transport", choices=("auto", "ble", "usb"), default="ble")
    serve.add_argument("--ble-address", help="optional BLE address; normally auto-discovered")
    serve.add_argument("--serial-port", help="optional USB serial port, for example COM5")

    set_parser = subparsers.add_parser("set", help="set a signal directly")
    set_parser.add_argument("state", choices=sorted(PUBLIC_STATES))
    set_parser.add_argument("--session", default="manual")

    hook = subparsers.add_parser("hook", help="accept a Codex/Claude hook event")
    hook.add_argument("event", nargs="?")
    hook.add_argument("--session")

    clear = subparsers.add_parser("clear", help="clear all state or one session")
    clear.add_argument("--session")

    subparsers.add_parser("status", help="show bridge, transport, and session status")

    install = subparsers.add_parser("install-hooks", help="merge hooks into Codex hooks.json")
    install.add_argument(
        "--codex-path", type=Path, default=Path.home() / ".codex" / "hooks.json"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            return asyncio.run(run_server(args))
        if args.command == "set":
            request = {"op": "set", "state": args.state, "session": args.session}
            print(json.dumps(send_request(request, args.host, args.port, 1.0), ensure_ascii=False, indent=2))
            return 0
        if args.command == "hook":
            payload = read_stdin_payload()
            event = args.event or event_from_payload(payload) or "Stop"
            session = args.session or session_from_payload(payload)
            request = {"op": "hook", "event": event, "session": session, "payload": payload}
            try:
                send_request(request, args.host, args.port, 0.35)
            except (BridgeError, TimeoutError, socket.timeout) as exc:
                # Hooks must never stall or fail the agent itself.
                print(f"DualKey bridge unavailable: {exc}", file=sys.stderr)
            return 0
        if args.command == "clear":
            request = {"op": "clear", "session": args.session}
            print(json.dumps(send_request(request, args.host, args.port, 1.0), ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            response = send_request({"op": "status"}, args.host, args.port, 1.0)
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return 0
        if args.command == "install-hooks":
            backup, added = install_codex_hooks(args.codex_path)
            print(f"Installed {added} DualKey hook entries in {args.codex_path}.")
            if backup:
                print(f"Backup: {backup}")
            return 0
    except (BridgeError, OSError, socket.timeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
