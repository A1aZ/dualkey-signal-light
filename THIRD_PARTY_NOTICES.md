# Third-party notices

The MIT License in this repository covers the original DualKey Signal Light source code. It does not replace the licenses of build tools, frameworks, or libraries fetched by PlatformIO or pip.

Direct firmware dependencies declared in `platformio.ini`:

| Component | Version constraint | License | Source |
| --- | --- | --- | --- |
| Arduino-ESP32 | Selected by `espressif32@6.12.0` | Primarily Apache-2.0; individual bundled components may use other compatible licenses | [espressif/arduino-esp32](https://github.com/espressif/arduino-esp32) |
| NimBLE-Arduino | `2.5.0` | Apache-2.0 | [h2zero/NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino) |
| Adafruit NeoPixel | `^1.15.1` | LGPL-3.0 | [adafruit/Adafruit_NeoPixel](https://github.com/adafruit/Adafruit_NeoPixel) |

Direct host dependencies declared in `host/requirements.txt`:

| Component | Version constraint | License | Source |
| --- | --- | --- | --- |
| Bleak | `>=1.0.1,<3` | MIT | [hbldh/bleak](https://github.com/hbldh/bleak) |
| pySerial | `>=3.5,<4` | BSD-3-Clause | [pyserial/pyserial](https://github.com/pyserial/pyserial) |

Distribution build tools:

| Component | Version | License | Source |
| --- | --- | --- | --- |
| PyInstaller | `6.21.0` | GPL-2.0 with the PyInstaller bootloader exception; selected files are Apache-2.0 | [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |
| Inno Setup | 6.x | Inno Setup License | [Inno Setup license](https://jrsoftware.org/files/is/license.txt) |

PyInstaller's exception permits distributing generated bundles under this project's license, subject to the licenses of bundled dependencies. Inno Setup is used only to produce the Windows installer and retains its own notices in the generated installer runtime.

The exact source and license files for resolved firmware dependencies are downloaded into PlatformIO's package and library directories during a build. Redistributors of compiled firmware must comply with all applicable third-party license terms.
