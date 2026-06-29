# EG25-G Toolset

大疆 4G 模块 (Quectel EG25-G / Baiwang QDC507) macOS/Linux 全能管理工具。

**不用 Linux 也能改 VID/PID、切模式、收发短信。**

## 功能

- **VID/PID 修改** — 纯 Python + libusb，macOS 上直接改，无需 Linux
- **模式切换** — QMI(0) / ECM(1) / MBIM(2)
- **发短信** — 文本模式收发
- **AT 命令** — 交互式终端、单条命令
- **PTY 桥接** — 映射虚拟串口，screen 直连
- **模块信息** — 一键查询

## 安装

```bash
# macOS
brew install libusb
pip3 install pyusb

# Linux
sudo apt install libusb-1.0-0-dev
pip3 install pyusb
```

## 用法

```bash
python3 eg25g.py info              # 查看模块信息
python3 eg25g.py at "AT+CSQ"       # 发 AT 命令
python3 eg25g.py mode ecm          # 切 ECM（macOS 直插上网）
python3 eg25g.py mode qmi          # 切 QMI（Linux/VoHive）
python3 eg25g.py sms send 13800138000 "hello"  # 发短信
python3 eg25g.py sms list          # 看短信
python3 eg25g.py shell             # 交互式 AT 终端
python3 eg25g.py pty               # 虚拟串口
```

## macOS 上改 VID/PID（无需 Linux）

```bash
# 1. 插上模块，确认 USB 识别
system_profiler SPUSBDataType | grep -A3 "0x2ca3"

# 2. 发 AT 改 VID/PID
python3 -c "
import usb.core, time
dev = usb.core.find(idVendor=0x2ca3, idProduct=0x4006)
dev.set_configuration()

def at(cmd):
    data = (cmd + '\r\n').encode()
    dev.write(0x03, data, timeout=5000)
    time.sleep(1.5)
    return bytes(dev.read(0x84, 4096, timeout=5000)).decode(errors='replace')

print(at('AT'))
print(at('AT+QCFG=\"usbcfg\",0x2C7C,0x0125,1,1,1,1,1,0,0'))
dev.write(0x03, b'AT+CFUN=1,1\r\n', timeout=2000)
print('完成，模块重启为新 VID/PID')
"

# 3. 验证
system_profiler SPUSBDataType | grep "0x2c7c"
```

原理：Python + libusb 绕过操作系统驱动，直接通过 USB bulk endpoint 发 AT 命令。

## 模块信息

| 项目 | 值 |
|------|-----|
| 芯片 | 高通 MDM9x07 |
| LTE | Cat 4, 150M/50M |
| 模式 | QMI ✅ / ECM ✅ / MBIM ⚠️ / RNDIS ❌ |
| GNSS | GPS+GLONASS+北斗+伽利略 |

## License

MIT
