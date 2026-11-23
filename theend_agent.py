#!/usr/bin/env python3
"""TheEnd Agent: Android ADB heartbeat and limited tap-command runner."""
import json, os, platform, re, subprocess, time, urllib.request, urllib.error

BASE_URL = os.environ.get("THEEND_URL", "https://theend-1.onrender.com").rstrip("/")
TOKEN = os.environ.get("THEEND_AGENT_TOKEN", "")
ADB = os.environ.get("THEEND_ADB", "adb")
ADB_SERIAL = os.environ.get("THEEND_ADB_SERIAL", "127.0.0.1:5555")
DEVICE_NAME = os.environ.get("THEEND_DEVICE_NAME", platform.node() or "Android emulator")

def adb(*args, timeout=8):
    return subprocess.run([ADB, "-s", ADB_SERIAL, *args], capture_output=True, text=True, timeout=timeout, check=True)

def emulator_connected():
    try:
        result = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=8, check=True)
        return any(line.split()[0] == ADB_SERIAL and len(line.split()) >= 2 and line.split()[1] == "device"
                   for line in result.stdout.splitlines()[1:] if line.split())
    except (FileNotFoundError, subprocess.SubprocessError):
        return False

def request_json(path, data=None, method=None):
    payload = None if data is None else json.dumps(data).encode()
    headers = {"Authorization":"Bearer " + TOKEN}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE_URL + path, data=payload, headers=headers, method=method or ("POST" if payload is not None else "GET"))
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode() or "{}")

def heartbeat(connected):
    return request_json("/api/agent/heartbeat", {"deviceName": DEVICE_NAME, "emulatorConnected": connected})

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
                raise ValueError("Unsupported command")
            size_text = adb("shell", "wm", "size").stdout
            match = re.search(r"(?:Physical|Override) size:\\s*(\\d+)x(\\d+)", size_text)
            if not match:
                raise RuntimeError("Could not read emulator screen size")
            width, height = int(match.group(1)), int(match.group(2))
            x, y = int(command["x"]), int(command["y"])
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Tap coordinates outside screen")
            adb("shell", "input", "tap", str(x), str(y))
            success = True
            print(time.strftime("%H:%M:%S"), "Tap command completed:", x, y)
        except Exception as error:
            print("Command failed:", error)
        request_json("/api/agent/commands/" + str(command_id) + "/result", {"ok":success})
    except urllib.error.HTTPError as error:
        print("Command service error:", error.code)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print("Command polling error:", error)

def main():
    if not TOKEN:
        raise SystemExit("Set THEEND_AGENT_TOKEN first. Never share this token.")
    print("TheEnd Agent started. Android target:", ADB_SERIAL)
    last_heartbeat = 0
    while True:
        connected = emulator_connected()
        now = time.time()
        if now - last_heartbeat >= 15:
            try:
                heartbeat(connected)
                print(time.strftime("%H:%M:%S"), "Android emulator:", "connected" if connected else "not found")
            except (urllib.error.URLError, TimeoutError) as error:
                print("Heartbeat error:", error)
            last_heartbeat = now
        if connected:
            run_one_command()
        time.sleep(2)

if __name__ == "__main__":
    main()
