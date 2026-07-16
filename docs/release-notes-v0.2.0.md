# DualKey Signal Light v0.2.0

This release turns the computer-side bridge into an installable background application. End users no longer need to clone the repository, install Python, run a service manually, or edit hook files.

## Highlights

- Windows x64 setup executable with per-user installation, login auto-start, upgrades, and uninstallation.
- macOS packages for Apple silicon and Intel Macs with a LaunchAgent.
- Automatic detection and integration for Codex, Claude Code, and Gemini CLI.
- One daemon and one BLE/USB connection shared safely by all agents and sessions.
- Namespaced session IDs and deterministic `blocked > attention > working > idle` aggregation.
- Existing settings are backed up; unrelated hooks are preserved during install, update, and uninstall.
- User-focused English and Chinese installation guides plus a separate English development guide.

## Assets

- `dualkey-signal-light-v0.1.0.factory.bin` — merged 8 MB ESP32-S3 firmware image; flash at `0x0`.
- `dualkey-signal-light-0.2.0-windows-x64-setup.exe` — Windows 10/11 x64 installer.
- `dualkey-signal-light-0.2.0-macos-arm64.pkg` — Apple silicon macOS installer.
- `dualkey-signal-light-0.2.0-macos-x64.pkg` — Intel macOS installer.

The macOS packages are unsigned community builds unless a Developer ID Installer identity is supplied to the release workflow. macOS may require explicit approval under Privacy & Security. Codex also requires users to review newly installed user hooks once through `/hooks`; the installer cannot bypass that security check.

Firmware SHA-256:

```text
44873D6C404F3228097492BF208A5FB8B5E70111248BBE406D99B49EEE5E6DAD  dualkey-signal-light-v0.1.0.factory.bin
```
