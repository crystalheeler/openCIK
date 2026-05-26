[app]

# (str) Title of your application
title = openCIK

# (str) Package name
package.name = opencik

# (str) Package domain (needed for android/ios packaging)
package.domain = io.crystalheeler

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,ttf

# (str) Application versioning (method 1)
version = 0.1.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy

# (str) Supported orientations
# Valid options are: landscape, portrait, portrait-reverse or landscape-reverse
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0


# --- ANDROID-SPECIFIC ---

# (list) Permissions
# For the hello-world step we ship zero permissions. Real openCIK will add:
#   - WAKE_LOCK, FOREGROUND_SERVICE (background USB monitoring)
#   - BIND_DEVICE_ADMIN (lock/wipe)
#   - POST_NOTIFICATIONS (Android 13+ persistent notification)
# android.permissions = INTERNET

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support.
# 21 = Android 5.0 Lollipop, covers 99%+ of devices in use.
# We may bump this later if specific USB OTG / DevicePolicyManager
# APIs we need require a higher floor.
android.minapi = 21

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
# arm64-v8a covers ~98% of modern devices. armeabi-v7a covers older ones.
# x86 / x86_64 are useful only for emulators.
android.archs = arm64-v8a, armeabi-v7a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D


# --- KIVY / P4A ---

# (list) Application requirements as we add them
# orientation, screen density, etc. handled above

# (str) python-for-android branch to use, defaults to master
p4a.branch = master


[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
