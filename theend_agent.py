#!/usr/bin/env python3
"""TheEnd Agent v12: accessibility-grounded guarded automation."""
import getpass, json, os, platform, re, shutil, subprocess, sys, time, urllib.error, urllib.request
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
    # Pin the model directory in this process so every pytesseract call uses it.
    local=os.environ.get("LOCALAPPDATA","") if os.name=="nt" else ""
    preferred=os.path.join(local,"TheEnd","tessdata") if local else ""
    if preferred and os.path.isdir(preferred):
        os.environ["TESSDATA_PREFIX"]=preferred
    if not OCR: raise SystemExit("Установи зависимости: py -m pip install pytesseract pillow opencv-python-headless")
    candidates=[shutil.which("tesseract"),r"C:\Program Files\Tesseract-OCR\tesseract.exe",r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
    for p in candidates:
        if p and (os.path.isfile(p) if os.path.isabs(p) else True):
            pytesseract.pytesseract.tesseract_cmd=p
            break
    # Prefer the user's writable model folder; Program Files is often read-only.
    model_dirs=[]
    if os.name=="nt":
        local=os.environ.get("LOCALAPPDATA","")
        if local: model_dirs.append(os.path.join(local,"TheEnd","tessdata"))
    model_dirs.extend([os.path.join(os.path.dirname(pytesseract.pytesseract.tesseract_cmd),"tessdata")])
    for folder in model_dirs:
        if os.path.isdir(folder) and any(os.path.isfile(os.path.join(folder,n+".traineddata")) for n in ("eng","rus")):
            TESSDATA_ARGS='--tessdata-dir '+folder
            break
    try:
        available=pytesseract.get_languages(config=TESSDATA_ARGS)
        preferred=[x for x in ("eng","rus") if x in available]
        if preferred:
            print("OCR: языки", "+".join(preferred), "| модели:", TESSDATA_ARGS or "системная папка")
        else:
            print("OCR: языковые модели eng/rus не найдены; доступно:", ", ".join(available))
    except Exception as e:
        print("OCR: не удалось проверить модели:",e)

def screen_png():
    # Screen pixels are read into memory only; no screenshot files or uploads are created.
    b=adb("exec-out","screencap","-p",timeout=15,binary=True)
    if not b.startswith(b"\x89PNG"): raise RuntimeError("Некорректный кадр экрана от ADB.")
    return b

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
    im=Image.open(io.BytesIO(png)).convert("RGB")
    scale=1.5 if im.width<1200 else 1.2
    im=im.resize((int(im.width*scale),int(im.height*scale)))
    im=ImageOps.grayscale(im)
    im=ImageEnhance.Contrast(im).enhance(1.8).filter(ImageFilter.SHARPEN)
    langs=[]
    try:
        available=pytesseract.get_languages(config=TESSDATA_ARGS)
        if "eng" in available and "rus" in available: langs.append("eng+rus")
        if "eng" in available: langs.append("eng")
        if "rus" in available: langs.append("rus")
    except Exception: langs=["eng"]
    if not langs: langs=["eng"]
    best=[]
    errors=[]
    for lang in langs:
        for psm in (11,6,12):
            try:
                d=pytesseract.image_to_data(im,lang=lang,config=(TESSDATA_ARGS+f" --oem 3 --psm {psm}").strip(),output_type=pytesseract.Output.DICT)
                words=[]
                for i,t in enumerate(d.get("text",[])):
                    t=re.sub(r"\s+"," ",t).strip()
                    try:
                        conf=float(d["conf"][i]); x=int(d["left"][i]); y=int(d["top"][i]); w=int(d["width"][i]); h=int(d["height"][i])
                    except (ValueError,TypeError,KeyError): continue
                    if t and conf>=25 and w>0 and h>0:
                        words.append({"text":t,"x":round((x+w/2)/scale),"y":round((y+h/2)/scale),"w":round(w/scale),"h":round(h/scale),"conf":conf})
                if sum(z["conf"] for z in words)>sum(z["conf"] for z in best): best=words
            except pytesseract.pytesseract.TesseractNotFoundError:
                raise RuntimeError("Tesseract OCR не найден. Установи его и перезапусти PowerShell.")
            except Exception as e:
                errors.append(f"{lang}/psm{psm}: {type(e).__name__}: {e}")
    if not best and not getattr(recognize,"_reported",False):
        try:
            raw_text=pytesseract.image_to_string(im,lang=langs[0],
                config=(TESSDATA_ARGS+" --oem 3 --psm 3").strip())
        except Exception as e:
            raw_text=""
            errors.append("image_to_string: "+type(e).__name__+": "+str(e))
        gray_array=np.asarray(im) if np is not None else None
        pixel_info=("size="+str(im.size))
        if gray_array is not None:
            pixel_info += " gray_min="+str(int(gray_array.min()))+" gray_max="+str(int(gray_array.max()))+" gray_std="+str(round(float(gray_array.std()),1))
        print(time.strftime("%H:%M:%S"),"OCR пустой результат;",pixel_info,
              "| text:",repr(raw_text[:500]),"| errors:", " | ".join(errors[:3]) or "none")
        recognize._reported=True
    elif best and not getattr(recognize,"_reported",False):
        print(time.strftime("%H:%M:%S"),"OCR проверка: распознано слов:",len(best),
              "| примеры:", " ".join(z["text"] for z in best[:18]))
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
    if not candidates: return None
    return max(candidates,key=lambda z:z["conf"])

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


def interpret_task(instruction):
    text=norm(instruction)
    selected=[]
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
        if key=="offline_production":
            pending.append("Сбор производства пока отключён: распознавание верхней панели по OCR не подтверждает назначение кнопки. Нужна отдельная проверенная модель экрана.")
            continue
        if key not in SEMANTIC_MODULES:
            pending.append(key+": модуль ещё не реализован.")
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
    if not (shutil.which(ADB) or os.path.isfile(ADB)): raise SystemExit("ADB не найден: проверь C:\platform-tools\adb.exe")
    print("TheEnd Agent v13 запущен | build 2026-11-23-safe-task-dispatch")
    print("Сервер:",BASE_URL,"| Эмулятор:",SERIAL)
    print("Безопасный режим: только контекстные кнопки Android UI; слепые координаты и OCR-сбор отключены.")
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
                    print(time.strftime("%H:%M:%S"),"Настройки синхронизированы; включено модулей:",len(active_modules))
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