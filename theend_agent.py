#!/usr/bin/env python3
"""TheEnd Agent: Android ADB heartbeat and limited tap-command runner."""
import getpass
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("THEEND_URL", "https://theend-1.onrender.com").strip().rstrip("/")
ADB = os.environ.get("THEEND_ADB", "adb").strip()
ADB_SERIAL = os.environ.get("THEEND_ADB_SERIAL", "127.0.0.1:5555").strip()
DEVICE_NAME = os.environ.get("THEEND_DEVICE_NAME", platform.node() or "Android emulator")


def get_token():
    # Always ask at launch: avoids silently reusing an old/stale environment token.
    token = getpass.getpass("Вставьте THEEND_AGENT_TOKEN из Render (ввод скрыт): ").strip()
    if not token:
        raise SystemExit("Токен пустой. Запустите агента снова и вставьте токен из Render.")
    return token


TOKEN = None


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
            match = re.search(r"(?:Physical|Override) size:\\s*(\\d+)x(\\d+)", size_text)
            if not match:
                raise RuntimeError("Не удалось определить размер экрана эмулятора")
            width, height = int(match.group(1)), int(match.group(2))
            # Scale calibrated base coordinates to actual emulator resolution.\n            x = round(int(command["x"]) * width / 605)\n            y = round(int(command["y"]) * height / 1070)
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Координаты касания за пределами экрана")
            adb("shell", "input", "tap", str(x), str(y))
            success = True
            print(time.strftime("%H:%M:%S"), "Касание выполнено:", x, y)
        except Exception as error:
            print("Ошибка выполнения команды:", error)
        request_json("/api/agent/commands/" + str(command_id) + "/result", {"ok": success})
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
            run_one_command()
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\nTheEnd Agent остановлен.")
