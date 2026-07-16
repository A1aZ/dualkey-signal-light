# Prebuilt firmware

`dualkey-signal-light-v0.1.0.factory.bin` is a merged ESP32-S3 image for 8 MB flash. It contains the bootloader, partition table, `boot_app0`, and application firmware and must be written at offset `0x0`.

SHA-256:

```text
44873D6C404F3228097492BF208A5FB8B5E70111248BBE406D99B49EEE5E6DAD  dualkey-signal-light-v0.1.0.factory.bin
```

The binary is distributed as a [GitHub Release asset](https://github.com/A1aZ/dualkey-signal-light/releases), not in the Git repository. For development, prefer the PlatformIO upload command documented in the main README.

The image includes third-party components under their respective licenses. The complete application source and reproducible build configuration are provided in this repository; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
