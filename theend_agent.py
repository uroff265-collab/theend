#!/usr/bin/env python3
"""TheEnd Agent: reports Android Debug Bridge emulator connectivity."""
import json, os, platform, subprocess, time, urllib.request, urllib.error

BASE_URL = os.environ.get("THEEND_URL", "https://theend-1.onrender.com").rstrip("/")
TOKEN = os.environ.get("THEEND_AGENT_TOKEN", "")
DEVICE_NAME = os.environ.get("THEEND_DEVICE_NAME", platform.node() or "Android emulator")

def emulator_connected():
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8, check=True)
        return any(len(parts := line.split()) >= 2 and parts[1] == "device"
                   for line in result.stdout.splitlines()[1:])
    except (FileNotFoundError, subprocess.SubprocessError):
        return False

def heartbeat(connected):
    body = json.dumps({"deviceName": DEVICE_NAME, "emulatorConnected": connected}).encode()
    request = urllib.request.Request(
        BASE_URL + "/api/agent/heartbeat", data=body,
        headers={"Content-Type":"application/json", "Authorization":"Bearer " + TOKEN},
        method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status

def main():
    if not TOKEN:
        raise SystemExit("Set THEEND_AGENT_TOKEN first. Never share this token.")
    print("TheEnd Agent started. Press Ctrl+C to stop.")
    while True:
        connected = emulator_connected()
        try:
            heartbeat(connected)
            print(time.strftime("%H:%M:%S"), "Android emulator:", "connected" if connected else "not found")
        except (urllib.error.URLError, TimeoutError) as error:
            print("Connection error:", error)
        time.sleep(15)

if __name__ == "__main__":
    main()
