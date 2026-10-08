"""Loopback-only browser preview; stdlib HTTP, no OpenCV GUI dependency.

HTTP handlers queue observation commands; only the ROS thread applies them.
This module has no ROS imports, motor publishers or robot action services.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import queue
import threading
import time
from urllib.parse import urlsplit

from shirt_color_selector import COLORS

PAGE = """<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pupper 上衣顏色觀察</title>
<style>body{background:#15191f;color:#eee;font:18px sans-serif;margin:16px}
img{display:block;width:min(960px,100%);height:auto;background:#000}
button{font:inherit;padding:10px;margin:4px;border:0;border-radius:6px}
#status{white-space:pre-wrap;max-width:960px;padding:12px;background:#252b35}
.notice{color:#ffc45c}</style>
<h2>上衣顏色觀察 — 不控制馬達</h2>
<p class="notice">關閉網頁不會停止觀察程式；請在 SSH 終端機按 Ctrl+C。</p>
<div id="buttons"></div><button id="reset">重新選目標</button>
<div><button id="view-raw">原始相機（完整、無人物框）</button><button id="view-projected">校正畫面（人物框）</button></div>
<div id="status">等待相機資料…</div><img id="frame" alt="相機預覽">
<script src="/app.js"></script></html>""".encode("utf-8")

SCRIPT = r"""const colours={red:'紅',orange:'橘',yellow:'黃',green:'綠',blue:'藍',purple:'紫',black:'黑',white:'白',gray:'灰'};
const status=document.getElementById('status'),frame=document.getElementById('frame');
let view='raw';
document.getElementById('view-raw').onclick=()=>{view='raw';};
document.getElementById('view-projected').onclick=()=>{view='projected';};
async function send(body){try{const r=await fetch('/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());}catch(e){status.textContent='觀察請求失敗：'+e.message;}}
for(const [color,label]of Object.entries(colours)){const b=document.createElement('button');b.textContent=label+'色上衣';b.onclick=()=>send({color});document.getElementById('buttons').appendChild(b);}
document.getElementById('reset').onclick=()=>send({reset:true});
async function refresh(){try{const r=await fetch('/status.json',{cache:'no-store'});const s=await r.json();const raw=view==='raw',age=raw?s.raw_camera_age:s.camera_age;status.textContent=(raw?'原始相機：完整、無人物框':'校正畫面：人物框')+'\n目標：'+(colours[s.color]||s.color||'?')+'色上衣\n'+(s.state||'等待')+'：'+(s.reason||'')+'\n校正圖人物：'+(s.people??'?')+'，符合：'+(s.matches??'?')+'，相機延遲：'+(age??'?')+' 秒\n'+(s.wait_reason||'')+(s.server_age>1?'\n警告：預覽未更新':'');if(raw&&(age==null||age>0.30||age< -0.05)){frame.removeAttribute('src');status.textContent+='\n原始相機畫面未更新；不顯示舊畫面';}else{frame.src=(raw?'/raw.jpg':'/frame.jpg')+'?t='+Date.now();}}catch(e){frame.removeAttribute('src');status.textContent='預覽連線中斷：'+e.message;}finally{setTimeout(refresh,200);}}
refresh();""".encode("utf-8")


class AppearanceWebPreview:
    def __init__(self, port=8766, read_only=False):
        self.read_only = read_only
        self.page = PAGE
        if read_only:
            self.page = PAGE.decode("utf-8").replace(
                "上衣顏色觀察 — 不控制馬達", "外觀跟隨 — 實際控制模式／唯讀預覽").replace(
                "關閉網頁不會停止觀察程式；請在 SSH 終端機按 Ctrl+C。",
                "關閉預覽不會停止移動。使用手動 STOP 或在主啟動終端機 Ctrl+C；緊急情況用實體停止方式。"
            ).replace("</style>", "#buttons,#reset{display:none}</style>").encode("utf-8")
        self._lock = threading.Lock()
        self._jpeg = None
        self._raw_jpeg = None
        self._raw_updated = None
        self._raw_camera_age = None
        self._status = {}
        self._updated = time.monotonic()
        self._commands = queue.Queue(maxsize=16)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def allowed(self, mutation=False):
                self.connection.settimeout(2)
                host = self.headers.get("Host", "")
                if self.client_address[0] != "127.0.0.1" or host not in owner.hosts:
                    return False
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    return False
                origin = self.headers.get("Origin")
                if origin is not None and origin != "http://" + host:
                    return False
                return not mutation or origin == "http://" + host

            def respond(self, status, content_type, body):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self.allowed():
                    self.respond(403, "text/plain", b"Forbidden"); return
                path = urlsplit(self.path).path
                if path == "/":
                    self.respond(200, "text/html; charset=utf-8", owner.page)
                elif path == "/app.js":
                    self.respond(200, "text/javascript; charset=utf-8", SCRIPT)
                elif path == "/status.json":
                    with owner._lock:
                        status = dict(owner._status, server_age=time.monotonic() - owner._updated)
                        elapsed = None if owner._raw_updated is None else time.monotonic() - owner._raw_updated
                        status["raw_frame_age"] = elapsed
                        status["raw_camera_age"] = (None if elapsed is None else owner._raw_camera_age + elapsed)
                    self.respond(200, "application/json", json.dumps(status, allow_nan=False).encode())
                elif path in {"/frame.jpg", "/raw.jpg"}:
                    with owner._lock:
                        jpeg = owner._raw_jpeg if path == "/raw.jpg" else owner._jpeg
                    if jpeg is None:
                        self.respond(503, "text/plain", b"Waiting for preview frame")
                    else:
                        self.respond(200, "image/jpeg", jpeg)
                else:
                    self.respond(404, "text/plain", b"Not found")

            def do_POST(self):
                if owner.read_only:
                    self.respond(403, "text/plain", b"Execution preview is read-only"); return
                if not self.allowed(mutation=True):
                    self.respond(403, "text/plain", b"Forbidden"); return
                if self.path != "/command":
                    self.respond(404, "text/plain", b"Not found"); return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 1 <= length <= 128 or self.headers.get("Content-Type") != "application/json":
                        raise ValueError("Invalid body")
                    request = json.loads(self.rfile.read(length))
                    if not isinstance(request, dict):
                        raise ValueError("Invalid request")
                    if set(request) == {"color"} and request["color"] in COLORS:
                        command = ("color", request["color"])
                    elif set(request) == {"reset"} and request["reset"] is True:
                        command = ("reset", None)
                    else:
                        raise ValueError("Unsupported observation command")
                    owner._commands.put_nowait(command)
                except (ValueError, TypeError, queue.Full):
                    self.respond(400, "text/plain", b"Rejected observation request"); return
                self.respond(202, "application/json", b'{"queued":true,"mode":"OBSERVATION_ONLY"}')

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def update(self, jpeg, status):
        with self._lock:
            self._jpeg = bytes(jpeg)
            self._status = dict(status)
            self._updated = time.monotonic()

    def commands(self):
        requests = []
        while True:
            try:
                requests.append(self._commands.get_nowait())
            except queue.Empty:
                return requests

    def update_raw(self, jpeg, camera_age):
        # Latest original JPEG only: no projection, crop, boxes or ROS access here.
        if not math.isfinite(camera_age):
            raise ValueError("Invalid raw camera age")
        with self._lock:
            self._raw_jpeg = bytes(jpeg)
            self._raw_camera_age = float(camera_age)
            self._raw_updated = time.monotonic()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
