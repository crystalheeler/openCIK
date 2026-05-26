#!/bin/bash
P4A_BS_RES="/mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer/android/platform/python-for-android/pythonforandroid/bootstraps/_sdl_common/build/src/main/res"
DIST_RES="/mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/opencik/src/main/res"

echo "=== bootstrap res/xml ==="
ls -la "$P4A_BS_RES/xml/" 2>&1
echo ""
echo "=== bootstrap res/ all dirs ==="
ls "$P4A_BS_RES/"
echo ""
echo "=== dist res/xml ==="
ls -la "$DIST_RES/xml" 2>&1
echo ""
echo "=== dist res/ all entries ==="
ls "$DIST_RES/"
echo ""
echo "=== check manifest receiver block in dist ==="
grep -A 8 "AdminReceiver" "/mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/opencik/src/main/AndroidManifest.xml" 2>&1 || echo "(no AdminReceiver entry)"
