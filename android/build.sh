#!/bin/bash
#
# openCIK Android build wrapper.
#
# Why a wrapper instead of just `buildozer android debug`:
#   1. We need a <receiver> in the manifest for DeviceAdminReceiver, but
#      buildozer.spec has no hook for that. We inject it via
#      patches/inject-admin-receiver.py.
#   2. p4a copies most res/<type>/ subdirs (drawable/, mipmap/, etc.)
#      from its bootstrap into the dist on each build, but it does NOT
#      copy res/xml/. So we copy res/xml/device_admin.xml into the dist
#      manually after buildozer has set things up.
#   3. The Android Gradle Plugin caches resources aggressively, so if
#      buildozer's APK packaging fails because of a missing resource,
#      we fix it and re-run gradle DIRECTLY (skipping buildozer's
#      re-regenerate-dist step which would clobber our fixes).
#
# Build flow:
#   1. Run buildozer once (creates the dist tree, may fail at AAPT —
#      that's fine, we just need the dist to exist with the patched
#      manifest in place).
#   2. Run patches/inject-admin-receiver.py — patches manifest template
#      at bootstrap level (so subsequent regens are correct) AND
#      patches the current dist directly (for THIS build).
#   3. Run gradle directly from the dist dir to repackage the APK.
#   4. Copy the resulting APK from dist/build/outputs/apk/debug/ to bin/.
#
# Subsequent builds are fast — once the bootstrap is patched and the
# dist exists, only steps 2-4 take meaningful time (~30 sec).
#
# Usage:  cd android/ && ./build.sh

set -e

cd "$(dirname "$0")"
ANDROID_DIR="$(pwd)"
REPO_ROOT="$(cd .. && pwd)"

BUILDOZER="${HOME}/.local/bin/buildozer"
PATCH_SCRIPT="${ANDROID_DIR}/patches/inject-admin-receiver.py"
DIST_DIR="${ANDROID_DIR}/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/opencik"

if [ ! -x "$BUILDOZER" ]; then
    echo "buildozer not found at $BUILDOZER"
    echo "did you run android/setup-wsl.sh?"
    exit 1
fi

# Step 1: ensure the dist tree exists. If it doesn't, run buildozer once
# (which we expect to fail at AAPT but will create the dist along the way).
if [ ! -d "$DIST_DIR" ]; then
    echo "================================================================"
    echo "Step 1: first build — dist not yet generated. Running buildozer"
    echo "to bootstrap the dist tree. Will likely fail at AAPT; we'll fix"
    echo "and retry with gradle directly."
    echo "================================================================"
    yes | "$BUILDOZER" android debug || true
fi

if [ ! -d "$DIST_DIR" ]; then
    echo "buildozer failed to create the dist tree at $DIST_DIR"
    echo "this usually means a real Python / p4a error — look earlier in"
    echo "the buildozer output for details."
    exit 1
fi

# Step 2: apply patches (manifest receiver + xml resource).
# Both bootstrap-level (persistent) and dist-level (this build).
echo ""
echo "=== Step 2: applying patches ==="
python3 "$PATCH_SCRIPT"

# Step 2.5: ALSO run buildozer one more time IF the python source has
# changed (so buildozer copies main.py and service/monitor.py into the
# dist's private dir before we package). The catch: this also
# regenerates the manifest from the (already-patched) template, which
# is fine; and copies res from bootstrap to dist, which would WIPE our
# device_admin.xml since p4a doesn't include xml/ in its copy. So we
# re-apply patches AFTER buildozer runs.
echo ""
echo "=== Step 2.5: buildozer pass to refresh python sources ==="
yes | "$BUILDOZER" android debug || true

# Re-apply patches now that buildozer may have wiped the dist res
echo ""
echo "=== re-applying dist-level patches after buildozer pass ==="
python3 "$PATCH_SCRIPT"

# Step 3: run gradle directly. This skips p4a's regen so our patches
# survive into the actual APK.
echo ""
echo "=== Step 3: gradle assembleDebug (direct) ==="
cd "$DIST_DIR"
./gradlew assembleDebug

# Step 4: copy the APK into android/bin/ with a versioned name.
echo ""
echo "=== Step 4: copy APK to bin/ ==="
APK_SRC="$DIST_DIR/build/outputs/apk/debug/opencik-debug.apk"
if [ ! -f "$APK_SRC" ]; then
    echo "expected APK not produced at $APK_SRC"
    exit 1
fi

VERSION=$(grep -E "^version\s*=" "$ANDROID_DIR/buildozer.spec" \
    | head -1 | awk -F= '{print $2}' | tr -d ' ')
APK_DST="$ANDROID_DIR/bin/opencik-${VERSION}-arm64-v8a_armeabi-v7a-debug.apk"
mkdir -p "$ANDROID_DIR/bin"
cp "$APK_SRC" "$APK_DST"

echo ""
echo "================================================================"
echo "Build OK"
echo "  APK: $APK_DST"
ls -lh "$APK_DST"
echo "================================================================"
