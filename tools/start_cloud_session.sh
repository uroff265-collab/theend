#!/usr/bin/env bash
set -Eeuo pipefail

diagnostics() {
  rc=$?
  echo "THEEND_STARTUP_ERROR exit_code=$rc line=${BASH_LINENO[0]:-unknown} command=${BASH_COMMAND:-unknown}"
  echo "---- adb version ----"
  adb version || true
  echo "---- adb devices ----"
  adb devices -l || true
  echo "---- emulator state ----"
  adb get-state || true
  echo "---- emulator boot property ----"
  adb shell getprop sys.boot_completed || true
  echo "---- remote server log ----"
  cat /tmp/theend-remote.log 2>/dev/null || true
  echo "---- cloudflared log ----"
  cat /tmp/theend-tunnel.log 2>/dev/null || true
}
trap diagnostics ERR
set -x

echo "THEEND_ADB_DIAGNOSTICS_BEGIN"
adb version
adb start-server
adb devices -l

# Wait for the emulator transport and Android boot to become usable.
connected=0
for i in $(seq 1 60); do
  if adb get-state >/dev/null 2>&1; then
    connected=1
    break
  fi
  adb devices -l || true
  sleep 2
done
if [ "$connected" -ne 1 ]; then
  echo "ADB_DEVICE_NEVER_BECAME_READY"
  exit 1
fi

booted=0
for i in $(seq 1 90); do
  state="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [ "$state" = "1" ]; then
    booted=1
    break
  fi
  sleep 2
done
if [ "$booted" -ne 1 ]; then
  echo "ANDROID_BOOT_DID_NOT_COMPLETE"
  exit 1
fi

ANDROID_VERSION="$(adb shell getprop ro.build.version.release | tr -d '\r')"
adb shell wm size 1080x1920
adb shell input keyevent 82 || true
# This emulator image uses google_apis (not the Play Store image).
# Keep the remote session usable; the game can be installed only from an official source.
adb exec-out screencap -p > /tmp/theend-cloud-screen.png
test -s /tmp/theend-cloud-screen.png
echo "ANDROID_EMULATOR_READY Android $ANDROID_VERSION"

python3 tools/cloud_android_remote.py >/tmp/theend-remote.log 2>&1 &
REMOTE_PID=$!
sleep 2
if ! kill -0 "$REMOTE_PID" 2>/dev/null; then
  cat /tmp/theend-remote.log
  echo "Remote Android server failed to start"
  exit 1
fi

cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8765 --allowed-mail "$ACCESS_EMAIL" >/tmp/theend-tunnel.log 2>&1 &
TUNNEL_PID=$!
URL=""
for i in $(seq 1 90); do
  URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/theend-tunnel.log | head -n1 || true)"
  if [ -n "$URL" ]; then
    break
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    cat /tmp/theend-tunnel.log
    exit 1
  fi
  sleep 2
done

if [ -z "$URL" ]; then
  cat /tmp/theend-tunnel.log
  echo "Cloudflare tunnel URL was not created"
  exit 1
fi

echo ""
echo "=============================================="
echo "THEEND CLOUD ANDROID IS READY"
echo "OPEN THIS LINK: $URL/?k=cloudflare-otp-protected"
echo "Cloudflare will send a one-time PIN to the allowed email."
echo "Sign in only through the official game/app source."
echo "Keep this workflow running while using the emulator."
echo "=============================================="
echo ""

for i in $(seq 1 21000); do
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "Cloudflare tunnel stopped"
    cat /tmp/theend-tunnel.log
    exit 1
  fi
  if ! kill -0 "$REMOTE_PID" 2>/dev/null; then
    echo "Remote Android server stopped"
    cat /tmp/theend-remote.log
    exit 1
  fi
  sleep 1
done
