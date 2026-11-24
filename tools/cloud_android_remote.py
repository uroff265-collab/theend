#!/usr/bin/env python3
"""Temporary browser control panel for the TheEnd Android test emulator."""
import json, os, secrets, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
TOKEN=os.environ["THEEND_REMOTE_TOKEN"]; PORT=int(os.environ.get("THEEND_REMOTE_PORT","8765"))
PAGE=r"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>TheEnd Cloud Android</title><style>*{box-sizing:border-box}body{margin:0;background:#10151d;color:#eef2f7;font:15px system-ui}header{padding:12px 16px;background:#1c2634;position:sticky;top:0}main{max-width:720px;margin:auto;padding:12px}#screen{width:100%;max-height:75vh;object-fit:contain;background:#000;border-radius:10px;touch-action:none}button{background:#2c79d0;color:white;border:0;border-radius:8px;padding:10px 14px;margin:4px;font-size:14px}#status{color:#a9c4df;font-size:13px}input{padding:10px;width:100%;margin:5px 0;border-radius:8px;border:1px solid #526070;background:#18212d;color:white}</style></head><body><header><b>TheEnd — Cloud Android</b><div id="status">Connecting…</div></header><main><p>Tap the game screen to interact. Swipe to move. This is your temporary cloud Android device.</p><img id="screen" alt="Android emulator"><div><button onclick="key(4)">Back</button><button onclick="key(3)">Home</button><button onclick="key(82)">Menu</button><button onclick="refresh()">Refresh</button></div><input id="txt" placeholder="Text input (optional)"><button onclick="typeText()">Send text</button><p>If Last Asylum is not installed, its official Google Play listing is open on the emulator. Install it there and sign in only inside Google Play. Never send your password or verification code to anyone.</p></main><script>const k=new URLSearchParams(location.search).get('k')||'',img=document.getElementById('screen'),status=document.getElementById('status');let w=1080,h=1920,start=null;async function refresh(){try{let r=await fetch('/frame?k='+encodeURIComponent(k)+'&t='+Date.now());if(!r.ok)throw Error('HTTP '+r.status);let b=await r.blob(),u=URL.createObjectURL(b);img.onload=()=>URL.revokeObjectURL(u);img.src=u;w=img.naturalWidth;h=img.naturalHeight;status.textContent='Android connected · '+w+'×'+h}catch(e){status.textContent='Frame error: '+e}}async function send(a){let r=await fetch('/input?k='+encodeURIComponent(k),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(a)});if(!r.ok)status.textContent='Input error '+r.status;setTimeout(refresh,500)}function key(code){send({type:'key',code})}function typeText(){let t=document.getElementById('txt').value;if(t)send({type:'text',text:t})}img.addEventListener('pointerdown',e=>{let r=img.getBoundingClientRect();start={x:(e.clientX-r.left)*w/r.width,y:(e.clientY-r.top)*h/r.height};img.setPointerCapture(e.pointerId)});img.addEventListener('pointerup',e=>{if(!start)return;let r=img.getBoundingClientRect(),x=(e.clientX-r.left)*w/r.width,y=(e.clientY-r.top)*h/r.height;if(Math.hypot(x-start.x,y-start.y)>18)send({type:'swipe',x:start.x,y:start.y,x2:x,y2:y,ms:350});else send({type:'tap',x,y});start=null});refresh();setInterval(refresh,1300)</script></body></html>"""
class H(BaseHTTPRequestHandler):
 def log_message(self,*a): pass
 def auth(self): return secrets.compare_digest(parse_qs(urlparse(self.path).query).get("k",[""])[0],TOKEN)
 def reply(self,c,b,t):
  self.send_response(c);self.send_header("Content-Type",t);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):
  if not self.auth(): return self.reply(403,b"Forbidden","text/plain")
  p=urlparse(self.path).path
  if p=="/": return self.reply(200,PAGE.encode(),"text/html; charset=utf-8")
  if p=="/frame":
   try:
    r=subprocess.run(["adb","exec-out","screencap","-p"],capture_output=True,timeout=15,check=True)
    if not r.stdout.startswith(b"\x89PNG"): raise RuntimeError("Invalid screenshot")
    return self.reply(200,r.stdout,"image/png")
   except Exception as e: return self.reply(503,str(e).encode(),"text/plain")
  self.reply(404,b"Not found","text/plain")
 def do_POST(self):
  if not self.auth(): return self.reply(403,b"Forbidden","text/plain")
  if urlparse(self.path).path!="/input": return self.reply(404,b"Not found","text/plain")
  try:
   n=int(self.headers.get("Content-Length","0"))
   if n>4096: raise ValueError("Request too large")
   d=json.loads(self.rfile.read(n));t=d.get("type")
   if t=="tap": cmd=["adb","shell","input","tap",str(int(d["x"])),str(int(d["y"]))]
   elif t=="swipe": cmd=["adb","shell","input","swipe",*[str(int(d[k])) for k in ("x","y","x2","y2")],str(max(80,min(1200,int(d.get("ms",350)))))]
   elif t=="key":
    code=int(d["code"])
    if code not in (3,4,82,66,67): raise ValueError("Key not allowed")
    cmd=["adb","shell","input","keyevent",str(code)]
   elif t=="text": cmd=["adb","shell","input","text",str(d.get("text",""))[:120].replace(" ","%s")]
   else: raise ValueError("Unknown action")
   subprocess.run(cmd,capture_output=True,timeout=10,check=True);self.reply(200,b'{"ok":true}',"application/json")
  except Exception as e:self.reply(400,json.dumps({"error":str(e)}).encode(),"application/json")
if __name__=="__main__": ThreadingHTTPServer(("127.0.0.1",PORT),H).serve_forever()
