#!/usr/bin/env python3
"""Reliable single-process smoke test for the cloud Android emulator."""
from pathlib import Path
import subprocess
import sys
import time

SCREENSHOT = Path("/tmp/theend-cloud-screen.png")


def run(command, check=True, binary=False):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if binary else subprocess.STDOUT,
        timeout=90,
    )
    output = result.stdout if binary else result.stdout.decode(errors="replace").strip()
    error = result.stderr.decode(errors="replace").strip() if binary else ""
    if not binary and output:
        print(output, flush=True)
    if check and result.returncode:
        detail = error or output
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return output


def main():
    devices = run(["adb", "devices"])
    if not any(line.startswith("emulator-") and line.endswith("\tdevice")
               for line in devices.splitlines()):
        raise RuntimeError("No online Android emulator in adb devices")

    version = run(["adb", "shell", "getprop", "ro.build.version.release"])
    run(["adb", "shell", "wm", "size", "1080x1920"])
    store = run(["adb", "shell", "pm", "path", "com.android.vending"], check=False)
    game = run(["adb", "shell", "pm", "path", "com.phs.global"], check=False)

    if store.startswith("package:"):
        print("GOOGLE_PLAY_STORE_OK", flush=True)
    else:
        print("WARNING: Play Store absent; continuing.", flush=True)

    if game.startswith("package:"):
        print("LAST_ASYLUM_INSTALLED; launching", flush=True)
        run(["adb", "shell", "monkey", "-p", "com.phs.global",
             "-c", "android.intent.category.LAUNCHER", "1"], check=False)
    elif store.startswith("package:"):
        print("LAST_ASYLUM_NOT_INSTALLED; opening Play Store listing", flush=True)
        run(["adb", "shell", "am", "start", "-a", "android.intent.action.VIEW",
             "-d", "market://details?id=com.phs.global"], check=False)
    else:
        print("LAST_ASYLUM_NOT_INSTALLED_AND_PLAY_STORE_MISSING", flush=True)

    time.sleep(5)
    image = run(["adb", "exec-out", "screencap", "-p"], binary=True)
    if not image:
        raise RuntimeError("Screenshot is empty")
    SCREENSHOT.write_bytes(image)

    from PIL import Image
    import cv2
    import numpy as np
    with Image.open(SCREENSHOT) as frame:
        frame.verify()
    decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise RuntimeError("OpenCV could not decode screenshot")
    print(f"ANDROID_EMULATOR_OK Android {version}; screenshot={decoded.shape}; bytes={len(image)}",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ANDROID_SMOKE_TEST_FAILED: {exc}", file=sys.stderr, flush=True)
        raise
