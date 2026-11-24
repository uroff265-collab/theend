#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
ANDROID_VERSION="$(adb shell getprop ro.build.version.release | tr -d '\r')"
adb shell wm size 1080x1920
adb shell input keyevent 82 || true
# Open the Last Asylum Play Store listing on the cloud device.
adb shell am start -a android.intent.action.VIEW -d 'market://details?id=com.phs.global' || true
sleep 8
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
echo "Install Last Asylum from Play Store and sign in."
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
