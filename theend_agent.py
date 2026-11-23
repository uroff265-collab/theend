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
    global LAST_ACTION_EVENT
    s=adb("shell","wm","size")
    m=re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",s)
    if not m: raise RuntimeError("Не удалось определить размер экрана.")
    width,height=map(int,m.groups())
    if not (0<=x<width and 0<=y<height): raise ValueError("Координаты вне экрана.")
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
    },
    "golden_eggs": {
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

def run_semantic_modules(activities):
    outcomes=[]
    nodes=read_ui_nodes()
    visible=" ".join(n["label"] for n in nodes)
    for key,spec in SEMANTIC_MODULES.items():
        if activities.get(key) is not True: continue
        if nodes and any(norm(ctx) in visible for ctx in spec["context"]):
            matches=[n for n in nodes if n["clickable"] and n["enabled"]
                     and any(n["label"]==norm(action) for action in spec["actions"])]
            if len(matches)!=1:
                outcomes.append((key,False,"Не найдена единственная безопасная кнопка"))
                continue
            target=matches[0]; x,y=target["x"],target["y"]; label=target["label"]
        else:
            found=find_semantic_ocr_target({key:True})
            if not found:
                outcomes.append((key,False,"Нужный экран или кнопка не распознаны"))
                continue
            _,_,target=found; x,y=target["x"],target["y"]; label=target["text"]
        try:
            tap(x,y)
            print(time.strftime("%H:%M:%S"),"Модуль:",spec["label"],"— действие:",label)
            time.sleep(1.5)
            after=read_ui_nodes()
            after_labels=" ".join(n["label"] for n in after)
            changed=bool(after and label not in after_labels)
            outcomes.append((key,changed,"Элемент исчез/изменился" if changed else "Нажатие сделано, игровой результат пока не подтверждён"))
            print(time.strftime("%H:%M:%S"),"Проверка:",spec["label"],"—",outcomes[-1][2])
        except Exception as e:
            outcomes.append((key,False,"Ошибка: "+str(e)[:180]))
            print(time.strftime("%H:%M:%S"),"Модуль",spec["label"],"пропущен:",e)
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
        labels=sorted(set(n["label"] for n in nodes))
        if not labels:
            labels=sorted(set(norm(w["text"]) for w in words if w["conf"]>=75))
        if not labels: return 0
        signature="|".join(labels[:80])
        try:
            with open(GAME_MEMORY_PATH,"r",encoding="utf-8") as f: memory=json.load(f)
            if not isinstance(memory,dict): memory={}
        except (OSError,ValueError): memory={}
        screens=memory.setdefault("screens",{})
        entry=screens.get(signature,{"firstSeen":int(time.time()),"visits":0,"labels":labels,"controls":[]})
        entry["visits"]=int(entry.get("visits",0))+1
        entry["lastSeen"]=int(time.time())
        entry["resolution"]=[width,height]
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

def interpret_task(instruction):
    text=norm(instruction)
    selected=[]
    if any(x in text for x in ("ресурс","ресурсы","производств","собери город","collect resources","gather resources")):
        selected.append("town_production")
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
    selected=interpret_task(instruction)
    if not selected:
        return "needs_input","Пока не распознал задачу. Поддерживаемые команды: собрать ресурсы, забрать награды лагеря/святилища/золотых яиц, помочь альянсу."
    completed=[]
    pending=[]
    for key in selected:
        if key=="town_production":
            try:
                png=screen_png()
                words=recognize(png)
                action=find_collection(png,words)
                if action:
                    tap(action["x"],action["y"])
                    completed.append("нажал распознанный пузырь производства")
                else:
                    pending.append("пузырь сбора ресурсов не найден на текущем экране")
            except Exception as e:
                pending.append("ошибка анализа производства: "+str(e)[:180])
        else:
            outcomes=run_semantic_modules({key:True})
            outcome=next((item for item in outcomes if item[0]==key),None)
            if outcome and outcome[1]:
                completed.append("выполнено действие модуля "+key+" (элемент интерфейса изменился)")
            elif outcome:
                pending.append(key+": "+outcome[2])
            else:
                pending.append(key+": действие не выполнено")
    if completed and not pending:
        return "completed","Выполнено: "+"; ".join(completed)+"."
    if completed or pending:
        return "needs_input","Частично обработано. "+"; ".join(completed+pending)+"."
    return "needs_input","На текущем экране нет распознанной безопасной цели."

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
    if not (shutil.which(ADB) or os.path.isfile(ADB)): raise SystemExit("ADB не найден: проверь C:\\platform-tools\\adb.exe")
    print("TheEnd Agent v7 запущен (поиск пузырей сбора по изображению + OCR числа).")
    print("Сервер:",BASE_URL,"| Эмулятор:",SERIAL)
    print("Автораспознавание включено: поиск круглых пузырей ресурсов + проверка числа под пузырём. Кадры только в памяти, без сохранения и отправки.")
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
                    if activities.get("town_production") is True:
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
                            print(time.strftime("%H:%M:%S"),"Производство: пузырь сбора не найден.")
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
