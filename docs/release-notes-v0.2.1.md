# DualKey Signal Light v0.2.1

This patch release hardens lifecycle-hook delivery to the local DualKey bridge.

## Fixed

- Lifecycle-hook events are reduced to a bounded status envelope before local UDP delivery.
- Large tool inputs, outputs, and session identifiers no longer exceed operating-system datagram limits.
- Hook-side bridge, timeout, serialization, and transport failures fail open and cannot block the coding agent.
- Prompts, file bodies, attachments, complete tool inputs, and tool outputs are no longer forwarded through local bridge IPC.

## Assets

- `dualkey-signal-light-v0.1.0.factory.bin` — unchanged merged 8 MB ESP32-S3 firmware image; flash at `0x0`.
- `dualkey-signal-light-0.2.1-windows-x64-setup.exe` — Windows 10/11 x64 installer.
- `dualkey-signal-light-0.2.1-macos-arm64.pkg` — Apple silicon macOS installer.
- `dualkey-signal-light-0.2.1-macos-x64.pkg` — Intel macOS installer.

The desktop installers remain unsigned community builds. Windows SmartScreen or macOS Gatekeeper may require explicit approval. Codex users must still review newly installed user hooks once through `/hooks`.

The DualKey firmware is unchanged from v0.2.0.
