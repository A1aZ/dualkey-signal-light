# DualKey Signal Light

[![CI](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml/badge.svg)](https://github.com/A1aZ/dualkey-signal-light/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/A1aZ/dualkey-signal-light)](https://github.com/A1aZ/dualkey-signal-light/releases)

[English](README.md) | **简体中文**

把 [M5Stack Chain DualKey](https://docs.m5stack.com/en/chain/Chain_DualKey) 变成 Codex、Claude Code 和 Gemini CLI 共用的无线状态灯。

固件默认通过低功耗蓝牙连接。电脑上只运行一个常驻服务，由它独占设备连接、自动安装或更新检测到的 Agent 集成，并在用户登录时自动启动。

## 灯效含义

| 灯效 | 含义 |
| --- | --- |
| 绿→黄→红循环 | 一个或多个 Agent 正在工作 |
| 双黄闪烁 | 有结果或通知需要查看 |
| 双红双闪 | 权限、失败或其他阻塞需要处理 |
| 双绿短闪 | 最后一个活跃会话刚完成 |
| 双绿常亮 | 空闲 |
| 蓝色心跳 | 正在等待电脑侧服务连接 |
| 熄灭 | 已手动清除 |

## 1. 刷入 DualKey 固件

1. 从[最新 Release](https://github.com/A1aZ/dualkey-signal-light/releases/latest)下载 `dualkey-signal-light-v0.1.0.factory.bin`。
2. 将 DualKey 侧面开关拨到中间位置，然后拔掉 USB-C。
3. 按住离挂绳孔更远的 **Key 1**，重新接入 USB-C 数据线，再松开按键。
4. 用 Chrome 或 Edge 打开 Espressif 的[网页版烧录工具](https://espressif.github.io/esptool-js/)，连接新增的串口，把下载的固件添加到地址 `0x0`，然后开始烧录。
5. 烧录完成后拔掉 USB，再在不按按键的情况下重新连接。出现蓝色心跳灯就表示固件已就绪。

刷写会覆盖出厂固件。以后可用 M5Stack 官方的 [M5DualKey UserDemo](https://github.com/m5stack/M5DualKey-UserDemo) 恢复原始 Demo。固件校验值见 [dist/README.md](dist/README.md)。

## 2. 安装电脑常驻程序和 Hooks

从[最新 Release](https://github.com/A1aZ/dualkey-signal-light/releases/latest)下载与你电脑对应的安装包：

- Windows 10/11 x64：`dualkey-signal-light-0.2.0-windows-x64-setup.exe`
- Apple 芯片 Mac：`dualkey-signal-light-0.2.0-macos-arm64.pkg`
- Intel Mac：`dualkey-signal-light-0.2.0-macos-x64.pkg`

这个版本暂未提供 Linux 一键安装包；Linux 源码运行方式见[开发文档](docs/DEVELOPMENT.md)。

只需运行一次安装包，它会自动：

- 安装无需 Python 的电脑侧程序；
- 创建一个登录后自动启动的常驻服务；
- 优先使用 BLE，并在需要时回退到 USB；
- 检测 Codex、Claude Code 和 Gemini CLI；
- 合并或更新 DualKey Hooks，不覆盖其他 Hooks；
- 修改已有配置前自动创建备份。

请保持蓝牙开启，不需要先在系统蓝牙设置里手动配对。目前的社区版安装包尚未代码签名：Windows SmartScreen 拦截时请选择**更多信息 → 仍要运行**；macOS 首次使用时请允许蓝牙权限，如果 Gatekeeper 拦截尚未公证的安装包，请按住 Control 点击并选择**打开**，或前往**系统设置 → 隐私与安全性**允许打开。

### Codex 需要确认一次

Codex 要求用户检查非托管 Hooks。首次安装后，请在 Codex 中打开 `/hooks`，批准 DualKey Hooks，然后新建一个任务。Hooks 的写入与后续更新都由安装包完成；这个确认属于 Codex 的安全边界，安装程序不能静默绕过。

Claude Code 和 Gemini CLI 不需要这一步 Codex 专属确认。安装前已打开的 Agent 会话可能需要重启。如果以后才安装另一个受支持的 Agent，它会在下次登录时被自动检测；也可以直接再次运行 DualKey 安装包。

## 多 Agent、多会话如何避免冲突

Codex、Claude Code 和 Gemini CLI 可以同时安装、同时运行，但不会各自抢占蓝牙：

- 系统里只有一个常驻服务连接 DualKey；
- Hook 事件使用 `agent:session` 命名空间，相同的 session ID 也不会串线；
- 每个活跃会话独立保存状态；
- 最终显示按 `blocked > attention > working > idle` 聚合；
- 一个会话结束时，不会盖住另一个仍在工作或等待处理的会话；
- 红色或黄色提醒会保持，直到用户确认（或 Agent 发出受支持的会话结束事件）；
- 长按实体双键会全局清除所有会话。

因为两颗 LED 无法同时展示每个会话，所以设备始终显示当前最需要处理的状态。

## 双键操作

- **Key 1** 短按：确认提醒并回到空闲。
- **Key 2** 短按：依次预览全部灯效。
- **双键同时按住 1.5 秒**：清除全部会话并熄灯。

## 排查问题

- 蓝色心跳：固件正在运行，但电脑服务尚未连接。检查蓝牙，也可以接入 USB 作为备用连接。
- Agent 活动没有灯效：新建一个 Agent 会话；Codex 用户同时检查 `/hooks` 是否已批准。
- Windows 日志：`%USERPROFILE%\.dualkey-signal-light\bridge.log`
- macOS 日志：`~/.dualkey-signal-light/bridge.log`
- 安装包可以安全地重复运行；它只更新本项目管理的服务和 Hooks。

源码构建、架构、协议、测试、安装包制作以及新增 Agent 适配器，请参阅英文的[开发文档](docs/DEVELOPMENT.md)。

灵感来自 [starlight36/vibecoding-signal-light](https://github.com/starlight36/vibecoding-signal-light)。项目原创代码使用 [MIT License](LICENSE)，第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
