#!/usr/bin/env python3
"""TheEnd Agent v19: visual resource detection and guarded automation."""
import base64, csv, getpass, io, json, os, platform, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from theend_vision import parse_hierarchy, choose_action, analyze_screen

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

TESSDATA_ARGS=""

def configure_ocr():
    global TESSDATA_ARGS
    if not OCR: raise SystemExit("Установи зависимости: py -m pip install pillow opencv-python-headless numpy")
    local=os.environ.get("LOCALAPPDATA","") if os.name=="nt" else ""
    folder=os.path.join(local,"TheEnd","tessdata") if local else ""
    if not folder or not os.path.isdir(folder):
        folder=os.path.join(os.path.dirname(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),"tessdata")
    if folder and os.path.isdir(folder):
        os.environ["TESSDATA_PREFIX"]=folder
    candidates=[shutil.which("tesseract"),r"C:\Program Files\Tesseract-OCR\tesseract.exe",r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
    exe=next((p for p in candidates if p and (os.path.isfile(p) if os.path.isabs(p) else True)),None)
    if not exe: raise SystemExit("Tesseract OCR не найден.")
    pytesseract.pytesseract.tesseract_cmd=exe
    # Use Tesseract's CLI directly. This avoids pytesseract's Windows argument quoting
    # and language-list parsing issues when the user profile path contains spaces.
    env=os.environ.copy()
    try:
        result=subprocess.run([exe,"--list-langs"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15,env=env)
        output=(result.stdout or "")+"\n"+(result.stderr or "")
        available=[x.strip() for x in output.splitlines() if x.strip() in ("eng","rus")]
        if result.returncode!=0 or not available:
            raise RuntimeError(output.strip() or "Tesseract не вернул список языков.")
        from PIL import ImageDraw
        probe=Image.new("RGB",(480,100),"white")
        ImageDraw.Draw(probe).text((12,25),"THEEND OCR TEST 123",fill="black")
        buf=io.BytesIO(); probe.save(buf,format="PNG")
        test=subprocess.run([exe,"stdin","stdout","-l","eng","--oem","3","--psm","7"],
            input=buf.getvalue(),capture_output=True,timeout=20,env=env)
        test_text=test.stdout.decode("utf-8","replace").strip()
        if test.returncode!=0 or not test_text:
            err=test.stderr.decode("utf-8","replace")
            raise RuntimeError("Тест OCR не пройден: "+(err or test_text or "пустой результат"))
        print("OCR: языки", "+".join(available), "| Tesseract CLI | тест:", repr(test_text))
    except Exception as e:
        raise SystemExit("Ошибка настройки OCR: "+str(e))

def screen_png():
    # Prefer binary streaming. Some Windows/LDPlayer ADB builds return an empty
    # or damaged PNG through exec-out, so retry through a device-side file.
    try:
        b=adb("exec-out","screencap","-p",timeout=20,binary=True)
        if b.startswith(b"\x89PNG") and len(b)>4096:
            Image.open(io.BytesIO(b)).verify()
            return b
    except Exception:
        pass
    remote="/sdcard/theend_capture.png"
    local=os.path.join(tempfile.gettempdir(),"theend_capture.png")
    try:
        adb("shell","screencap","-p",remote,timeout=20)
        subprocess.run([ADB,"-s",SERIAL,"pull",remote,local],capture_output=True,timeout=20,check=True)
        with open(local,"rb") as f: b=f.read()
        if not b.startswith(b"\x89PNG"): raise RuntimeError("fallback capture is not PNG")
        Image.open(io.BytesIO(b)).verify()
        return b
    except Exception as e:
        raise RuntimeError("Не удалось получить кадр экрана ни через exec-out, ни через файл: "+str(e)[:180])

def get_screen_size():
    """Return active emulator resolution, falling back to PNG dimensions."""
    try:
        output=adb("shell","wm","size",timeout=8)
        matches=re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",output,re.I)
        if matches: return tuple(map(int,matches[-1]))
        matches=re.findall(r"(\d{3,5})x(\d{3,5})",output)
        if matches: return tuple(map(int,matches[-1]))
    except Exception:
        pass
    try:
        png=screen_png()
        if png[:8]==b"\x89PNG\r\n\x1a\n" and len(png)>=24:
            width=int.from_bytes(png[16:20],"big")
            height=int.from_bytes(png[20:24],"big")
            if width>0 and height>0: return width,height
    except Exception:
        pass
    raise RuntimeError("Не удалось определить размер экрана через ADB (wm size и PNG). Проверь подключение LDPlayer.")

def recognize(png):
    """OCR fallback pipeline for Unity game screens with small, outlined HUD text."""
    source=Image.open(io.BytesIO(png)).convert("RGB")
    scale=2.0 if source.width<1600 else 1.5
    source=source.resize((int(source.width*scale),int(source.height*scale)),Image.Resampling.LANCZOS)
    gray=ImageOps.grayscale(source)
    gray=ImageOps.autocontrast(gray,cutoff=1)
    gray=ImageEnhance.Sharpness(ImageEnhance.Contrast(gray).enhance(2.0)).enhance(1.5)

    variants=[("gray",gray)]
    # Unity text often has thin outlines over a textured background. Add
    # thresholded and inverted variants only when the normal OCR finds nothing.
    best=[]; errors=[]; attempts=[]
    exe=pytesseract.pytesseract.tesseract_cmd
    env=os.environ.copy()

    def run_variant(image, name, psm):
        buf=io.BytesIO(); image.save(buf,format="PNG")
        result=subprocess.run([exe,"stdin","stdout","-l","eng+rus",
            "--oem","3","--psm",str(psm),"tsv"],input=buf.getvalue(),
            capture_output=True,timeout=25,env=env)
        if result.returncode!=0:
            raise RuntimeError(result.stderr.decode("utf-8","replace")[:300])
        rows=csv.DictReader(io.StringIO(result.stdout.decode("utf-8","replace")),delimiter="\t")
        found=[]
        for row in rows:
            value=re.sub(r"\s+"," ",(row.get("text") or "")).strip()
            try:
                conf=float(row.get("conf","-1"))
                x=int(row["left"]); y=int(row["top"]); w=int(row["width"]); h=int(row["height"])
            except (ValueError,TypeError,KeyError):
                continue
            # Low-confidence words are retained for screen observation only.
            # Any action still requires exact labels and high confidence.
            if value and conf>=8 and w>0 and h>0:
                found.append({"text":value,"x":round((x+w/2)/scale),
                    "y":round((y+h/2)/scale),"w":round(w/scale),
                    "h":round(h/scale),"conf":conf})
        return found

    for psm in (11,6,12):
        try:
            found=run_variant(gray,"gray",psm)
            attempts.append((f"gray/psm{psm}",len(found)))
            if sum(z["conf"] for z in found)>sum(z["conf"] for z in best):
                best=found
            if len(best)>=3:
                break
        except Exception as e:
            errors.append(f"gray/psm{psm}: {type(e).__name__}: {e}")

    if not best:
        fallback=[]
        if cv2 is not None and np is not None:
            arr=np.asarray(gray)
            try:
                otsu=cv2.threshold(arr,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
                adaptive=cv2.adaptiveThreshold(arr,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,31,11)
                fallback=[("otsu",Image.fromarray(otsu)),
                          ("otsu_inv",Image.fromarray(255-otsu)),
                          ("adaptive",Image.fromarray(adaptive)),
                          ("adaptive_inv",Image.fromarray(255-adaptive))]
            except Exception as e:
                errors.append("preprocess: "+str(e)[:200])
        for name,image in fallback:
            for psm in (11,6):
                try:
                    found=run_variant(image,name,psm)
                    attempts.append((f"{name}/psm{psm}",len(found)))
                    if sum(z["conf"] for z in found)>sum(z["conf"] for z in best):
                        best=found
                    if len(best)>=3:
                        break
                except Exception as e:
                    errors.append(f"{name}/psm{psm}: {type(e).__name__}: {e}")
            if len(best)>=3:
                break

    # Merge near-duplicate tokens from overlapping OCR layouts.
    unique=[]
    for word in sorted(best,key=lambda z:(-z["conf"],z["y"],z["x"])):
        if not any(word["text"].casefold()==old["text"].casefold()
                   and abs(word["x"]-old["x"])<max(12,word["w"])
                   and abs(word["y"]-old["y"])<max(12,word["h"])
                   for old in unique):
            unique.append(word)
    best=sorted(unique,key=lambda z:(z["y"],z["x"]))

    if not best and not getattr(recognize,"_reported",False):
        gray_array=np.asarray(gray) if np is not None else None
        pixel_info=("size="+str(gray.size))
        if gray_array is not None:
            pixel_info += " gray_min="+str(int(gray_array.min()))+" gray_max="+str(int(gray_array.max()))+" gray_std="+str(round(float(gray_array.std()),1))
        print(time.strftime("%H:%M:%S"),"OCR пустой результат;",pixel_info,
              "| попытки:",attempts,"| errors:", " | ".join(errors[:3]) or "none")
        recognize._reported=True
    elif best and not getattr(recognize,"_reported",False):
        print(time.strftime("%H:%M:%S"),"OCR проверка: распознано слов:",len(best),
              "| примеры:", " ".join(z["text"] for z in best[:24]),
              "| попытки:",attempts)
        recognize._reported=True
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
        # Resource bubbles are on the central town map, not in the side HUD.
        # Ignore top resource counters, left/right menus and bottom chat controls.
        if not (int(w*0.18) <= cx <= int(w*0.82)): continue
        if not (int(h*0.25) <= cy <= int(h*0.76)): continue
        if rad < int(w*0.028) or rad > int(w*0.075): continue
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
        # The actual town collection bubbles have a pale/white rim and a
        # green leaf/resource icon in the middle. Use green HSV pixels rather
        # than accepting any colorful circular map decoration.
        white=np.mean((roi[:,:,1][ring]<100)&(roi[:,:,2][ring]>180))
        center_hsv=roi[center]
        green=np.mean((center_hsv[:,0]>=25)&(center_hsv[:,0]<=100)&
                      (center_hsv[:,1]>55)&(center_hsv[:,2]>65))
        if white<0.42 or green<0.10: continue
        # Amount OCR is unreliable on small floating labels in this game's
        # isometric map. The distinctive green leaf inside a pale bubble is
        # the primary signal; nearby amount is optional metadata, not a gate.
        near=[z for z in numeric if abs(z["x"]-cx)<rad*1.5
              and rad*0.35 < z["y"]-cy < rad*2.8]
        amount=min(near,key=lambda z:abs(z["x"]-cx)+abs(z["y"]-(cy+rad*1.2))) if near else None
        label=("production bubble "+amount["text"]) if amount else "green resource bubble"
        confidence=float(amount["conf"]) if amount else float(green*100)
        candidates.append({"text":label,"x":int(cx),"y":int(cy),"conf":confidence})
    # Return every distinct candidate from this single screenshot, strongest first.
    candidates.sort(key=lambda z:z["conf"],reverse=True)
    unique=[]
    for item in candidates:
        if all(abs(item["x"]-old["x"])>max(18,rad*0.55) or
               abs(item["y"]-old["y"])>max(18,rad*0.55) for old in unique):
            unique.append(item)
    return unique


# Cropped from the actual Last Asylum screenshot: wheat icon inside floating green reward badge.
WHEAT_ICON_TEMPLATE_B64="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"

LAST_WHEAT_DIAG=0

def find_visual_resource_badges(png):
    """Search the playable town area at multiple scales; return observations, never taps."""
    global LAST_WHEAT_DIAG
    if cv2 is None or np is None: return []
    frame=cv2.imdecode(np.frombuffer(png,dtype=np.uint8),cv2.IMREAD_COLOR)
    if frame is None: return []
    h,w=frame.shape[:2]
    template=cv2.imdecode(np.frombuffer(base64.b64decode(WHEAT_ICON_TEMPLATE_B64),dtype=np.uint8),cv2.IMREAD_COLOR)
    if template is None: return []
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    # Search the full playable town, not just the upper HUD strip.
    x0,x1=int(w*.06),int(w*.94)
    y0,y1=int(h*.025),int(h*.84)
    roi=gray[y0:y1,x0:x1]
    base_scale=w/900.0
    candidates=[]
    for factor in (0.65,0.75,0.85,0.95,1.0,1.05,1.15,1.25,1.4,1.55):
        tw=max(12,int(template.shape[1]*base_scale*factor))
        th=max(12,int(template.shape[0]*base_scale*factor))
        if roi.shape[0]<th or roi.shape[1]<tw: continue
        scaled=cv2.resize(template,(tw,th),interpolation=cv2.INTER_CUBIC)
        templ=cv2.cvtColor(scaled,cv2.COLOR_BGR2GRAY)
        scores=cv2.matchTemplate(roi,templ,cv2.TM_CCOEFF_NORMED)
        work=scores.copy()
        for _ in range(4):
            _,score,_,loc=cv2.minMaxLoc(work)
            if not np.isfinite(score) or score<0.48: break
            cx=x0+loc[0]+tw//2
            cy=y0+loc[1]+th//2
            candidates.append({"x":int(cx),"y":int(cy),"confidence":round(float(score),3),
                               "scale":round(float(factor),2),"w":tw,"h":th})
            xx,yy=loc
            cv2.rectangle(work,(max(0,xx-tw//2),max(0,yy-th//2)),
                          (min(work.shape[1]-1,xx+tw//2),min(work.shape[0]-1,yy+th//2)),-1,-1)
    # Non-maximum suppression across scales.
    candidates.sort(key=lambda z:z["confidence"],reverse=True)
    unique=[]
    for item in candidates:
        if all(abs(item["x"]-old["x"])>max(item["w"],old["w"])*0.65 or
               abs(item["y"]-old["y"])>max(item["h"],old["h"])*0.65 for old in unique):
            unique.append(item)
        if len(unique)>=8: break
    now=time.time()
    if now-LAST_WHEAT_DIAG>=15:
        summary="; ".join(f'({z["x"]},{z["y"]})={z["confidence"]:.3f}@{z["scale"]}' for z in unique[:5])
        print(time.strftime("%H:%M:%S"),"Диагностика значка: поиск по игровому полю",
              f"{w}x{h}","| лучшие кандидаты:",summary or "совпадений нет",
              "| порог действия 0.620 + подтверждение тремя кадрами")
        LAST_WHEAT_DIAG=now
    return unique

LAST_VISUAL_TAPS={}
PENDING_WHEAT_TARGET=None
WHEAT_CONFIRMATIONS=0

def run_visual_resource_collection():
    """Scan resource-bubble candidates and report only visually verified disappearances."""
    global PENDING_WHEAT_TARGET,WHEAT_CONFIRMATIONS,LAST_WHEAT_DIAG
    try:
        png=screen_png()
        targets=find_collection(png,[])
        initial_count=len(targets)
        now=time.time()
        if not targets:
            if now-LAST_WHEAT_DIAG>=15:
                print(time.strftime("%H:%M:%S"),
                      "Поиск ресурсов: на текущем кадре подходящих значков не найдено.")
                LAST_WHEAT_DIAG=now
            PENDING_WHEAT_TARGET=None
            WHEAT_CONFIRMATIONS=0
            return {"found":0,"attempted":0,"visually_confirmed":0,"reason":"no_candidates"}
        w,h=get_screen_size()
        print(time.strftime("%H:%M:%S"),"Один проход сканирования:",
              len(targets),"кандидат(ов):",
              "; ".join(f'({z["x"]},{z["y"]}) {z["conf"]:.1f}%' for z in targets[:8]))
        collected=0
        attempts=0
        while targets and attempts<5:
            target=next((z for z in targets
                if time.time()-LAST_VISUAL_TAPS.get(
                    f'{round(z["x"]/w*100)}:{round(z["y"]/h*100)}',0)>=120),None)
            if target is None: break
            key=f'{round(target["x"]/w*100)}:{round(target["y"]/h*100)}'
            print(time.strftime("%H:%M:%S"),"Пробую собрать ресурс:",
                  f'({target["x"]},{target["y"]})')
            tap(target["x"],target["y"])
            LAST_VISUAL_TAPS[key]=time.time()
            attempts+=1
            time.sleep(1.0)
            targets=find_collection(screen_png(),[])
            still=any(abs(z["x"]-target["x"])<w*.04
                      and abs(z["y"]-target["y"])<h*.04
                      for z in targets)
            if still:
                print(time.strftime("%H:%M:%S"),
                      "Сбор НЕ подтверждён: значок остался на месте; повтор заблокирован на 120 секунд.")
                break
            collected+=1
            print(time.strftime("%H:%M:%S"),
                  "Визуально подтверждено: значок исчез или изменился после нажатия.")
        print(time.strftime("%H:%M:%S"),"Итог цикла сбора:",
              "подтверждено",collected,"| найдено изначально",initial_count)
        PENDING_WHEAT_TARGET=None
        WHEAT_CONFIRMATIONS=0
        return {"found":initial_count,"attempted":attempts,"visually_confirmed":collected,
                "reason":"visual_change" if collected else "not_confirmed"}
    except Exception as e:
        print(time.strftime("%H:%M:%S"),"Визуальный сбор ресурсов:",str(e)[:200])
        return {"found":0,"attempted":0,"visually_confirmed":0,"reason":"error: "+str(e)[:240]}


def tap(x,y):
    global LAST_ACTION_EVENT
    width,height=get_screen_size()
    x,y=int(round(x)),int(round(y))
    if not (0<=x<width and 0<=y<height):
        raise ValueError(f"Координаты ({x},{y}) вне экрана {width}x{height}.")
    adb("shell","input","tap",str(x),str(y))
    LAST_ACTION_EVENT={"x":int(x),"y":int(y),"at":int(time.time())}

# Conservative semantic automation: only click a unique, clickable Android UI node
# when the matching activity title and a safe action label are both visible.
SEMANTIC_MODULES = {
    "exploration_camp": {
        "context": ("лагерь разведки", "exploration camp"),
        "actions": ("забрать", "получить", "claim", "collect"),
        "label": "Лагерь разведки"
    },
    "sanctuary": {
        "context": ("святилище", "sanctuary"),
        "actions": ("собрать", "получить", "collect", "claim"),
        "label": "Святилище"
    },
    "alliance_help": {
        "context": ("помощь альянсу", "alliance help"),
        "actions": ("помочь всем", "помочь", "help all", "help"),
        "label": "Помощь альянсу"
    },    "golden_eggs": {
        "context": ("золотые яйца", "golden eggs"),
        "actions": ("забрать", "получить", "claim", "collect"),
        "label": "Золотые яйца"
    }
}

def read_ui_nodes():
    # Android accessibility hierarchy is read directly; no screenshot is saved.
    try:
        adb("shell", "uiautomator", "dump", "/sdcard/theend-window.xml", timeout=12)
        raw=adb("shell", "cat", "/sdcard/theend-window.xml", timeout=8)
        root=ET.fromstring(raw)
        nodes=[]
        for node in root.iter("node"):
            text_value=norm(node.attrib.get("text",""))
            desc=norm(node.attrib.get("content-desc",""))
            label=(text_value+" "+desc).strip()
            if not label: continue
            bounds=node.attrib.get("bounds","")
            match=re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",bounds)
            if not match: continue
            x1,y1,x2,y2=map(int,match.groups())
            nodes.append({"label":label,"x":(x1+x2)//2,"y":(y1+y2)//2,
                          "clickable":node.attrib.get("clickable")=="true",
                          "enabled":node.attrib.get("enabled","true")=="true"})
        return nodes
    except Exception:
        return []

def ocr_lines(words):
    lines=[]
    for word in sorted(words,key=lambda z:(z["y"],z["x"])):
        row=next((v for v in lines if abs(v["y"]-word["y"])<=max(12,word["h"])),None)
        if row is None:
            row={"y":word["y"],"words":[]}; lines.append(row)
        row["words"].append(word)
    result=[]
    for row in lines:
        row["words"].sort(key=lambda z:z["x"])
        result.append({"text":" ".join(w["text"] for w in row["words"]),
                       "x":sum(w["x"] for w in row["words"])//len(row["words"]),
                       "y":row["y"],
                       "conf":sum(w["conf"] for w in row["words"])/len(row["words"])})
    return result

def find_semantic_ocr_target(activities):
    try:
        words=recognize(screen_png())
    except Exception:
        return None
    lines=ocr_lines(words)
    screen_text=" | ".join(norm(line["text"]) for line in lines)
    for key,spec in SEMANTIC_MODULES.items():
        if activities.get(key) is not True: continue
        if not any(norm(ctx) in screen_text for ctx in spec["context"]): continue
        candidates=[line for line in lines
                    if any(norm(line["text"])==norm(action) for action in spec["actions"])
                    and line["conf"]>=75]
        if len(candidates)==1:
            return key,spec,candidates[0]
    return None

LAST_SEMANTIC_SCREEN={}

def run_semantic_modules(activities):
    """Execute at most once per unchanged screen for each enabled activity."""
    outcomes=[]
    try:
        adb("shell","uiautomator","dump","/sdcard/theend-window.xml",timeout=12)
        raw=adb("shell","cat","/sdcard/theend-window.xml",timeout=8)
        nodes=parse_hierarchy(raw)
    except Exception as e:
        print("Семантические модули: дерево интерфейса недоступно; нажатий нет:",str(e)[:160])
        return outcomes
    signature=tuple((n.label,n.bounds,n.clickable,n.enabled) for n in nodes)
    for key,spec in SEMANTIC_MODULES.items():
        if activities.get(key) is not True: continue
        if LAST_SEMANTIC_SCREEN.get(key)==signature:
            continue
        target,reason=choose_action(key,nodes)
        if target is None:
            outcomes.append((key,False,"Безопасная цель не подтверждена: "+reason))
            continue
        try:
            x,y=target.center
            tap(x,y)
            LAST_SEMANTIC_SCREEN[key]=signature
            print(time.strftime("%H:%M:%S"),"Модуль:",spec["label"],"— точная кнопка:",target.label)
            time.sleep(1.5)
            adb("shell","uiautomator","dump","/sdcard/theend-window.xml",timeout=12)
            after=parse_hierarchy(adb("shell","cat","/sdcard/theend-window.xml",timeout=8))
            changed=[(n.label,n.bounds,n.enabled) for n in nodes] != [(n.label,n.bounds,n.enabled) for n in after]
            detail="ui_changed_result_unconfirmed" if changed else "Интерфейс не изменился; повторное нажатие на этом экране заблокировано."
            outcomes.append((key,changed,detail))
        except Exception as e:
            outcomes.append((key,False,"Ошибка выполнения: "+str(e)[:160]))
    return outcomes

GAME_MEMORY_PATH=os.path.join(os.path.dirname(os.path.abspath(__file__)),"theend_game_memory.json")
LAST_SCREEN_SIGNATURE=None
LAST_ACTION_EVENT=None

def learn_screen():
    global LAST_SCREEN_SIGNATURE,LAST_ACTION_EVENT
    # Persist only extracted UI labels and relative control positions, never image pixels.
    try:
        nodes=read_ui_nodes()
        png=screen_png()
        words=recognize(png)
        im=Image.open(io.BytesIO(png))
        width,height=im.size
        screen_state=analyze_screen(words,width,height)
        # Unity exposes only a generic "Game view" accessibility node.
        # Do not let that placeholder hide the OCR text that describes the real game screen.
        labels=sorted(set(n["label"] for n in nodes
                          if norm(n["label"]) not in ("game view","gameview","")))
        ocr_labels=sorted(set(norm(w["text"]) for w in words if w["conf"]>=25 and norm(w["text"])))
        if ocr_labels:
            labels=sorted(set(labels + ocr_labels))
        if not labels:
            print(time.strftime("%H:%M:%S"),"Экран пока не размечен: accessibility nodes=",
                  [n["label"] for n in nodes[:8]],"| OCR слов=",len(words))
            return 0
        signature="|".join(labels[:80])
        if signature != LAST_SCREEN_SIGNATURE:
            screen_info=screen_state.get("screen",{})
            print(time.strftime("%H:%M:%S"),"Распознан экран:",screen_info.get("type","unknown"),
                  "| уверенность:",screen_info.get("confidence",0),
                  "| признаки:",", ".join(screen_info.get("evidence",[])) or "нет")
            if screen_info.get("type") == "unknown":
                print("OCR диагностика:", " | ".join(line["text"] for line in screen_state.get("lines",[])[:24]) or "текст не распознан")
            suggestions=screen_state.get("action_suggestions",[])
            if suggestions:
                print("Кандидаты кнопок задания (пока без нажатия):",
                      "; ".join(item["label"] for item in suggestions[:6]))
        try:
            with open(GAME_MEMORY_PATH,"r",encoding="utf-8") as f: memory=json.load(f)
            if not isinstance(memory,dict): memory={}
        except (OSError,ValueError): memory={}
        screens=memory.setdefault("screens",{})
        entry=screens.get(signature,{"firstSeen":int(time.time()),"visits":0,"labels":labels,"controls":[]})
        entry["visits"]=int(entry.get("visits",0))+1
        entry["lastSeen"]=int(time.time())
        entry["resolution"]=[width,height]
        entry["screenState"]=screen_state
        entry["controls"]=[{"label":n["label"],"x":round(n["x"]/width,4),"y":round(n["y"]/height,4),
                            "clickable":n["clickable"],"enabled":n["enabled"]}
                           for n in nodes if n["clickable"]]
        screens[signature]=entry
        if LAST_SCREEN_SIGNATURE and LAST_SCREEN_SIGNATURE!=signature and LAST_ACTION_EVENT:
            transitions=memory.setdefault("transitions",[])
            transitions.append({"from":LAST_SCREEN_SIGNATURE,"to":signature,
                                "action":LAST_ACTION_EVENT,"at":int(time.time())})
            memory["transitions"]=transitions[-1000:]
        LAST_SCREEN_SIGNATURE=signature
        LAST_ACTION_EVENT=None
        memory["updatedAt"]=int(time.time())
        # Keep the local knowledge base bounded.
        if len(screens)>300:
            ordered=sorted(screens.items(),key=lambda pair:pair[1].get("lastSeen",0),reverse=True)
            memory["screens"]=dict(ordered[:300])
        temp=GAME_MEMORY_PATH+".tmp"
        with open(temp,"w",encoding="utf-8") as f: json.dump(memory,f,ensure_ascii=False)
        os.replace(temp,GAME_MEMORY_PATH)
        return len(screens)
    except Exception as e:
        print("Обучение экрана:",e)
        return 0

def heartbeat(is_connected):
    api("/api/agent/heartbeat",{"deviceName":DEVICE,"emulatorConnected":is_connected})

def get_agent_config():
    data=api("/api/agent/config")
    activities=data.get("activities") or {}
    if not isinstance(activities,dict): activities={}
    return activities

def run_queued_command():
    """Drain legacy dashboard tap commands without executing blind coordinates."""
    try:
        c=api("/api/agent/commands/next").get("command")
        if not c: return
        api("/api/agent/commands/"+str(c["id"])+"/result",{"ok":False})
        print(time.strftime("%H:%M:%S"),"Старая команда координат отклонена: требуется распознанная игровая цель.")
    except Exception as e:
        print("Очередь команд:",e)

def scaled_tap(x, y, ref_w=900, ref_h=1600):
    w,h=get_screen_size()
    tap(round(x*w/ref_w),round(y*h/ref_h))

def swipe_up():
    w,h=get_screen_size()
    adb("shell","input","swipe",str(round(w*.5)),str(round(h*.78)),
        str(round(w*.5)),str(round(h*.28)),"650")

def detect_top_food_icon(png, words):
    """Find the first resource counter in the top HUD and infer its adjacent icon."""
    width,height=Image.open(io.BytesIO(png)).size
    counters=[]
    for word in words:
        token=re.sub(r"[^0-9.,KMBkmb]","",word["text"])
        if word["y"] < height*0.12 and any(ch.isdigit() for ch in token):
            counters.append(word)
    if not counters: return None
    counters.sort(key=lambda z:z["x"])
    first=counters[0]
    x=int(first["x"]-max(first["w"]*0.95,width*0.035))
    y=int(first["y"])
    if not (0<=x<width and 0<=y<height*0.12): return None
    return {"x":x,"y":y,"counter":first["text"],"confidence":first["conf"]}

def collect_offline_production():
    """Use live HUD/OCR detection and refuse ambiguous taps."""
    png=screen_png()
    words=recognize(png)
    anchor=detect_top_food_icon(png,words)
    if not anchor:
        return False,"Не смог определить значок ресурса на верхней панели. Ничего не нажимал."
    print(time.strftime("%H:%M:%S"),"Производство: найден счётчик",anchor["counter"],"значок:",anchor["x"],anchor["y"])
    tap(anchor["x"],anchor["y"])
    time.sleep(2.0)
    for page in range(4):
        lines=ocr_lines(recognize(screen_png()))
        joined=" | ".join(norm(x["text"]) for x in lines)
        print(time.strftime("%H:%M:%S"),"Производство: экран",page+1,"|",joined[:500])
        context=any(k in joined for k in ("офлайн","offline","сбор продукции","производств","награда","продукц"))
        claims=[x for x in lines if any(k in norm(x["text"]) for k in ("собрать","забрать","получить","claim","collect"))]
        if context and len(claims)==1:
            before=joined
            target=claims[0]
            tap(target["x"],target["y"])
            time.sleep(2.0)
            after=" | ".join(norm(x["text"]) for x in ocr_lines(recognize(screen_png())))
            if after!=before: return True,"Нажата кнопка сбора; интерфейс изменился: "+after[:240]
            return False,"Нажатие не подтвердилось изменением экрана. Повторно не нажимал."
        if not context: return False,"Панель офлайн-продукции не подтверждена. Ничего не нажимал."
        if page<3:
            w,h=get_screen_size()
            adb("shell","input","swipe",str(round(w*.5)),str(round(h*.78)),str(round(w*.5)),str(round(h*.38)),"550")
            time.sleep(1.0)
    return False,"Кнопка сбора не найдена однозначно. Ничего не нажимал."


def diagnose_game_screen():
    """Observe the current game screen and return OCR/classification without tapping."""
    png=screen_png()
    words=recognize(png)
    width,height=get_screen_size()
    report=analyze_screen(words,width,height)
    screen=report.get("screen") or {}
    lines=[str(x.get("text","")).strip() for x in report.get("lines",[]) if str(x.get("text","")).strip()]
    summary=" | ".join(lines[:14])[:900]
    screen_name=screen.get("type","unknown")
    confidence=screen.get("confidence",0)
    evidence=", ".join(screen.get("evidence",[])) or "нет"
    return ("completed",
        f"Диагностика экрана завершена. Экран: {screen_name} (уверенность {confidence}). "
        f"Разрешение: {width}x{height}. Признаки: {evidence}. "
        f"Распознанный текст: {summary or 'текст не распознан'}. Никаких нажатий не выполнялось.")


def interpret_task(instruction):
    text=norm(instruction)
    selected=[]
    if any(x in text for x in ("диагностик","проверь экран","что на экране","распознай экран","screen status","diagnose screen")):
        selected.append("screen_diagnostics")
    if any(x in text for x in ("офлайн","offline","сбор продукции","награда","значок зерна","собери ресурсы","ресурс","ресурсы","производств","собери город","collect resources","gather resources")):
        selected.append("offline_production")
    intents={
        "exploration_camp":("лагер","развед","exploration camp"),
        "sanctuary":("святилищ","sanctuary"),
        "alliance_help":("помощ альянс","помоги альянс","help alliance"),
        "golden_eggs":("золот яйц","golden egg")
    }
    for key,terms in intents.items():
        if any(term in text for term in terms): selected.append(key)
    return list(dict.fromkeys(selected))

def execute_task(instruction, activities):
    """Run only implemented, screen-confirmed accessibility actions.

    OCR-only production taps are intentionally disabled: the game's Unity
    canvas does not reliably expose those controls through Android UIAutomator.
    """
    selected=interpret_task(instruction)
    if not selected:
        return "needs_input","Задача не распознана. Доступны только модули с подтверждаемым экраном: лагерь разведки, святилище, помощь альянсу, золотые яйца."
    completed=[]
    pending=[]
    for key in selected:
        if key=="screen_diagnostics":
            try:
                status,result=diagnose_game_screen()
                if status=="completed": completed.append(result)
                else: pending.append(result)
            except Exception as e:
                pending.append("Диагностика экрана: "+str(e)[:300])
            continue
        if key=="offline_production":
            if activities.get("town_production") is not True:
                pending.append("Сбор ресурсов: сначала включи модуль «Производство города» в настройках.")
                continue
            outcome=run_visual_resource_collection()
            if outcome.get("visually_confirmed",0)>0:
                completed.append("Сбор ресурсов: визуально исчезло значков "+str(outcome["visually_confirmed"])+
                                 " из "+str(outcome.get("found",0))+
                                 "; серверное начисление ресурсов игрой не подтверждено")
            elif outcome.get("reason")=="no_candidates":
                pending.append("Сбор ресурсов: на экране не найдено подходящих значков; нажатий не было.")
            else:
                pending.append("Сбор ресурсов не подтверждён: "+str(outcome.get("reason","неизвестная причина"))+
                               ". Найдено кандидатов: "+str(outcome.get("found",0))+
                               ", попыток: "+str(outcome.get("attempted",0))+".")
            continue
        if key not in SEMANTIC_MODULES:
            pending.append(key+": модуль ещё не реализован.")
            continue
        if activities.get(key) is not True:
            pending.append(key+": модуль выключен в настройках автоматизации.")
            continue
        outcome=run_semantic_modules({key:True})
        item=next((x for x in outcome if x[0]==key),None)
        if item and item[1] and item[2]=="ui_changed_result_unconfirmed":
            pending.append(key+": интерфейс изменился, но получение награды сервером игры не подтверждено.")
        elif item:
            pending.append(key+": "+item[2])
        else:
            pending.append(key+": экран или безопасная кнопка не распознаны; действий не было.")
    if completed and not pending:
        return "completed","Выполнено: "+"; ".join(completed)+"."
    return "needs_input","Проверка завершена. "+"; ".join(pending)+"."

def poll_game_task(activities):
    try:
        task=api("/api/agent/tasks/next").get("task")
        if not task: return
        print(time.strftime("%H:%M:%S"),"Получена задача:",task.get("instruction",""))
        try:
            status,result=execute_task(task.get("instruction",""),activities)
        except Exception as e:
            status,result="failed","Ошибка выполнения: "+str(e)[:500]
        api("/api/agent/tasks/"+str(task["id"])+"/result",{"status":status,"result":result})
        print(time.strftime("%H:%M:%S"),"Результат задачи:",status,"—",result)
    except Exception as e:
        print(time.strftime("%H:%M:%S"),"Очередь ИИ:",e)

def main():
    global TOKEN
    TOKEN=token_value(); configure_ocr()
    if not (shutil.which(ADB) or os.path.isfile(ADB)): raise SystemExit(r"ADB не найден: проверь C:\platform-tools\adb.exe")
    print("TheEnd Agent v19 запущен | build 2026-11-24-wheat-diagnostics")
    print("Сервер:",BASE_URL,"| Эмулятор:",SERIAL)
    print("Режим: поиск игровых значков ресурсов по изображению; OCR не используется для поиска значков.")
    last_beat=last_scan=last_command_poll=last_config_poll=last_task_poll=0; last_key=None; last_action=0; activities={}; active_modules=()
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
            if now-last_config_poll>=30:
                try:
                    activities=get_agent_config()
                    active_modules=tuple(k for k,v in activities.items() if v is True)
                    print(time.strftime("%H:%M:%S"),"Настройки синхронизированы; включено модулей:",len(active_modules),"|",", ".join(active_modules) if active_modules else "все выключены в панели сайта")
                except Exception as e:
                    print("Не удалось обновить настройки модулей:",e)
                last_config_poll=now
            if now-last_scan>=SCAN_SECONDS:
                try:
                    known_screens=learn_screen()
                    if known_screens:
                        print(time.strftime("%H:%M:%S"),"Память игры:",known_screens,"изученных экранов")
                    # Safety: do not guess resource bubbles from circle geometry.
                    # The former background scanner clicked unrelated HUD controls.
                    # Production actions must use an explicit task with UI verification.
                    run_semantic_modules(activities)
                    if activities.get('town_production') is True:
                        run_visual_resource_collection()
                except Exception as e: print("Ошибка игрового цикла:",e)
                last_scan=now
            if now-last_command_poll>=COMMAND_POLL_SECONDS:
                run_queued_command()
                last_command_poll=now
            if now-last_task_poll>=8:
                poll_game_task(activities)
                last_task_poll=now
        time.sleep(2)

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: print("\nTheEnd Agent остановлен.")