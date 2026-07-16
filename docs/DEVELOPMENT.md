# DualKey Signal Light development guide

The root READMEs are intentionally end-user installation guides. This document covers source development, architecture, protocols, verification, and packaging.

## Architecture

```text
Codex / Claude Code / Gemini CLI hooks
                    |
                    | short-lived localhost UDP request
                    v
            dualkey-light daemon
        session namespace + priority reducer
             |                    |
             | BLE GATT           | USB CDC fallback
             +----------+---------+
                        v
              Chain DualKey firmware
                  2 x WS2812 LEDs
```

There is exactly one daemon per user and one physical-device connection. A second daemon that finds the local UDP endpoint already owned by this project exits successfully and leaves the existing daemon in control.

Hook sessions are keyed as `<agent>:<session>`. The reducer tracks sessions independently and selects `blocked > attention > working > idle`. Urgent states are sticky; ordinary `Stop` events do not clear them. A completion cue is shown only when no other active session has a higher state.

## Source setup

Python 3.10 or newer is required.

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

## Firmware

Build:

```bash
python -m platformio run
```

Enter ROM download mode by moving the side switch to the middle, disconnecting USB, holding Key 1, and reconnecting USB. Upload with the actual serial port:

```bash
python -m platformio run --target upload --upload-port PORT
```

The official pin map is intentionally conservative:

- GPIO 21: two WS2812 LEDs
- GPIO 40: active-low, open-drain LED power enable
- GPIO 0: Key 1
- GPIO 41: Key 2
- GPIO 8 and 7 are never configured as outputs

The firmware uses Espressif VID `0x303A` and development PID `0x4010`. This is a development identity, not an assigned USB identity for a commercial product.

## Host bridge

Run the daemon from source:

```bash
python host/dualkey_light.py serve --transport auto --install-integrations
```

Useful commands:

```bash
python host/dualkey_light.py detect-agents
python host/dualkey_light.py install-integrations --agents auto
python host/dualkey_light.py install-integrations --agents codex,claude,gemini
python host/dualkey_light.py status
python host/dualkey_light.py set blocked
python host/dualkey_light.py clear
python host/dualkey_light.py shutdown
python host/dualkey_light.py uninstall-integrations --agents all
```

Hook clients have a 350 ms UDP timeout and return success when the daemon is unavailable so a lamp failure cannot block the coding agent.

### Agent adapters

Adapters live in `host/integrations.py`.

| Agent | User config | Event namespace |
| --- | --- | --- |
| Codex | `~/.codex/hooks.json` | Codex lifecycle hooks |
| Claude Code | `~/.claude/settings.json` | Claude Code hooks |
| Gemini CLI | `~/.gemini/settings.json` | Gemini CLI hooks |

Installation is additive and idempotent. Before rewriting an existing JSON file, the adapter creates a timestamped sibling backup. It removes only command handlers whose command points to `dualkey-light` or the legacy `dualkey_light.py` source entry. Unrelated hook groups and settings remain intact.

The parser deliberately accepts strict JSON only. If an existing settings file cannot be parsed, installation fails without replacing it. Codex additionally requires the user to approve non-managed hooks in `/hooks`.

To add another agent:

1. Add an `AgentAdapter` with its executable, user config path, supported events, timeout units, and detection markers.
2. Map its lifecycle events in `EVENT_STATE` or `choose_hook_action`.
3. Add fixture-based schema, idempotence, preservation, and concurrent-session tests.
4. Link the adapter's official hook documentation in the pull request.

## Device protocol

BLE and USB accept the same UTF-8 text commands:

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

The GATT service is intentionally unencrypted and carries lamp state only. Do not send secrets over it without adding authentication and encryption.

## Tests

```bash
python -m unittest discover -s host/tests -v
python -m platformio run
```

The unit suite covers event mapping, integration preservation and backups, multi-agent namespacing, reducer priority, sticky alerts, completion behavior, physical clearing, and platform error messages. CI runs host tests on Windows, Ubuntu, and macOS, builds the firmware, and builds installer artifacts.

## Packaging

Install the packaging dependency and build the platform-local PyInstaller one-folder bundle:

```bash
python -m pip install -r host/requirements.txt -r packaging/requirements.txt
python -m PyInstaller --noconfirm --clean --distpath build/package --workpath build/pyinstaller packaging/dualkey-light.spec
```

PyInstaller is not a cross-compiler. Build Windows on Windows and each macOS architecture on matching runners.

### Windows

Compile `packaging/windows/dualkey-signal-light.iss` with Inno Setup 6. The per-user installer requires no administrator privileges, installs a login-startup shortcut, reconciles detected integrations, and cleanly shuts down the previous daemon during an update. Its uninstaller removes only this project's hooks and startup entry.

### macOS

Run:

```bash
packaging/macos/build-pkg.sh \
  "build/package/DualKey Signal Light.app" \
  build/installers/dualkey-signal-light-VERSION-macos-ARCH.pkg \
  VERSION
```

The package installs `DualKey Signal Light.app` under `/Applications`, a CLI symlink under `/usr/local/bin`, and a per-user LaunchAgent from `/Library/LaunchAgents`. The app bundle declares `NSBluetoothAlwaysUsageDescription`, keeps the background process out of the Dock, and gives macOS a stable identity for Bluetooth permission. The postinstall script performs user-scoped hook reconciliation and starts the agent.

Set `MACOS_INSTALLER_IDENTITY` to a valid Developer ID Installer identity to sign the product archive. A public release should also be notarized and stapled before distribution; CI currently emits unsigned community test packages when no identity is provided.

## Release checklist

1. Update the host version, changelog, installer version, and release notes.
2. Run host tests and the firmware build locally.
3. Push and wait for all CI jobs.
4. Download the Windows and both macOS installer artifacts.
5. Compute SHA-256 checksums and add them to the release notes.
6. Create the GitHub release with the factory firmware image and installers.
7. Verify a clean install, upgrade, auto-start, hook preservation, and uninstall on physical machines.

## References

- [M5Stack Chain DualKey documentation](https://docs.m5stack.com/en/chain/Chain_DualKey)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Gemini CLI hooks reference](https://geminicli.com/docs/hooks/reference/)
- [Bleak](https://bleak.readthedocs.io/)
- [PyInstaller](https://pyinstaller.org/en/stable/)
