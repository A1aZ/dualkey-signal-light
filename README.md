# DualKey Signal Light

[![CI](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml/badge.svg)](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/A1aZ/dualkey-signal-light)](https://github.com/A1aZ/dualkey-signal-light/releases)

**English** | [简体中文](README_zh-CN.md)

Turn an [M5Stack Chain DualKey](https://docs.m5stack.com/en/chain/Chain_DualKey) into a wireless status light for Codex, Claude Code, and Gemini CLI.

The firmware uses Bluetooth Low Energy by default. One background service owns the device connection, automatically installs or updates the integrations it detects, and starts whenever you sign in.

## What the lights mean

| Lights | Meaning |
| --- | --- |
| Green cycle | One or more agents are working |
| Flashing yellow | A result or notification needs attention |
| Double-flashing red | Permission, failure, or another blocker needs action |
| Brief green flash | The last active session completed |
| Steady green | Idle |
| Blue heartbeat | Waiting for the computer bridge |
| Off | Manually cleared |

## 1. Flash the DualKey firmware

1. Download `dualkey-signal-light-v0.1.0.factory.bin` from the [latest release](https://github.com/A1aZ/dualkey-signal-light/releases/latest).
2. Move the DualKey side switch to the middle position and unplug USB-C.
3. Hold **Key 1**, the key farther from the lanyard hole, reconnect the USB-C data cable, and then release the key.
4. Open Espressif's [browser flasher](https://espressif.github.io/esptool-js/) in Chrome or Edge, connect to the new serial device, add the downloaded file at address `0x0`, and program it.
5. Unplug and reconnect the DualKey without holding a key. A blue heartbeat means it is ready for the computer bridge.

Flashing replaces the factory firmware. The official [M5DualKey UserDemo](https://github.com/m5stack/M5DualKey-UserDemo) can be used to restore the original demo later. The firmware checksum is published in [dist/README.md](dist/README.md).

## 2. Install the computer bridge and hooks

Download the installer for your computer from the [latest release](https://github.com/A1aZ/dualkey-signal-light/releases/latest):

- Windows 10/11 x64: `dualkey-signal-light-0.2.0-windows-x64-setup.exe`
- Apple silicon Mac: `dualkey-signal-light-0.2.0-macos-arm64.pkg`
- Intel Mac: `dualkey-signal-light-0.2.0-macos-x64.pkg`

A one-click Linux package is not included in this release; Linux source operation is documented in the [developer guide](docs/DEVELOPMENT.md).

Run the installer once. It will:

- install the bridge without requiring Python;
- start one background service at login;
- use BLE automatically, with USB as a fallback;
- detect Codex, Claude Code, and Gemini CLI;
- merge or update DualKey hooks while preserving unrelated hooks;
- back up an existing hook/settings file before changing it.

Keep Bluetooth enabled. Normal OS-level pairing is not required. The current community installers are not code-signed, so Windows SmartScreen or macOS Gatekeeper may stop the first launch.

### If the operating system blocks the installer

Only override the warning when the installer came from this repository's [official release](https://github.com/A1aZ/dualkey-signal-light/releases/latest). Compare its SHA-256 with the release's [`SHA256SUMS`](https://github.com/A1aZ/dualkey-signal-light/releases/latest/download/SHA256SUMS) before continuing.

Windows PowerShell:

```powershell
Get-FileHash "$HOME\Downloads\dualkey-signal-light-0.2.0-windows-x64-setup.exe" -Algorithm SHA256
```

macOS Terminal:

```bash
shasum -a 256 ~/Downloads/dualkey-signal-light-0.2.0-macos-*.pkg
```

Windows 10/11:

1. Open the downloaded `.exe`.
2. If **Windows protected your PC** appears, select **More info**.
3. Confirm that the filename is the installer you downloaded, then select **Run anyway**.
4. If Windows does not offer **Run anyway**, do not disable system security globally. The computer may be managed or using a stricter Smart App Control policy; contact its administrator or use the source installation in the developer guide.

See [Microsoft's SmartScreen and app-protection overview](https://support.microsoft.com/en-US/Windows/Security/Threat-Malware-Protection/protect-your-pc-from-unwanted-software).

macOS:

1. Try to open the downloaded `.pkg` once so macOS records the blocked installer.
2. Open **Apple menu → System Settings → Privacy & Security**.
3. Scroll to **Security** and select **Open Anyway** beside the blocked installer.
4. Authenticate, confirm **Open**, and finish the installer.
5. When DualKey Signal Light starts for the first time, allow Bluetooth access.

Apple notes that **Open Anyway** is available for about one hour after the blocked launch. On a managed Mac the option may be disabled; contact the administrator instead of weakening Gatekeeper. See [Apple's official instructions](https://support.apple.com/guide/mac-help/open-an-app-by-overriding-security-settings-mh40617/mac).

### One Codex confirmation

Codex requires non-managed user hooks to be reviewed. Open `/hooks` once, approve the DualKey hooks, and start a new Codex task. The installer writes and updates the hooks for you; this confirmation is Codex's security boundary and cannot be silently bypassed.

Claude Code and Gemini CLI do not require this Codex-specific confirmation. Existing agent sessions may need to be restarted after installation. If you install another supported agent later, its hooks are detected at the next sign-in or when you run the DualKey installer again.

## Multiple agents and sessions

Codex, Claude Code, and Gemini CLI can all be installed and running together. They do not open separate Bluetooth connections:

- one background bridge owns the DualKey connection;
- hook events are namespaced as `agent:session`, so identical session IDs cannot collide;
- every active session is tracked independently;
- the visible state is aggregated as `blocked > attention > working > idle`;
- completing one session never hides another session that is still working or needs attention;
- a red or yellow alert stays visible until you acknowledge it (or the agent emits a supported session-end event);
- holding both physical keys clears all current sessions.

This is deliberate: two LEDs cannot show every session at once, so they always show the most actionable state.

## Keys

- **Key 1** short press: acknowledge and return to idle.
- **Key 2** short press: preview every light pattern.
- **Both keys** for 1.5 seconds: clear every session and turn the LEDs off.

## Troubleshooting

- Blue heartbeat: the firmware is running, but the computer bridge has not connected. Check Bluetooth and reconnect USB as a fallback.
- Agent activity has no effect: start a new agent session; for Codex, also check `/hooks` approval.
- Windows log: `%USERPROFILE%\.dualkey-signal-light\bridge.log`
- macOS log: `~/.dualkey-signal-light/bridge.log`
- Re-running the installer is safe and updates the service and only the hooks managed by this project.

For source builds, architecture, protocols, tests, packaging, and adding another agent adapter, see [Developer documentation](docs/DEVELOPMENT.md).

Inspired by [starlight36/vibecoding-signal-light](https://github.com/starlight36/vibecoding-signal-light). Original project code is licensed under the [MIT License](LICENSE); third-party notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
