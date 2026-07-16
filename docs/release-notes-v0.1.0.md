# DualKey Signal Light v0.1.0

Initial public release for the M5Stack Chain DualKey (C147).

## Highlights

- Bluetooth Low Energy GATT and USB CDC transports
- Persistent Python bridge with concurrent agent-session aggregation
- Codex hook adapter and additive hook installer
- Six lamp states plus two-key local controls
- English and Simplified Chinese documentation
- Host support for Windows, macOS, and Linux
- Host CI on Ubuntu, Windows, and macOS

## Firmware

`dualkey-signal-light-v0.1.0.factory.bin` is a merged factory image for the DualKey's 8 MB flash. Flash it at offset `0x0`. Verify the download with the attached `SHA256SUMS` file.

Physical BLE and USB validation for this release was performed on Windows 11 with a Chain DualKey. The macOS host path uses Bleak's CoreBluetooth backend and is covered by the `macos-latest` CI job.

See `THIRD_PARTY_NOTICES.md` for dependency licenses and `ACKNOWLEDGMENTS.md` for inspiration and hardware references.
