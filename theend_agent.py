#!/usr/bin/env python3
"""TheEnd Agent v7: local visual production-bubble detector for Last Asylum."""
import getpass, json, os, platform, re, shutil, subprocess, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET

BASE_URL=os.environ.get("THEEND_URL","https://theend-1.onrender.com").strip().rstrip("/")
ADB=os.environ.get("THEEND_ADB",r"C:\platform-tools\adb.exe" if os.name=="nt" else "adb").strip()
SERIAL=os.environ.get("THEEND_ADB_SERIAL","127.0.0.1:5555").strip()
DEVICE=os.environ.get("THEEND_DEVICE_NAME",platform.node() or "Android emulator")
SCAN_SECONDS=5
COMMAND_POLL_SECONDS=12
COOLDOWN=35

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    import io
    import cv2
    import numpy as np
    OCR=True
except ImportError:
    OCR=False
    cv2=None
    np=None

def token_value():
    token=os.environ.get("THEEND_AGENT_TOKEN","").strip()
    if not token and sys.platform=="win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,"Environment") as k:
                token,_=winreg.QueryValueEx(k,"THEEND_AGENT_TOKEN")
        except (OSError,ValueError): token=""
    if not token: token=getpass.getpass("THEEND_AGENT_TOKEN (ввод скрыт): ").strip()
    if not token: raise SystemExit("Не задан THEEND_AGENT_TOKEN.")
    return token

TOKEN=None

def adb(*args,timeout=6,binary=False):
    r=subprocess.run([ADB,"-s",SERIAL,*args],capture_output=True,timeout=timeout,check=True)
    return r.stdout if binary else r.stdout.decode("utf-8","replace")

def connected():
    try:
        r=subprocess.run([ADB,"devices"],capture_output=True,text=True,timeout=8,check=True)
        return any(x.split()[:2]==[SERIAL,"device"] for x in r.stdout.splitlines()[1:])
    except Exception: return False

def api(path,data=None):
    body=None if data is None else json.dumps(data).encode()
    headers={"Authorization":"Bearer "+TOKEN}
    if body is not None: headers["Content-Type"]="application/json"
    req=urllib.request.Request(BASE_URL+path,data=body,headers=headers,method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req,timeout=12) as r: return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code==401: raise RuntimeError("HTTP 401: токен не совпадает с THEEND_AGENT_TOKEN в Render.")
        raise RuntimeError("HTTP "+str(e.code)+" при запросе "+path)

def configure_ocr():
    if not OCR: raise SystemExit("Установи зависимости: py -m pip install pytesseract pillow opencv-python-headless")
    candidates=[shutil.which("tesseract"),r"C:\Program Files\Tesseract-OCR\tesseract.exe",r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
    for p in candidates:
        if p and (os.path.isfile(p) if os.path.isabs(p) else True):
            pytesseract.pytesseract.tesseract_cmd=p
            break

def screen_png():
    # Screen pixels are read into memory only; no screenshot files or uploads are created.
    b=adb("exec-out","screencap","-p",timeout=15,binary=True)
    if not b.startswith(b"\x89PNG"): raise RuntimeError("Некорректный кадр экрана от ADB.")
    return b

def recognize(png):
    im=Image.open(io.BytesIO(png)).convert("RGB")
    scale=1.5 if im.width<1200 else 1.2
    im=im.resize((int(im.width*scale),int(im.height*scale)))
    im=ImageOps.grayscale(im)
    im=ImageEnhance.Contrast(im).enhance(1.8).filter(ImageFilter.SHARPEN)
    langs=[]
    try:
        available=pytesseract.get_languages(config="")
        if "eng" in available and "rus" in available: langs.append("eng+rus")
        if "eng" in available: langs.append("eng")
        if "rus" in available: langs.append("rus")
    except Exception: langs=["eng"]
    if not langs: langs=["eng"]
    best=[]
    for lang in langs:
        for psm in (11,6):
            try:
                d=pytesseract.image_to_data(im,lang=lang,config=f"--oem 3 --psm {psm}",output_type=pytesseract.Output.DICT)
                words=[]
                for i,t in enumerate(d.get("text",[])):
                    t=re.sub(r"\s+"," ",t).strip()
                    try:
                        conf=float(d["conf"][i]); x=int(d["left"][i]); y=int(d["top"][i]); w=int(d["width"][i]); h=int(d["height"][i])
                    except (ValueError,TypeError,KeyError): continue
                    if t and conf>=65 and w>0 and h>0:
                        words.append({"text":t,"x":round((x+w/2)/scale),"y":round((y+h/2)/scale),"w":round(w/scale),"h":round(h/scale),"conf":conf})
                if sum(z["conf"] for z in words)>sum(z["conf"] for z in best): best=words
            except pytesseract.pytesseract.TesseractNotFoundError:
                raise RuntimeError("Tesseract OCR не найден. Установи его и перезапусти PowerShell.")
            except Exception: pass
    return best

def norm(s):
    return re.sub(r"[^a-zа-я0-9 ]+"," ",s.casefold().replace("ё","е")).strip()

SAFE={"collect","collect all","claim","claim all","gather","collect reward","claim reward",
      "собрать","собрать все","получить","забрать","забрать все","получить награду","забрать награду","собрать награду"}

def find_collection(png, words):
    # Last Asylum shows production rewards as floating white circular bubbles:
    # a resource icon inside the bubble and a numeric amount directly below it.
    # Detect the visual control, then require the nearby number to avoid tapping
    # unrelated circular menu buttons. All pixels stay in memory.
    if cv2 is None or np is None:
        raise RuntimeError("Нужен OpenCV: py -m pip install opencv-python-headless")
    raw=np.frombuffer(png,dtype=np.uint8)
    frame=cv2.imdecode(raw,cv2.IMREAD_COLOR)
    if frame is None: return None
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    circles=cv2.HoughCircles(cv2.medianBlur(gray,5),cv2.HOUGH_GRADIENT,
        dp=1.2,minDist=max(42,int(w*0.075)),param1=100,param2=28,
        minRadius=max(16,int(w*0.035)),maxRadius=max(42,int(w*0.105)))
    if circles is None: return None
    numeric=[]
    for z in words:
        t=re.sub(r"[^0-9.,KMBkmb]","",z["text"])
        if t and any(c.isdigit() for c in t):
            numeric.append(z)
    candidates=[]
    for cx,cy,rad in np.round(circles[0]).astype(int):
        if cy<max(45,int(h*0.06)) or cy>int(h*0.91): continue
        y0=max(0,cy-rad); y1=min(h,cy+rad)
        x0=max(0,cx-rad); x1=min(w,cx+rad)
        roi=hsv[y0:y1,x0:x1]
        if roi.size==0: continue
        # White outer bubble + colored resource artwork in its center.
        yy,xx=np.ogrid[:roi.shape[0],:roi.shape[1]]
        rr=np.sqrt((xx-(cx-x0))**2+(yy-(cy-y0))**2)
        ring=(rr>rad*0.66)&(rr<rad*0.98)
        center=rr<rad*0.58
        if ring.sum()<20 or center.sum()<20: continue
        white=np.mean((roi[:,:,1][ring]<85)&(roi[:,:,2][ring]>175))
        colorful=np.mean(roi[:,:,1][center]>55)
        if white<0.48 or colorful<0.12: continue
        # In the public game UI, the amount is printed immediately beneath
        # the floating production bubble. Require a nearby numeric OCR token.
        near=[z for z in numeric if abs(z["x"]-cx)<rad*1.25
              and rad*0.45 < z["y"]-cy < rad*2.4]
        if not near: continue
        amount=min(near,key=lambda z:abs(z["x"]-cx)+abs(z["y"]-(cy+rad*1.25)))
        candidates.append({"text":"production bubble "+amount["text"],
                           "x":int(cx),"y":int(cy),"conf":float(amount["conf"])})
    if not candidates: return None
    return max(candidates,key=lambda z:z["conf"])

def tap(x,y):
    s=adb("shell","wm","size")
    m=re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",s)
    if not m: raise RuntimeError("Не удалось определить размер экрана.")
    width,height=map(int,m.groups())
    if not (0<=x<width and 0<=y<height): raise ValueError("Координаты вне экрана.")
    adb("shell","input","tap",str(x),str(y))

def heartbeat(is_connected):
    api("/api/agent/heartbeat",{"deviceName":DEVICE,"emulatorConnected":is_connected})

def run_queued_command():
    try:
        c=api("/api/agent/commands/next").get("command")
        if not c: return
        ok=False
        try:
            if c.get("type")!="tap": raise ValueError("Неподдерживаемая команда.")
            s=adb("shell","wm","size"); m=re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",s)
            if not m: raise RuntimeError("Размер экрана не определён.")
            w,h=map(int,m.groups()); x=round(int(c["x"])*w/605); y=round(int(c["y"])*h/1070)
            tap(x,y); ok=True
            print(time.strftime("%H:%M:%S"),"Команда сайта выполнена.")
        except Exception as e: print("Команда не выполнена:",e)
        api("/api/agent/commands/"+str(c["id"])+"/result",{"ok":ok})
    except Exception as e: print("Очередь команд:",e)

def main():
    global TOKEN
    TOKEN=token_value(); configure_ocr()
    if not (shutil.which(ADB) or os.path.isfile(ADB)): raise SystemExit("ADB не найден: проверь C:\\platform-tools\\adb.exe")
    print("TheEnd Agent v7 запущен (поиск пузырей сбора по изображению + OCR числа).")
    print("Сервер:",BASE_URL,"| Эмулятор:",SERIAL)
    print("Автораспознавание включено: поиск круглых пузырей ресурсов + проверка числа под пузырём. Кадры только в памяти, без сохранения и отправки.")
    last_beat=last_scan=last_command_poll=0; last_key=None; last_action=0
    while True:
        now=time.time(); online=connected()
        if now-last_beat>=15:
            try:
                heartbeat(online); print(time.strftime("%H:%M:%S"),"Эмулятор:","подключён" if online else "не найден")
            except Exception as e:
                print("Связь с сервером:",e)
                if "401" in str(e): raise SystemExit("Исправь токен в Render и перезапусти агента.")
            last_beat=now
        if online:
            if now-last_scan>=SCAN_SECONDS:
                try:
                    png=screen_png()
                    words=recognize(png)
                    action=find_collection(png,words)
                    if action:
                        key=(norm(action["text"]),action["x"],action["y"])
                        if key!=last_key or now-last_action>=COOLDOWN:
                            tap(action["x"],action["y"])
                            print(time.strftime("%H:%M:%S"),"Сбор:",action["text"],f"({action['x']},{action['y']})")
                            last_key=key; last_action=now
                    else:
                        print(time.strftime("%H:%M:%S"),"Игра просканирована; кнопка сбора не найдена.")
                except Exception as e: print("Ошибка распознавания:",e)
                last_scan=now
            if now-last_command_poll>=COMMAND_POLL_SECONDS:
                run_queued_command()
                last_command_poll=now
        time.sleep(2)

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: print("\nTheEnd Agent остановлен.")
