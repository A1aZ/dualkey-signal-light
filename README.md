# DualKey Signal Light

[![CI](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml/badge.svg)](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/A1aZ/dualkey-signal-light)](https://github.com/A1aZ/dualkey-signal-light/releases)

**English** | [简体中文](README_zh-CN.md)

Turn an [M5Stack Chain DualKey](https://docs.m5stack.com/en/chain/Chain_DualKey) into a wireless status light for AI coding agents.

The ESP32-S3 firmware renders agent states on the DualKey's two RGB LEDs. A small host bridge keeps one persistent Bluetooth Low Energy connection open, aggregates concurrent agent sessions, and accepts fast local hook events from Codex or compatible tools. USB CDC remains available as a fallback and debugging transport.

## Highlights

- BLE-first operation; the USB cable is optional after flashing.
- Persistent GATT connection instead of scanning on every hook event.
- Codex hook adapter and installer that preserves existing hook entries.
- Session-aware priority: `blocked > attention > working > idle`.
- Alerts are not hidden when another agent session starts working.
- Two local keys for acknowledgement, effect preview, and clear.
- Shared text protocol over BLE and USB CDC.
- PlatformIO build and automated host-side tests.

## Lamp language

| LEDs | State | Meaning |
| --- | --- | --- |
| Both steady green | `idle` | Nothing needs attention |
| Offset green → yellow → red cycle | `working` | The agent is thinking, editing, or running tools |
| Both flashing yellow | `attention` | A result or notification is ready to review |
| Both double-flashing red | `blocked` | Permission, failure, or another blocker needs action |
| Both briefly flashing green | `complete` | A turn or session just completed |
| Off | `off` | Manually cleared |
| Blue heartbeat | Disconnected | The firmware is advertising and waiting for the bridge |

## Key controls

- **Key 1** (farther from the lanyard hole, GPIO 0), short press: acknowledge and return to `idle`.
- **Key 2**, short press: cycle through every lamp pattern.
- **Both keys**, hold for 1.5 seconds: clear state and turn the LEDs off.
- Hold **Key 1** while connecting USB: enter the ESP32-S3 ROM download mode.

## Architecture

```text
Codex / compatible hooks
          │ fast localhost UDP
          ▼
host/dualkey_light.py  ─── session aggregation
          │
          ├── BLE GATT (default)
          └── USB CDC (fallback)
                    │
                    ▼
           Chain DualKey firmware
                    │
                    ▼
             2 × WS2812 LEDs
```

## Requirements

- M5Stack Chain DualKey (C147)
- A USB-C data cable for the initial flash
- Python 3.10 or newer
- Bluetooth Low Energy on the host for wireless operation

The host bridge uses [Bleak](https://github.com/hbldh/bleak) and pySerial, so it can run on Windows, macOS, and Linux. The initial hardware validation for this release was performed on Windows 11.

## Quick start

### 1. Clone and install the tools

```bash
git clone https://github.com/A1aZ/dualkey-signal-light.git
cd dualkey-signal-light
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install platformio -r .\host\requirements.txt
```

macOS/Linux:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install platformio -r host/requirements.txt
```

On macOS, the first BLE scan may ask for Bluetooth access. Allow the terminal or Python process. If access was denied, enable it in **System Settings → Privacy & Security → Bluetooth**. See the [Bleak macOS backend notes](https://bleak.readthedocs.io/en/latest/backends/macos.html) and [Apple's privacy settings guide](https://support.apple.com/guide/mac-help/change-privacy-security-settings-on-mac-mchl211c911f/mac).

### 2. Build

```powershell
.\.venv\Scripts\python.exe -m platformio run
```

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `./.venv/bin/python`. The application image is written to `.pio/build/dualkey/firmware.bin`.

### 3. Enter download mode and flash

The DualKey has no dedicated reset button. Follow the [official download-mode sequence](https://docs.m5stack.com/en/chain/Chain_DualKey):

1. Move the side switch to the middle position.
2. Disconnect USB-C.
3. Hold **Key 1**, the key farther from the lanyard hole.
4. Reconnect the USB-C data cable and release Key 1.
5. Find the new serial port and upload:

```powershell
.\.venv\Scripts\python.exe -m platformio run --target upload --upload-port COM4
```

Use the actual port, such as `/dev/ttyACM0` on Linux. After flashing, disconnect and reconnect USB without holding either key.

On macOS, the DualKey normally appears as `/dev/cu.usbmodem*`:

```bash
ls /dev/cu.usbmodem*
./.venv/bin/python -m platformio run --target upload --upload-port /dev/cu.usbmodemXXXX
```

> Flashing replaces the factory firmware. To restore it, use the [official M5DualKey UserDemo](https://github.com/m5stack/M5DualKey-UserDemo) or M5Burner.

A merged 8 MB factory image is also attached to each [GitHub Release](https://github.com/A1aZ/dualkey-signal-light/releases). Flash that image at offset `0x0`; checksums are documented in [dist/README.md](dist/README.md).

### 4. Start the BLE bridge

The device advertises as `DualKey Signal Light`. OS-level pairing is not required for the default unencrypted GATT connection.

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py serve --transport ble
```

macOS/Linux:

```bash
./.venv/bin/python host/dualkey_light.py serve --transport ble
```

Keep the bridge running, then use another terminal to test it:

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py set working
.\.venv\Scripts\python.exe .\host\dualkey_light.py set attention
.\.venv\Scripts\python.exe .\host\dualkey_light.py set blocked
.\.venv\Scripts\python.exe .\host\dualkey_light.py set idle
.\.venv\Scripts\python.exe .\host\dualkey_light.py status
```

Use `--ble-address <address>` to pin a device. On macOS, CoreBluetooth exposes a host-specific UUID instead of the hardware MAC address, so name-based auto-discovery is usually the simplest option. USB fallback mode is:

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py serve --transport usb --serial-port COM5
```

On macOS, use `./.venv/bin/python host/dualkey_light.py serve --transport usb --serial-port /dev/cu.usbmodemXXXX`.

`--transport auto` tries BLE first and then USB.

### 5. Install Codex hooks

After confirming that the bridge controls the LEDs:

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py install-hooks
```

The installer merges entries into `~/.codex/hooks.json`, preserves unrelated hooks, and creates a timestamped backup before changing an existing file. Restart Codex tasks after installation so the new hook configuration is loaded.

Hook calls are lightweight UDP clients with a 350 ms ceiling. If the bridge is unavailable, the hook prints a warning but does not fail the agent.

## BLE and USB protocol

Both transports accept UTF-8 text commands:

```text
STATE idle|working|attention|blocked|complete|off
BRIGHTNESS 1..255
STATUS
PING
```

BLE UUIDs:

- Service: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0001`
- RX / Write: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0002`
- TX / Notify: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0003`

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\host\tests -v
.\.venv\Scripts\python.exe -m platformio run
```

GitHub Actions runs the host dependency/import checks, command-line smoke test, and unit tests on Ubuntu, Windows, and macOS. The firmware build runs on Ubuntu. Physical BLE and USB validation for v0.1.0 was performed on Windows 11; the macOS path uses Bleak's CoreBluetooth backend and is continuously checked on `macos-latest`.

The firmware follows the official pin map: GPIO 21 drives the two WS2812 LEDs, GPIO 40 is an active-low open-drain LED power enable, and GPIO 8/7 are never configured as outputs.

## Security and USB identity

The BLE service is intentionally unencrypted and carries only lamp-control/status messages. Do not extend the current protocol with secrets without adding authentication and encryption.

The firmware uses Espressif VID `0x303A` with a development PID `0x4010` so the host bridge can distinguish it from ROM download mode. This is suitable for development, not an assigned USB identity for a commercial product. Products must use properly assigned USB identifiers.

## Acknowledgements

The physical-agent-status concept and compact lamp language were inspired by [starlight36/vibecoding-signal-light](https://github.com/starlight36/vibecoding-signal-light), an MIT-licensed project for a real traffic light driven by local AI coding agents. This repository is a new implementation for the Chain DualKey's ESP32-S3, RGB LEDs, keys, BLE GATT, and USB CDC hardware. See [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

Hardware details and the download procedure come from the [M5Stack Chain DualKey documentation](https://docs.m5stack.com/en/chain/Chain_DualKey) and [official UserDemo](https://github.com/m5stack/M5DualKey-UserDemo).

## License

Original code in this repository is licensed under the [MIT License](LICENSE). Third-party dependencies retain their respective licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
