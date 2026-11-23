#!/usr/bin/env python3
"""TheEnd Agent: Android ADB heartbeat and limited tap-command runner."""
import getpass
import base64
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import sys
import xml.etree.ElementTree as ET

BASE_URL = os.environ.get("THEEND_URL", "https://theend-1.onrender.com").strip().rstrip("/")
ADB = os.environ.get("THEEND_ADB", r"C:\platform-tools\adb.exe" if os.name == "nt" else "adb").strip()
ADB_SERIAL = os.environ.get("THEEND_ADB_SERIAL", "127.0.0.1:5555").strip()
DEVICE_NAME = os.environ.get("THEEND_DEVICE_NAME", platform.node() or "Android emulator")


def get_token():
    token = os.environ.get("THEEND_AGENT_TOKEN", "").strip()
    if not token and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                token, _ = winreg.QueryValueEx(key, "THEEND_AGENT_TOKEN")
            token = token.strip()
        except (OSError, ValueError):
            token = ""
    if token:
        print("Токен загружен из Windows.")
        return token

    token = getpass.getpass("Один раз вставьте THEEND_AGENT_TOKEN из Render (ввод скрыт): ").strip()
    if not token:
        raise SystemExit("Токен пустой. Запустите агента снова.")

    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "THEEND_AGENT_TOKEN", 0, winreg.REG_SZ, token)
            os.environ["THEEND_AGENT_TOKEN"] = token
            print("Токен сохранён в Windows. В следующий раз вводить его не нужно.")
        except OSError as error:
            print("Не удалось сохранить токен автоматически:", error)
    return token


TOKEN = None



# Optional OCR engine. Install with: py -m pip install pytesseract pillow
try:
    import pytesseract
    from PIL import Image
    import io
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

if OCR_AVAILABLE:
    for _candidate in (shutil.which("tesseract"), r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                       r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if _candidate and os.path.isfile(_candidate):
            pytesseract.pytesseract.tesseract_cmd = _candidate
            break


def capture_screen_png():
    """Capture emulator screen locally; never uploads it."""
    result = subprocess.run([ADB, "-s", ADB_SERIAL, "exec-out", "screencap", "-p"],
                            capture_output=True, timeout=15, check=True)
    if not result.stdout.startswith(b"\x89PNG"):
        raise RuntimeError("ADB вернул некорректный снимок экрана")
    return result.stdout


def ocr_game_screen(png_bytes):
    if not OCR_AVAILABLE:
        raise RuntimeError("OCR-библиотеки не установлены. Выполните: py -m pip install pytesseract pillow")
    try:
        image_obj = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        data = pytesseract.image_to_data(image_obj, lang="eng+rus", config="--psm 11",
                                         output_type=pytesseract.Output.DICT)
    except pytesseract.pytesseract.TesseractNotFoundError:
        raise RuntimeError("Не найден Tesseract OCR. Установите Tesseract OCR для Windows.")
    words = []
    for i, raw in enumerate(data.get("text", [])):
        label = re.sub(r"\s+", " ", raw).strip()
        try:
            confidence = float(data["conf"][i])
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
        except (ValueError, TypeError, KeyError):
            continue
        if label and confidence >= 65 and w > 0 and h > 0:
            words.append((label, x + w // 2, y + h // 2, confidence))
    return words


def find_ocr_collection_action(words):
    allowed = {"collect", "collect all", "claim", "claim all", "gather", "collect reward", "claim reward",
               "собрать", "собрать всё", "собрать все", "получить", "забрать", "забрать всё",
               "забрать все", "получить награду", "забрать награду", "получить всё", "получить все"}
    for label, x, y, confidence in words:
        normalized = re.sub(r"\\s+", " ", label.casefold()).strip(" .,:;!?")
        if normalized in allowed:
            return label, x, y, confidence
    return None



def adb(*args, timeout=8):
    return subprocess.run(
        [ADB, "-s", ADB_SERIAL, *args],
        capture_output=True, text=True, timeout=timeout, check=True
    )


def emulator_connected():
    try:
        result = subprocess.run(
            [ADB, "devices"], capture_output=True, text=True, timeout=8, check=True
        )
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[0] == ADB_SERIAL and fields[1] == "device":
                return True
        return False
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def request_json(path, data=None):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Authorization": "Bearer " + TOKEN}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE_URL + path,
        data=payload,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read().decode("utf-8")
            return json.loads(body or "{}")
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise RuntimeError(
                "HTTP 401: токен не совпадает с THEEND_AGENT_TOKEN в Render. "
                "Скопируйте значение из Render → Environment и запустите агента снова."
            ) from None
        raise RuntimeError(f"HTTP {error.code} при запросе {path}") from None


def heartbeat(connected):
    return request_json(
        "/api/agent/heartbeat",
        {"deviceName": DEVICE_NAME, "emulatorConnected": connected},
    )


def upload_screenshot():
    result = subprocess.run(
        [ADB, "-s", ADB_SERIAL, "exec-out", "screencap", "-p"],
        capture_output=True, timeout=12, check=True
    )
    encoded = base64.b64encode(result.stdout).decode("ascii")
    request_json("/api/agent/screenshot", {"image": encoded})
    print(time.strftime("%H:%M:%S"), "Снимок экрана отправлен в TheEnd.")



def read_game_ui():
    """Read Android accessibility hierarchy; screenshots stay local."""
    adb("shell", "uiautomator", "dump", "/sdcard/theend_window.xml", timeout=20)
    xml_text = adb("shell", "cat", "/sdcard/theend_window.xml", timeout=10).stdout
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    nodes = []
    for node in root.iter("node"):
        label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        bounds = node.attrib.get("bounds", "")
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if label and match:
            x1, y1, x2, y2 = map(int, match.groups())
            if x2 > x1 and y2 > y1:
                nodes.append((label, (x1 + x2) // 2, (y1 + y2) // 2))
    return nodes


def find_safe_game_action(nodes):
    """Activate only clearly labeled resource/reward collection controls."""
    allowed = {
        "collect", "collect all", "claim", "claim all", "gather",
        "собрать", "собрать всё", "собрать все", "получить", "забрать",
        "забрать всё", "забрать все", "получить награду", "забрать награду"
    }
    for label, x, y in nodes:
        normalized = re.sub(r"\s+", " ", label.casefold()).strip()
        if normalized in allowed:
            return label, x, y
    return None


def run_one_command():
    try:
        response = request_json("/api/agent/commands/next")
        command = response.get("command")
        if not command:
            return
        command_id = command.get("id")
        success = False
        try:
            if command.get("type") != "tap":
                raise ValueError("Неподдерживаемая команда")
            size_text = adb("shell", "wm", "size").stdout
            match = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", size_text)
            if not match:
                raise RuntimeError("Не удалось определить размер экрана эмулятора")
            width, height = int(match.group(1)), int(match.group(2))
            # Scale calibrated base coordinates to actual emulator resolution.
            x = round(int(command["x"]) * width / 605)
            y = round(int(command["y"]) * height / 1070)
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Координаты касания за пределами экрана")
            adb("shell", "input", "tap", str(x), str(y))
            success = True
            print(time.strftime("%H:%M:%S"), "Касание выполнено:", x, y)
        except Exception as error:
            print("Ошибка выполнения команды:", error)
        request_json("/api/agent/commands/" + str(command_id) + "/result", {"ok": success})
        # Let the game react before the next queued tap.
        time.sleep(1.5)
    except Exception as error:
        print("Ошибка командного сервиса:", error)


def main():
    global TOKEN
    TOKEN = get_token()

    if not shutil.which(ADB) and not os.path.isfile(ADB):
        raise SystemExit(
            "ADB не найден. Установите Android platform-tools или задайте THEEND_ADB "
            "полным путём к adb.exe."
        )

    print("TheEnd Agent запущен.")
    print("Сервер:", BASE_URL)
    print("Эмулятор:", ADB_SERIAL)
    print("Не закрывайте это окно PowerShell.")

    last_heartbeat = 0
    last_ui_scan = 0
    last_action_key = ""
    last_action_at = 0
    while True:
        connected = emulator_connected()
        now = time.time()
        if now - last_heartbeat >= 15:
            try:
                heartbeat(connected)
                print(
                    time.strftime("%H:%M:%S"),
                    "Эмулятор:",
                    "подключён" if connected else "не найден",
                )
            except Exception as error:
                print("Ошибка связи:", error)
                if "HTTP 401" in str(error):
                    raise SystemExit("Исправьте токен в Render и перезапустите агента.")
            last_heartbeat = now

        if connected:
            if now - last_ui_scan >= 6:
                try:
                    nodes = read_game_ui()
                    action = find_safe_game_action(nodes)
                    if action:
                        label, x, y = action
                        action_key = f"a11y:{label}:{x}:{y}"
                        if action_key != last_action_key or now - last_action_at >= 45:
                            adb("shell", "input", "tap", str(x), str(y))
                            print(time.strftime("%H:%M:%S"), f"Автодействие (Android UI): {label} ({x},{y})")
                            last_action_key, last_action_at = action_key, now
                    else:
                        if nodes:
                            labels = [label for label, _, _ in nodes[:5]]
                            print(time.strftime("%H:%M:%S"), "Android UI:", " | ".join(labels))
                        png = capture_screen_png()
                        words = ocr_game_screen(png)
                        ocr_action = find_ocr_collection_action(words)
                        if ocr_action:
                            label, x, y, confidence = ocr_action
                            action_key = f"ocr:{label}:{x}:{y}"
                            if action_key != last_action_key or now - last_action_at >= 45:
                                adb("shell", "input", "tap", str(x), str(y))
                                print(time.strftime("%H:%M:%S"), f"Автодействие (OCR {confidence:.0f}%): {label} ({x},{y})")
                                last_action_key, last_action_at = action_key, now
                        elif words:
                            preview = [w[0] for w in words[:12]]
                            print(time.strftime("%H:%M:%S"), f"OCR: распознано {len(words)} слов: " + " | ".join(preview))
                        else:
                            print(time.strftime("%H:%M:%S"), "OCR: текст на экране не распознан; снимок остаётся на компьютере.")
                except Exception as error:
                    print("Ошибка анализа игрового интерфейса:", error)
                last_ui_scan = now
            run_one_command()
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\nTheEnd Agent остановлен.")
