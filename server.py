#!/usr/bin/env python3
"""EG25-G Web 上位机 — 浏览器控制 4G 模块"""

import usb.core
import usb.util
import time
import json
import sys
import os
import threading

try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError:
    print("需要: pip3 install flask")
    sys.exit(1)

app = Flask(__name__, static_folder=None)

KNOWN_VID_PID = [
    (0x2c7c, 0x0125),
    (0x2c7c, 0x0124),
    (0x2ca3, 0x4006),
]

dev = None
dev_lock = threading.Lock()
sms_buffer = []


def find_device():
    for vid, pid in KNOWN_VID_PID:
        d = usb.core.find(idVendor=vid, idProduct=pid)
        if d is not None:
            return d
    return None


def init_device(d):
    try:
        d.set_configuration()
    except:
        pass


def at_cmd(cmd, timeout=8000):
    global dev
    try:
        while True:
            dev.read(0x84, 1024, timeout=200)
    except:
        pass
    data = (cmd + '\r\n').encode()
    with dev_lock:
        dev.write(0x03, data, timeout=min(timeout, 5000))
    time.sleep(1.5)
    result = []
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        try:
            chunk = dev.read(0x84, 4096, timeout=800)
            result.append(bytes(chunk).decode(errors='replace'))
        except usb.core.USBTimeoutError:
            break
        except Exception:
            break
    full = ''.join(result).strip()
    if full.startswith(cmd):
        full = full[len(cmd):].strip()
    return full


# ==================== API ====================

@app.route('/')
def index():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EG25-G Console</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Menlo,Monaco,monospace;background:#111;color:#0f0;min-height:100vh}
header{background:#1a1a1a;padding:12px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #333}
header h1{font-size:16px;color:#0f0}
nav{display:flex;gap:4px;padding:8px 12px;background:#151515;border-bottom:1px solid #333}
nav button{padding:6px 16px;border:1px solid #333;background:#1a1a1a;color:#0f0;cursor:pointer;font-size:12px;border-radius:3px}
nav button:hover,nav button.active{background:#0f0;color:#000;border-color:#0f0}
main{padding:12px;max-width:900px;margin:0 auto}
.panel{display:none}
.panel.active{display:block}
.card{background:#1a1a1a;border:1px solid #333;border-radius:4px;padding:12px;margin-bottom:12px}
.card h2{font-size:13px;color:#0f0;margin-bottom:8px;border-bottom:1px solid #333;padding-bottom:4px}
.info-grid{display:grid;grid-template-columns:1fr 2fr;gap:4px 12px;font-size:12px}
.info-grid .key{color:#888}
.info-grid .val{color:#0f0;word-break:break-all}
.at-input{display:flex;gap:8px}
.at-input input{flex:1;background:#000;border:1px solid #333;color:#0f0;padding:6px 10px;font:12px Menlo,monospace;border-radius:3px}
.at-input button{padding:6px 14px;background:#0f0;color:#000;border:none;font:12px Menlo,monospace;border-radius:3px;cursor:pointer}
#at-output{background:#000;border:1px solid #333;border-radius:3px;padding:10px;min-height:200px;max-height:400px;overflow-y:auto;font-size:11px;white-space:pre-wrap;margin-top:8px}
.mode-btns{display:flex;gap:8px;margin-bottom:12px}
.mode-btns button{padding:8px 20px;border:1px solid #333;background:#1a1a1a;color:#0f0;cursor:pointer;font-size:13px;border-radius:3px}
.mode-btns button:hover{background:#0f0;color:#000}
.mode-btns button.current{border:2px solid #0f0;font-weight:bold}
.sms-form{display:flex;flex-wrap:wrap;gap:8px}
.sms-form input{flex:1;min-width:140px;background:#000;border:1px solid #333;color:#0f0;padding:8px;font:12px Menlo,monospace;border-radius:3px}
.sms-form button{padding:8px 16px;background:#0f0;color:#000;border:none;font:12px Menlo,monospace;border-radius:3px;cursor:pointer}
#sms-log{background:#000;border:1px solid #333;border-radius:3px;padding:10px;min-height:100px;max-height:300px;overflow-y:auto;font-size:11px;margin-top:8px}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.online{background:#0f0}
.status-dot.offline{background:#f00}
.toast{position:fixed;top:12px;right:12px;padding:10px 20px;border-radius:3px;font-size:12px;z-index:99;display:none}
.toast.success{background:#0a0;color:#fff}
.toast.error{background:#c00;color:#fff}
</style>
</head>
<body>
<header>
  <h1><span class="status-dot" id="status-dot"></span>EG25-G Console</h1>
  <span style="font-size:11px;color:#666" id="device-badge"></span>
</header>
<nav>
  <button onclick="switchTab('dashboard')" class="active" id="tab-dashboard">仪表盘</button>
  <button onclick="switchTab('at')" id="tab-at">AT 终端</button>
  <button onclick="switchTab('mode')" id="tab-mode">模式切换</button>
  <button onclick="switchTab('sms')" id="tab-sms">短信</button>
</nav>
<main>
<div class="panel active" id="panel-dashboard">
  <div class="card"><h2>模块信息</h2><div class="info-grid" id="modinfo"></div></div>
  <div class="card"><h2>网络状态</h2><div class="info-grid" id="netinfo"></div></div>
  <div class="card"><h2>USB 接口</h2><div id="usbiface" style="font-size:11px"></div></div>
</div>
<div class="panel" id="panel-at">
  <div class="card"><h2>AT 命令</h2>
    <div class="at-input"><input id="at-cmd" placeholder="AT+CSQ" onkeydown="if(event.key=='Enter')sendAT()"><button onclick="sendAT()">发送</button></div>
    <div id="at-output"></div>
  </div>
</div>
<div class="panel" id="panel-mode">
  <div class="card"><h2>USB 网络模式</h2>
    <div class="mode-btns"><button onclick="switchMode('qmi')" id="btn-qmi">QMI (0)</button><button onclick="switchMode('ecm')" id="btn-ecm">ECM (1)</button><button onclick="switchMode('mbim')" id="btn-mbim">MBIM (2)</button></div>
    <div id="mode-status" style="font-size:12px;margin-top:8px"></div>
  </div>
</div>
<div class="panel" id="panel-sms">
  <div class="card"><h2>发短信</h2>
    <div class="sms-form"><input id="sms-phone" placeholder="手机号"><input id="sms-msg" placeholder="内容"><button onclick="sendSMS()">发送</button></div>
  </div>
  <div class="card"><h2>短信记录</h2>
    <button onclick="loadSMS()" style="margin-bottom:8px;padding:6px 14px;background:#1a1a1a;border:1px solid #333;color:#0f0;cursor:pointer;border-radius:3px">刷新</button>
    <div id="sms-log">点击"刷新"加载</div>
  </div>
</div>
</main>
<div class="toast" id="toast"></div>

<script>
let currentTab = 'dashboard';
async function api(endpoint, opts={}) {
  const r = await fetch(endpoint, {headers:{'Content-Type':'application/json'},...opts});
  return r.json();
}
function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type; t.style.display = 'block';
  setTimeout(()=>t.style.display='none', 2500);
}
function switchTab(name) {
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+name).classList.add('active');
  document.getElementById('tab-'+name).classList.add('active');
  currentTab = name;
  if(name=='dashboard') refreshDash();
  if(name=='mode') refreshMode();
}
async function refreshDash() {
  try{
    const d = await api('/api/info');
    if(d.error){document.getElementById('status-dot').className='status-dot offline';return}
    document.getElementById('status-dot').className='status-dot online';
    document.getElementById('device-badge').textContent = d.vendor + ' ' + d.model + ' | ' + d.firmware;
    document.getElementById('modinfo').innerHTML = d.info.map(i=>'<div class="key">'+i[0]+'</div><div class="val">'+i[1]+'</div>').join('');
    document.getElementById('netinfo').innerHTML = d.net.map(i=>'<div class="key">'+i[0]+'</div><div class="val">'+i[1]+'</div>').join('');
    document.getElementById('usbiface').textContent = d.usb_ifaces.join(' | ');
  }catch(e){}
}
async function refreshMode() {
  const d = await api('/api/info');
  if(d.error)return;
  const mode = d.usbnet;
  document.querySelectorAll('.mode-btns button').forEach(b=>b.classList.remove('current'));
  const map = {'0':'qmi','1':'ecm','2':'mbim'};
  const btn = document.getElementById('btn-'+map[mode]);
  if(btn) btn.classList.add('current');
  document.getElementById('mode-status').textContent = '当前: usbnet=' + mode;
}
async function switchMode(mode) {
  if(!confirm('切换 ' + mode + ' 模式？模块会重启，需等待约15秒。')) return;
  document.getElementById('mode-status').textContent = '切换中...';
  const r = await api('/api/mode', {method:'POST',body:JSON.stringify({mode})});
  toast(r.ok ? '已切换，等待重启...' : '失败: '+r.error);
}
async function sendAT() {
  const cmd = document.getElementById('at-cmd').value.trim();
  if(!cmd) return;
  const out = document.getElementById('at-output');
  const r = await api('/api/at', {method:'POST',body:JSON.stringify({cmd})});
  out.textContent += '> ' + cmd + '\n' + (r.result||r.error) + '\n\n';
  out.scrollTop = out.scrollHeight;
}
async function sendSMS() {
  const phone = document.getElementById('sms-phone').value.trim();
  const msg = document.getElementById('sms-msg').value.trim();
  if(!phone||!msg) return;
  const r = await api('/api/sms/send', {method:'POST',body:JSON.stringify({phone,msg})});
  toast(r.ok ? '已发送' : '失败: '+r.error);
}
async function loadSMS() {
  const r = await api('/api/sms/list');
  document.getElementById('sms-log').textContent = r.messages || '暂无短信';
}
refreshDash();
setInterval(()=>{if(currentTab=='dashboard')refreshDash()}, 5000);
</script>
</body>
</html>"""


@app.route('/api/info')
def api_info():
    global dev
    if dev is None:
        return jsonify({"error": "模块未连接"})

    try:
        items = []
        for cmd, label in [
            ("ATI", "模块"), ("AT+CGMI", "厂商"), ("AT+CGMM", "型号"),
            ("AT+CGMR", "固件"), ("AT+CGSN", "IMEI"), ("AT+QCCID", "ICCID"),
            ("AT+CPIN?", "SIM"), ("AT+CSQ", "信号"), ("AT+QNWINFO", "网络"),
            ("AT+QSPN", "运营商"), ("AT+QTEMP", "温度"),
        ]:
            r = at_cmd(cmd).replace('\r\n', ' ').replace('\r', ' ')[:100]
            items.append([label, r])

        net = [["IP", at_cmd("AT+CGPADDR=1")[:100].replace('\r\n', ' ')]]
        net.append(["PDP", at_cmd("AT+CGACT?")[:100].replace('\r\n', ' ')])

        ifaces = []
        for cfg in dev:
            for intf in cfg:
                cls = intf.bInterfaceClass
                sub = intf.bInterfaceSubClass
                labels = {(2,6): "ECM", (2,14): "MBIM", (224,1): "RNDIS",
                          (2,2): "ACM", (10,0): "CDC_Data", (255,255): "DM", (255,0): "Vendor"}
                ifaces.append(labels.get((cls, sub), f"c={cls}"))

        usbnet = at_cmd('AT+QCFG="usbnet"').strip()

        return jsonify({
            "vendor": dev.manufacturer or "?",
            "model": dev.product or "?",
            "firmware": at_cmd("AT+CGMR").strip(),
            "usbnet": usbnet.replace('+QCFG: "usbnet",', '').strip(),
            "info": items, "net": net, "usb_ifaces": ifaces,
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/at', methods=['POST'])
def api_at():
    global dev
    if dev is None:
        return jsonify({"error": "模块未连接"})
    cmd = request.json.get('cmd', 'AT')
    try:
        r = at_cmd(cmd)
        return jsonify({"result": r})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/mode', methods=['POST'])
def api_mode():
    global dev
    modes = {"qmi": 0, "ecm": 1, "mbim": 2, "rndis": 3}
    mode_name = request.json.get('mode', 'ecm')
    if mode_name not in modes:
        return jsonify({"error": f"未知模式: {mode_name}"})

    target = modes[mode_name]
    try:
        r = at_cmd(f'AT+QCFG="usbnet",{target}')
        if "OK" not in r:
            return jsonify({"error": r})
        try:
            dev.write(0x03, b'AT+CFUN=1,1\r\n', timeout=2000)
        except:
            pass
        time.sleep(10)
        global dev
        dev = find_device()
        return jsonify({"ok": f"已切到 {mode_name}"})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/sms/send', methods=['POST'])
def api_sms_send():
    global dev
    phone = request.json.get('phone', '')
    msg = request.json.get('msg', '')
    try:
        at_cmd("AT+CMGF=1")
        r = at_cmd(f'AT+CMGS="{phone}"')
        if ">" not in r:
            return jsonify({"error": r})
        dev.write(0x03, (msg + '\x1A').encode(), timeout=3000)
        time.sleep(3)
        result = at_cmd("", drain_first=False)
        return jsonify({"ok": "已发送" if "OK" in result else "可能失败", "detail": result})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/sms/list')
def api_sms_list():
    try:
        at_cmd("AT+CMGF=1")
        r = at_cmd('AT+CMGL="ALL"', timeout=10000)
        return jsonify({"messages": r})
    except Exception as e:
        return jsonify({"error": str(e)})


# ==================== 启动 ====================

def main():
    global dev
    print("EG25-G Console", flush=True)

    dev = find_device()
    if dev is None:
        print("⚠️ 未检测到模块，进入离线模式（部分功能不可用）")
    else:
        init_device(dev)
        print(f"✅ {dev.manufacturer} {dev.product} {hex(dev.idVendor)}:{hex(dev.idProduct)}")

    port = int(os.environ.get("PORT", 7878))
    print(f"打开浏览器: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
