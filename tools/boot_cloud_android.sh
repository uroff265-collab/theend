#!/usr/bin/env bash
# Start Google Play Android directly; bypass the flaky post-boot ADB handoff
# in reactivecircus/android-emulator-runner observed on this GitHub runner.
set -Eeuo pipefail

SDK_ROOT="$(printenv ANDROID_SDK_ROOT || true)"
if [ -z "$SDK_ROOT" ]; then SDK_ROOT="$(printenv ANDROID_HOME || true)"; fi
if [ -z "$SDK_ROOT" ]; then SDK_ROOT="/usr/local/lib/android/sdk"; fi
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/platform-tools:$SDK_ROOT/emulator:$PATH"

SDKMANAGER="$(command -v sdkmanager || true)"
AVDMANAGER="$(command -v avdmanager || true)"
if [ -z "$SDKMANAGER" ]; then
  SDKMANAGER="$(find "$SDK_ROOT/cmdline-tools" -type f -name sdkmanager -print -quit 2>/dev/null || true)"
fi
if [ -z "$AVDMANAGER" ]; then
  AVDMANAGER="$(find "$SDK_ROOT/cmdline-tools" -type f -name avdmanager -print -quit 2>/dev/null || true)"
fi
ADB="$(command -v adb || true)"
if [ -z "$SDKMANAGER" ] || [ -z "$AVDMANAGER" ] || [ -z "$ADB" ]; then
  echo "ANDROID_SDK_TOOLS_MISSING sdk=$SDKMANAGER avd=$AVDMANAGER adb=$ADB"
  exit 1
fi

IMAGE="system-images;android-30;google_apis_playstore;x86_64"
echo "ANDROID_SDK_ROOT=$SDK_ROOT"
echo "Installing/verifying Google Play Android 30 image"
set +o pipefail
yes | "$SDKMANAGER" --licenses >/dev/null
set -o pipefail
"$SDKMANAGER" --install "platform-tools" "platforms;android-30" "emulator" "$IMAGE" --channel=0
EMULATOR="$(command -v emulator || true)"
if [ -z "$EMULATOR" ] || [ ! -x "$EMULATOR" ]; then
  EMULATOR="$SDK_ROOT/emulator/emulator"
fi
if [ ! -x "$EMULATOR" ]; then
  echo "ANDROID_EMULATOR_BINARY_MISSING path=$EMULATOR"
  exit 1
fi
echo no | "$AVDMANAGER" create avd --force -n theend-api30 --package "$IMAGE" --device pixel_2

if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  ACCEL_ARGS=(-accel on)
  echo "ANDROID_ACCELERATION=KVM"
else
  ACCEL_ARGS=(-accel off)
  echo "::warning::KVM unavailable; using Android Emulator software CPU fallback."
fi

rm -f /tmp/theend-cloud-screen.png
"$EMULATOR" -port 5554 -avd theend-api30 "${ACCEL_ARGS[@]}" \
  -no-window -gpu swiftshader_indirect -noaudio -no-boot-anim \
  -no-snapshot -no-metrics -wipe-data \
  >/tmp/theend-emulator.log 2>&1 &
EMULATOR_PID=$!
echo "ANDROID_EMULATOR_PID=$EMULATOR_PID"

"$ADB" start-server
BOOTED=0
for i in $(seq 1 200); do
  STATE="$("$ADB" -s emulator-5554 get-state 2>/dev/null || true)"
  if [ "$STATE" = "device" ]; then
    BOOT_STATE="$("$ADB" -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
    if [ "$BOOT_STATE" = "1" ]; then
      BOOTED=1
      break
    fi
  elif (( i % 5 == 0 )); then
    "$ADB" reconnect offline >/dev/null 2>&1 || true
  fi
  if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then
    echo "ANDROID_EMULATOR_PROCESS_EXITED"
    tail -n 120 /tmp/theend-emulator.log || true
    exit 1
  fi
  if (( i % 10 == 0 )); then
    echo "Waiting for Android boot: attempt $i/200; adb_state=$STATE"
  fi
  sleep 3
done

if [ "$BOOTED" -ne 1 ]; then
  echo "ANDROID_BOOT_TIMEOUT"
  "$ADB" devices -l || true
  tail -n 160 /tmp/theend-emulator.log || true
  exit 1
fi

"$ADB" -s emulator-5554 shell wm size 1080x1920 || true
"$ADB" -s emulator-5554 shell settings put global window_animation_scale 0 || true
"$ADB" -s emulator-5554 shell settings put global transition_animation_scale 0 || true
"$ADB" -s emulator-5554 shell settings put global animator_duration_scale 0 || true
"$ADB" devices -l
ANDROID_VERSION="$("$ADB" -s emulator-5554 shell getprop ro.build.version.release | tr -d '\r')"
echo "ANDROID_DIRECT_BOOT_OK Android=$ANDROID_VERSION"

MODE="--smoke"
if [ "$#" -gt 0 ]; then MODE="$1"; fi
if [ "$MODE" = "--smoke" ]; then
  python tools/cloud_android_smoke.py
elif [ "$MODE" != "--start-only" ]; then
  echo "Usage: $0 [--smoke|--start-only]"
  exit 2
fi
