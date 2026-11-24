#!/usr/bin/env bash
set -Eeuo pipefail

diagnostics() {
  rc=$?
  echo "THEEND_STARTUP_ERROR exit_code=$rc line=${BASH_LINENO[0]:-unknown} command=${BASH_COMMAND:-unknown}"
  echo "---- adb devices ----"; adb devices -l || true
  echo "---- emulator boot ----"; adb shell getprop sys.boot_completed || true
  echo "---- remote server log ----"; cat /tmp/theend-remote.log 2>/dev/null || true
  echo "---- public tunnel log ----"; cat /tmp/theend-tunnel.log 2>/dev/null || true
}
trap diagnostics ERR
set -x

echo "THEEND_ADB_DIAGNOSTICS_BEGIN"
adb version
adb start-server
adb devices -l
connected=0
for i in $(seq 1 60); do
  if adb get-state >/dev/null 2>&1; then connected=1; break; fi
  adb devices -l || true
  sleep 2
done
if [ "$connected" -ne 1 ]; then echo "ADB_DEVICE_NEVER_BECAME_READY"; exit 1; fi

booted=0
for i in $(seq 1 90); do
  state="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [ "$state" = "1" ]; then booted=1; break; fi
  sleep 2
done
if [ "$booted" -ne 1 ]; then echo "ANDROID_BOOT_DID_NOT_COMPLETE"; exit 1; fi

ANDROID_VERSION="$(adb shell getprop ro.build.version.release | tr -d '\r')"
adb shell wm size 1080x1920
adb shell input keyevent 82 || true
adb exec-out screencap -p > /tmp/theend-cloud-screen.png
test -s /tmp/theend-cloud-screen.png
echo "ANDROID_EMULATOR_READY Android $ANDROID_VERSION"

python3 tools/cloud_android_remote.py >/tmp/theend-remote.log 2>&1 &
REMOTE_PID=$!
sleep 2
kill -0 "$REMOTE_PID"
# Use localhost.run SSH reverse forwarding instead of Cloudflare Quick Tunnel,
# which currently rejects account-less tunnel creation with HTTP 429.
ssh -V
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -R 80:127.0.0.1:8765 nokey@localhost.run >/tmp/theend-tunnel.log 2>&1 &
TUNNEL_PID=$!
URL=""
for i in $(seq 1 90); do
  URL="$(grep -Eo 'https://[a-zA-z0-9.-]+\.lhr\.life' /tmp/theend-tunnel.log | head -n1 || true)"
  if [ -n "$URL" ]; then break; fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then cat /tmp/theend-tunnel.log; exit 1; fi
  sleep 2
done
if [ -z "$URL" ]; then cat /tmp/theend-tunnel.log; echo "Public SSH tunnel URL was not created"; exit 1; fi

echo ""
echo "=============================================="
echo "THEEND CLOUD ANDROID IS READY"
echo "OPEN THIS LINK: $URL/?k=cloudflare-otp-protected"
echo "The page requires the private access key in the link."
echo "Keep this workflow running while using the emulator."
echo "=============================================="
echo ""

for i in $(seq 1 21000); do
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then echo "Public tunnel stopped"; cat /tmp/theend-tunnel.log; exit 1; fi
  if ! kill -0 "$REMOTE_PID" 2>/dev/null; then echo "Remote Android server stopped"; cat /tmp/theend-remote.log; exit 1; fi
  sleep 1
done
