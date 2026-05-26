#!/bin/bash
# Inspect p4a's manifest template path + the generated AndroidManifest.
# Helper for figuring out where to inject the DeviceAdminReceiver entry.
echo "=== p4a manifest template locations ==="
find /home/jerrysmith/.buildozer -name "AndroidManifest.tmpl.xml" 2>/dev/null
echo ""
echo "=== rendered AndroidManifest in dist ==="
DIST_MANIFEST="/mnt/c/86/Tools-Tech/Software/AI-Projects/openCIK/android/.buildozer/android/platform/build-arm64-v8a_armeabi-v7a/dists/opencik/src/main/AndroidManifest.xml"
if [ -f "$DIST_MANIFEST" ]; then
    cat "$DIST_MANIFEST"
else
    echo "manifest not found at $DIST_MANIFEST"
fi
