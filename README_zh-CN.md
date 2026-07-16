# DualKey Signal Light

[![CI](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml/badge.svg)](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/A1aZ/dualkey-signal-light)](https://github.com/A1aZ/dualkey-signal-light/releases)

[English](README.md) | **简体中文**

把 [M5Stack Chain DualKey](https://docs.m5stack.com/en/chain/Chain_DualKey) 变成 AI 编程助手的无线状态灯。

ESP32-S3 固件使用 DualKey 的两颗 RGB LED 显示 Agent 状态。电脑侧常驻桥接进程维持一条 BLE 连接、聚合多个 Agent 会话，并接收 Codex 或兼容工具发来的快速本机 Hook 事件。USB CDC 同时保留为备用和调试通道。

## 功能亮点

- BLE 优先，初次刷写完成后无需依赖 USB 数据线。
- 常驻 GATT 连接，不会在每次 Hook 时重新扫描蓝牙。
- Codex Hook 适配器和安装器，保留已有 Hook 配置。
- 多会话优先级：`blocked > attention > working > idle`。
- 一个会话的红色/黄色告警不会被另一个会话的普通工作态覆盖。
- 两个机械键可用于确认、预览灯效和清除状态。
- BLE 与 USB CDC 共用一套文本协议。
- PlatformIO 构建和自动化主机端测试。

## 灯语

| 灯效 | Agent 状态 | 含义 |
| --- | --- | --- |
| 双绿常亮 | `idle` | 空闲，无需处理 |
| 双灯错相绿→黄→红慢速循环 | `working` | 正在思考、执行工具或测试 |
| 双黄闪烁 | `attention` | 有结果或通知需要查看 |
| 双红双闪 | `blocked` | 权限请求、失败或阻塞，需要马上处理 |
| 双绿短闪 | `complete` | 一个任务或会话刚完成 |
| 全灭 | `off` | 手动清除 |
| 蓝色心跳 | 尚未连接 | BLE 正在广播，等待电脑侧桥接 |

## 双键交互

- **Key 1**（离挂绳孔更远，GPIO 0）短按：确认告警并回到 `idle`。
- **Key 2** 短按：循环预览全部灯效。
- **两键同时**长按 1.5 秒：清除并熄灯。
- 插入 USB 时按住 **Key 1**：进入 ESP32-S3 ROM 下载模式。

## 工作架构

```text
Codex / 兼容 Hook
        │ 本机 UDP，快速返回
        ▼
host/dualkey_light.py  ─── 多会话聚合
        │
        ├── BLE GATT（默认）
        └── USB CDC（备用）
                  │
                  ▼
          Chain DualKey 固件
                  │
                  ▼
            2 × WS2812 LED
```

## 环境要求

- M5Stack Chain DualKey（C147）
- 初次刷写所需的 USB-C 数据线
- Python 3.10 或更新版本
- 无线使用时，电脑需要支持 BLE

电脑侧使用 [Bleak](https://github.com/hbldh/bleak) 和 pySerial，可运行在 Windows、macOS 和 Linux。本版本的首次实机验证环境为 Windows 11。

## 快速开始

### 1. 克隆并安装工具

```bash
git clone https://github.com/A1aZ/dualkey-signal-light.git
cd dualkey-signal-light
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install platformio -r .\host\requirements.txt
```

macOS/Linux：

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install platformio -r host/requirements.txt
```

在 macOS 上，首次扫描 BLE 时系统可能请求蓝牙权限，请允许终端或 Python 访问。如果之前拒绝过，请前往 **系统设置 → 隐私与安全性 → 蓝牙** 开启。可参考 [Bleak 的 macOS 后端说明](https://bleak.readthedocs.io/en/latest/backends/macos.html)和 [Apple 隐私设置指南](https://support.apple.com/zh-cn/guide/mac-help/mchl211c911f/mac)。

### 2. 构建固件

```powershell
.\.venv\Scripts\python.exe -m platformio run
```

macOS/Linux 请将 `.\.venv\Scripts\python.exe` 换成 `./.venv/bin/python`。应用固件位于 `.pio/build/dualkey/firmware.bin`。

### 3. 进入下载模式并刷写

DualKey 没有独立 Reset 键。按[官方步骤](https://docs.m5stack.com/en/chain/Chain_DualKey)操作：

1. 将侧面开关拨到中间位置。
2. 拔掉 USB-C。
3. 按住离挂绳孔更远的 **Key 1**。
4. 插入 USB-C 数据线，再松开 Key 1。
5. 找到新增串口并上传：

```powershell
.\.venv\Scripts\python.exe -m platformio run --target upload --upload-port COM4
```

请替换成实际端口，Linux 上通常类似 `/dev/ttyACM0`。刷写完成后，不按任何按键重新拔插 USB。

macOS 上的 DualKey 通常显示为 `/dev/cu.usbmodem*`：

```bash
ls /dev/cu.usbmodem*
./.venv/bin/python -m platformio run --target upload --upload-port /dev/cu.usbmodemXXXX
```

> 刷写会覆盖出厂固件。需要恢复时可使用 [M5Stack 官方 UserDemo](https://github.com/m5stack/M5DualKey-UserDemo) 或 M5Burner。

每个 [GitHub Release](https://github.com/A1aZ/dualkey-signal-light/releases) 也附带从 `0x0` 写入的 8 MB 合并镜像，校验值见 [dist/README.md](dist/README.md)。

### 4. 启动 BLE 桥接

设备广播名为 `DualKey Signal Light`。默认 GATT 连接无需先在系统蓝牙设置中手动配对。

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py serve --transport ble
```

macOS/Linux：

```bash
./.venv/bin/python host/dualkey_light.py serve --transport ble
```

保持这个终端运行，另开终端测试：

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py set working
.\.venv\Scripts\python.exe .\host\dualkey_light.py set attention
.\.venv\Scripts\python.exe .\host\dualkey_light.py set blocked
.\.venv\Scripts\python.exe .\host\dualkey_light.py set idle
.\.venv\Scripts\python.exe .\host\dualkey_light.py status
```

可使用 `--ble-address <address>` 固定设备。macOS 的 CoreBluetooth 会提供一条仅对当前电脑有效的 UUID，而不是硬件 MAC 地址，因此通常直接按设备名自动发现最方便。USB 备用模式：

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py serve --transport usb --serial-port COM5
```

macOS 请使用 `./.venv/bin/python host/dualkey_light.py serve --transport usb --serial-port /dev/cu.usbmodemXXXX`。

`--transport auto` 会优先尝试 BLE，再回退 USB。

### 5. 安装 Codex Hook

先确认桥接服务可以控制灯效，再运行：

```powershell
.\.venv\Scripts\python.exe .\host\dualkey_light.py install-hooks
```

安装器会合并写入 `~/.codex/hooks.json`，保留无关 Hook，并在修改已有文件前生成带时间戳的备份。安装完成后重启 Codex 任务，使新配置生效。

Hook 客户端通过本机 UDP 快速返回，等待上限为 350ms；桥接未运行时只打印警告，不会让 Agent 失败。

## BLE/USB 文本协议

两种通道都接受 UTF-8 文本命令：

```text
STATE idle|working|attention|blocked|complete|off
BRIGHTNESS 1..255
STATUS
PING
```

BLE UUID：

- Service: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0001`
- RX / Write: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0002`
- TX / Notify: `7b7f3d10-7d20-4b8e-a2d7-4d55414c0003`

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\host\tests -v
.\.venv\Scripts\python.exe -m platformio run
```

GitHub Actions 会在 Ubuntu、Windows 和 macOS 上安装电脑侧依赖，检查传输模块导入与命令行入口，并运行单元测试；固件构建在 Ubuntu 上执行。v0.1.0 的 BLE/USB 实机验证环境为 Windows 11；macOS 路径使用 Bleak 的 CoreBluetooth 后端，并由 `macos-latest` 持续检查。

固件遵循官方引脚定义：GPIO 21 驱动两颗 WS2812，GPIO 40 以开漏低电平使能 LED 电源；GPIO 8/7 不会被配置成输出。

## 安全与 USB 标识说明

BLE 服务目前未加密，只传递灯效控制和状态消息。若未来需要传输敏感信息，应先增加认证与加密。

固件使用 Espressif VID `0x303A` 和开发用 PID `0x4010`，以便桥接程序区分应用固件和 ROM 下载模式。它适用于开发用途，不是商业产品可直接使用的已分配 USB 标识；商业产品应申请并使用合规的 USB VID/PID。

## 致谢与灵感来源

本项目的实体 Agent 状态灯概念和精简灯语受 MIT 协议项目 [starlight36/vibecoding-signal-light](https://github.com/starlight36/vibecoding-signal-light) 启发。本仓库针对 Chain DualKey 的 ESP32-S3、双 RGB LED、机械键、BLE GATT 和 USB CDC 重新实现，详见 [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md)。

硬件信息和下载流程来自 [M5Stack Chain DualKey 官方文档](https://docs.m5stack.com/en/chain/Chain_DualKey)及[官方 UserDemo](https://github.com/m5stack/M5DualKey-UserDemo)。

## 许可证

本仓库原创代码采用 [MIT License](LICENSE)。第三方依赖继续适用各自许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
