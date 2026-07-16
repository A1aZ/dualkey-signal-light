# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-07-16

### Added

- One-click, per-user Windows installer with login auto-start and clean uninstall.
- macOS installer packages for Apple silicon and Intel Macs with a LaunchAgent.
- Automatic detection and hook integration for Codex, Claude Code, and Gemini CLI.
- Idempotent integration updates, timestamped configuration backups, and scoped removal.
- Agent-namespaced session tracking and multi-agent conflict tests.

### Changed

- The root READMEs now focus only on firmware flashing and end-user installation.
- Source development, architecture, protocol, testing, and packaging moved to `docs/DEVELOPMENT.md`.
- Completion cues no longer override another active or urgent session.
- Duplicate daemon starts leave the existing singleton daemon in control.

## [0.1.0] - 2026-07-16

### Added

- Initial Chain DualKey firmware with BLE GATT and USB CDC control.
- Six-state lamp language plus a BLE-disconnected heartbeat.
- Local acknowledgement, effect-preview, and clear key interactions.
- Persistent Python host bridge with session-aware state aggregation.
- Codex hook adapter and additive hook installer.
- Prebuilt merged ESP32-S3 factory image.
- English and Simplified Chinese documentation.
