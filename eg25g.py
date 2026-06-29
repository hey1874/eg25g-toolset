#!/usr/bin/env python3
"""
EG25-G Toolset — macOS/Linux 命令行工具
大疆 4G 模块 (Quectel EG25-G / Baiwang QDC507) 全能管理工具

依赖: brew install libusb && pip3 install pyusb

用法:
    python3 eg25g.py info         查看模块信息
    python3 eg25g.py at "AT+CSQ"  发送单条 AT 命令
    python3 eg25g.py mode ecm     切换 ECM 模式
    python3 eg25g.py mode qmi     切换 QMI 模式
    python3 eg25g.py mode mbim    切换 MBIM 模式
    python3 eg25g.py sms send <号码> <内容>  发短信
    python3 eg25g.py sms list              查看短信
    python3 eg25g.py shell                  交互式 AT 终端
    python3 eg25g.py pty                    创建虚拟串口 (PTY)
"""

import usb.core
import usb.util
import time
import sys
import os
import argparse
import threading
import signal

# ============================================================
# 底层 USB 通信
# ============================================================

KNOWN_VID_PID = [
    (0x2c7c, 0x0125),  # Quectel EC25
    (0x2c7c, 0x0124),  # Quectel EC21
    (0x2ca3, 0x4006),  # DJI 私有
]

AT_OUT_EP = 0x03  # AT 口 OUT 端点
AT_IN_EP = 0x84   # AT 口 IN 端点

running = True


def find_device():
    for vid, pid in KNOWN_VID_PID:
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is not None:
            return dev
    return None


def init_device(dev):
    try:
        dev.set_configuration()
    except:
        pass


def cleanup(dev):
    try:
        usb.util.dispose_resources(dev)
    except:
        pass


def at_cmd(dev, cmd, timeout=8000, drain_first=True):
    if drain_first:
        try:
            while True:
                dev.read(AT_IN_EP, 1024, timeout=200)
        except:
            pass

    data = (cmd + '\r\n').encode()
    dev.write(AT_OUT_EP, data, timeout=min(timeout, 5000))
    time.sleep(1.5)

    result = []
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        try:
            chunk = dev.read(AT_IN_EP, 4096, timeout=800)
            result.append(bytes(chunk).decode(errors='replace'))
        except usb.core.USBTimeoutError:
            break
        except Exception:
            break

    full = ''.join(result).strip()
    if full.startswith(cmd):
        full = full[len(cmd):].strip()
    return full


# ============================================================
# 功能模块
# ============================================================

def cmd_info(dev):
    """查看模块完整信息"""
    queries = [
        ("ATI", "模块信息"),
        ("AT+CGMI", "厂商"),
        ("AT+CGMM", "型号"),
        ("AT+CGMR", "固件版本"),
        ("AT+CGSN", "IMEI"),
        ("AT+QCCID", "ICCID"),
        ('AT+QCFG="usbnet"', "USB 网络模式"),
        ('AT+QCFG="usbcfg"', "USB VID/PID 配置"),
        ("AT+CPIN?", "SIM 状态"),
        ("AT+CSQ", "信号强度"),
        ("AT+QNWINFO", "当前网络"),
        ("AT+QSPN", "运营商"),
        ("AT+QTEMP", "温度"),
        ("AT+CGPADDR=1", "IP 地址"),
    ]

    print(f"{'='*50}")
    print(f"模块: {dev.manufacturer} {dev.product}")
    print(f"VID/PID: {hex(dev.idVendor)}:{hex(dev.idProduct)}")
    print(f"{'='*50}")

    for cmd, label in queries:
        r = at_cmd(dev, cmd).replace('\r\n', ' | ').replace('\r', ' ').replace('\n', ' ')
        print(f"  [{label}] {r[:120]}")

    print(f"\nUSB 接口:")
    for cfg in dev:
        for intf in cfg:
            cls = intf.bInterfaceClass
            sub = intf.bInterfaceSubClass
            labels = {(2,6): "ECM", (2,14): "MBIM", (224,1): "RNDIS",
                      (2,2): "ACM", (10,0): "CDC_Data", (255,255): "DM",
                      (255,0): "Vendor"}
            label = labels.get((cls, sub), f"class={cls}")
            print(f"    接口{intf.bInterfaceNumber}: {label}")


def cmd_at(dev, command):
    """发送单条 AT 命令"""
    r = at_cmd(dev, command)
    print(r)


def cmd_mode(dev, mode_name):
    """切换网络模式"""
    modes = {"qmi": 0, "ecm": 1, "mbim": 2, "rndis": 3}
    if mode_name not in modes:
        print(f"未知模式: {mode_name}。支持: {list(modes.keys())}")
        return

    target = modes[mode_name]
    current = at_cmd(dev, 'AT+QCFG="usbnet"')
    print(f"当前: {current}")

    r = at_cmd(dev, f'AT+QCFG="usbnet",{target}')
    print(f"切换: {r}")

    if "OK" in r:
        print("重启模块...")
        try:
            dev.write(AT_OUT_EP, b'AT+CFUN=1,1\r\n', timeout=2000)
        except:
            pass
        print("等待 10 秒后模块重新上线...")
        time.sleep(10)

        dev2 = find_device()
        if dev2:
            init_device(dev2)
            new_mode = at_cmd(dev2, 'AT+QCFG="usbnet"')
            print(f"新模式: {new_mode}")
        else:
            print("模块正在重启，稍后自行检查")
    else:
        print("切换失败")


def cmd_sms_send(dev, phone, message):
    """发送短信"""
    # 确保文本模式
    at_cmd(dev, "AT+CMGF=1", drain_first=True)

    # 发 CMGS
    r = at_cmd(dev, f'AT+CMGS="{phone}"')
    if ">" not in r:
        print(f"发送失败: {r}")
        return

    # 发消息体 + Ctrl+Z
    dev.write(AT_OUT_EP, (message + '\x1A').encode(), timeout=3000)
    time.sleep(5)

    result = at_cmd(dev, "", drain_first=False)
    if "OK" in result:
        print(f"✅ 短信已发送到 {phone}")
        print(f"   {result}")
    else:
        print(f"❌ 发送失败: {result}")


def cmd_sms_list(dev):
    """查看短信"""
    at_cmd(dev, "AT+CMGF=1")
    r = at_cmd(dev, 'AT+CMGL="ALL"', timeout=10000)
    if "OK" in r and len(r) > 3:
        print(r)
    else:
        print("收件箱为空（或无可读短信）")


def cmd_shell(dev):
    """交互式 AT 终端"""
    print("EG25-G AT Shell — 输入 'quit' 退出")
    while True:
        try:
            cmd = input("AT> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not cmd:
            continue
        if cmd.lower() in ("quit", "exit", "q"):
            break
        r = at_cmd(dev, cmd)
        print(r)


def cmd_pty(dev):
    """创建 PTY 虚拟串口桥接"""
    import os
    import threading
    import signal

    master_fd, slave_fd = os.openpty()
    slave_name = os.ttyname(slave_fd)
    print(f"虚拟串口: {slave_name}")
    print(f"连接: screen {slave_name}")
    print(f"退出: Ctrl+A Ctrl+\\")
    print(f"停止桥接: Ctrl+C")

    def usb_to_pty():
        global running
        while running:
            try:
                data = dev.read(AT_IN_EP, 4096, timeout=500)
                if data:
                    os.write(master_fd, bytes(data))
            except usb.core.USBTimeoutError:
                continue
            except Exception as e:
                if running:
                    print(f"\nUSB读错误: {e}", file=sys.stderr)
                break

    def pty_to_usb():
        global running
        while running:
            try:
                data = os.read(master_fd, 4096)
                if data:
                    dev.write(AT_OUT_EP, data, timeout=1000)
            except usb.core.USBTimeoutError:
                continue
            except OSError:
                break
            except Exception as e:
                if running:
                    print(f"\nUSB写错误: {e}", file=sys.stderr)
                break

    t1 = threading.Thread(target=usb_to_pty, daemon=True)
    t2 = threading.Thread(target=pty_to_usb, daemon=True)
    t1.start()
    t2.start()

    def shutdown(sig, frame):
        global running
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while t1.is_alive() or t2.is_alive():
            t1.join(1)
            t2.join(1)
    except KeyboardInterrupt:
        pass
    finally:
        global running
        running = False
        os.close(master_fd)
        os.close(slave_fd)
        print("已断开")


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="EG25-G Toolset")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("info", help="查看模块信息")

    p_at = sub.add_parser("at", help="发送 AT 命令")
    p_at.add_argument("cmd", type=str, help="AT 命令 (如 'AT+CSQ')")

    p_mode = sub.add_parser("mode", help="切换网络模式")
    p_mode.add_argument("mode", type=str, choices=["qmi", "ecm", "mbim", "rndis"])

    p_sms = sub.add_parser("sms", help="短信操作")
    p_sms_sub = p_sms.add_subparsers(dest="sms_cmd")
    p_sms_send = p_sms_sub.add_parser("send", help="发短信")
    p_sms_send.add_argument("phone", type=str)
    p_sms_send.add_argument("message", type=str)
    p_sms_sub.add_parser("list", help="查看短信")

    sub.add_parser("shell", help="交互式 AT 终端")
    sub.add_parser("pty", help="创建虚拟串口")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    dev = find_device()
    if dev is None:
        print("未找到 EG25-G 模块，检查 USB 连接", file=sys.stderr)
        sys.exit(1)

    init_device(dev)

    try:
        if args.command == "info":
            cmd_info(dev)
        elif args.command == "at":
            cmd_at(dev, args.cmd)
        elif args.command == "mode":
            cmd_mode(dev, args.mode)
        elif args.command == "sms":
            if args.sms_cmd == "send":
                cmd_sms_send(dev, args.phone, args.message)
            elif args.sms_cmd == "list":
                cmd_sms_list(dev)
        elif args.command == "shell":
            cmd_shell(dev)
        elif args.command == "pty":
            cmd_pty(dev)
    finally:
        cleanup(dev)


if __name__ == "__main__":
    main()
