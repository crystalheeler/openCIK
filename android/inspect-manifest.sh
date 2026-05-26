#!/bin/bash
# Inspect the generated AndroidManifest.xml for our current build.
# Helper for figuring out how to inject a DeviceAdminReceiver entry.
DIST_MANIFEST="/mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/opencik/src/main/AndroidManifest.xml"
if [ -f "$DIST_MANIFEST" ]; then
    cat "$DIST_MANIFEST"
else
    echo "manifest not found at $DIST_MANIFEST"
    find /mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer -name AndroidManifest.xml 2>/dev/null
fi
