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
ADB_KEY="$HOME/.android/adbkey"
if [ -s "$ADB_KEY" ]; then export ADB_VENDOR_KEYS="$ADB_KEY"; fi
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
PLAY_STORE_APK="$(adb shell pm path com.android.vending 2>/dev/null | tr -d '\r' | head -n1 || true)"
if [[ "$PLAY_STORE_APK" == package:* ]]; then
  echo "GOOGLE_PLAY_STORE_OK $PLAY_STORE_APK"
else
  echo "::warning::Google Play Store package com.android.vending is absent; continuing to publish Android screen for diagnosis."
  adb shell pm list packages | grep -Ei 'vending|google' | head -n 30 || true
fi
if adb shell pm path com.phs.global 2>/dev/null | grep -q '^package:'; then
  echo "LAST_ASYLUM_ALREADY_INSTALLED"
  adb shell monkey -p com.phs.global -c android.intent.category.LAUNCHER 1
elif [[ "$PLAY_STORE_APK" == package:* ]]; then
  echo "LAST_ASYLUM_NOT_INSTALLED_OPENING_OFFICIAL_PLAY_STORE_LISTING"
  adb shell am start -a android.intent.action.VIEW -d "market://details?id=com.phs.global" || true
else
  echo "LAST_ASYLUM_NOT_INSTALLED_AND_PLAY_STORE_MISSING"
fi
sleep 5
adb shell dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity' | head -n1 || true
adb exec-out screencap -p > /tmp/theend-cloud-screen.png
test -s /tmp/theend-cloud-screen.png
echo "CHECKPOINT_ANDROID_BOOTED Android $ANDROID_VERSION"
echo "ANDROID_EMULATOR_READY Android $ANDROID_VERSION"

set +x
THEEND_REMOTE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export THEEND_REMOTE_TOKEN
echo "::add-mask::$THEEND_REMOTE_TOKEN"
printf '%s\\n' "${URL:-}" > /tmp/theend-cloud-session-link.txt
set -x
python3 tools/cloud_android_remote.py >/tmp/theend-remote.log 2>&1 &
REMOTE_PID=$!
sleep 2
kill -0 "$REMOTE_PID"
# Pinggy's free HTTPS tunnel has a documented 60-minute session and unlimited transfer,
# unlike localhost.run's anonymous bandwidth throttling. Empty password is accepted.
ssh -V
sshpass -p '' ssh -T -p 443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o NumberOfPasswordPrompts=1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R0:127.0.0.1:8765 free.pinggy.io >/tmp/theend-tunnel.log 2>&1 &
TUNNEL_PID=$!
URL=""
for i in $(seq 1 90); do
  URL="$(grep -Eo 'https://[A-Za-z0-9.-]+(\.run\.pinggy-free\.link|\.free\.pinggy\.net|\.a\.pinggy\.link)' /tmp/theend-tunnel.log | head -n1 || true)"
  if [ -n "$URL" ]; then break; fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then cat /tmp/theend-tunnel.log; exit 1; fi
  sleep 2
done
if [ -z "$URL" ]; then cat /tmp/theend-tunnel.log; echo "Public SSH tunnel URL was not created"; exit 1; fi
echo "CHECKPOINT_TUNNEL_CREATED $URL"

# Verify the public URL once. Repeated probes trigger throttling on free tunnel services.
if ! curl -fsS --max-time 45 "$URL/frame?k=$THEEND_REMOTE_TOKEN" -o /tmp/theend-public-frame.png ||
   ! head -c 8 /tmp/theend-public-frame.png | od -An -tx1 | grep -qi '89 50 4e 47 0d 0a 1a 0a'; then
  echo "PUBLIC_ANDROID_FRAME_CHECK_FAILED"
  cat /tmp/theend-tunnel.log
  exit 1
fi
echo "CHECKPOINT_PUBLIC_FRAME_OK bytes=$(wc -c </tmp/theend-public-frame.png)"

export URL
set +x
if [[ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" || -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]]; then
  echo "GITHUB_OIDC_UNAVAILABLE: id-token: write permission is required"
  exit 1
fi
OIDC_REQUEST_URL="${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=theend-cloud-session"
OIDC_RESPONSE="$(curl -fsS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" "$OIDC_REQUEST_URL")"
OIDC_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["value"])' <<<"$OIDC_RESPONSE")"
SESSION_PAYLOAD="$(python3 -c 'import json,os; print(json.dumps({"url":os.environ["URL"],"token":os.environ["THEEND_REMOTE_TOKEN"],"runId":os.environ["GITHUB_RUN_ID"],"commitSha":os.environ["GITHUB_SHA"]}))')"
PUBLISHED=0
for i in $(seq 1 18); do
  STATUS="$(curl -sS -o /tmp/theend-publish-response.json -w '%{http_code}' -X POST "https://theend-1.onrender.com/internal/cloud-session" -H "Authorization: Bearer $OIDC_TOKEN" -H "Content-Type: application/json" --data "$SESSION_PAYLOAD" || true)"
  if [ "$STATUS" = "202" ]; then PUBLISHED=1; break; fi
  echo "Private session registry not ready (HTTP $STATUS; attempt $i/18)"
  sleep 10
done
if [ "$PUBLISHED" -ne 1 ]; then
  cat /tmp/theend-publish-response.json 2>/dev/null || true
  echo "CLOUD_SESSION_REGISTRY_FAILED"
  exit 1
fi
echo "CHECKPOINT_SESSION_REGISTERED run=$GITHUB_RUN_ID"
set -x
echo ""
echo "=============================================="
echo "THEEND CLOUD ANDROID IS READY"
echo "OPEN THIS BASE URL: $URL"
echo "The private access key was delivered to the authenticated TheEnd service log."
echo "Keep this workflow running while using the emulator."
echo "=============================================="
echo ""

for i in $(seq 1 1800); do
  if (( i % 30 == 0 )); then echo "CHECKPOINT_SESSION_HEARTBEAT elapsed=${i}s"; fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then echo "Public tunnel stopped"; cat /tmp/theend-tunnel.log; exit 1; fi
  if ! kill -0 "$REMOTE_PID" 2>/dev/null; then echo "Remote Android server stopped"; cat /tmp/theend-remote.log; exit 1; fi
  sleep 1
done
