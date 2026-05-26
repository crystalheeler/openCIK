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
version = 0.3.1

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
# pyjnius is the Python -> Java bridge we use to call Android's
# UsbManager / DevicePolicyManager / NotificationManager. It's usually
# pulled in transitively by kivy on Android, but listed explicitly so
# we don't depend on that staying true across p4a versions.
requirements = python3,kivy,pyjnius

# (list) Background services to register.
# Format: name:script_path:foreground|background
# Foreground services keep running when the activity is backgrounded,
# but require a persistent notification (Android shows one
# automatically; p4a's template handles that for us).
# The 'monitor' entry generates a Java class
# io.crystalheeler.opencik.ServiceMonitor which we start from main.py.
services = monitor:service/monitor.py:foreground

# (str) Supported orientations
# Valid options are: landscape, portrait, portrait-reverse or landscape-reverse
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0


# --- ANDROID-SPECIFIC ---

# (list) Permissions
# - FOREGROUND_SERVICE / FOREGROUND_SERVICE_SPECIAL_USE: required to
#   run our USB-monitoring foreground service on Android 9+ / 14+
# - WAKE_LOCK: keep CPU running while the service polls (1Hz, very low
#   power, but Android still demands the permission)
# - POST_NOTIFICATIONS: Android 13+ requires this to show the
#   mandatory persistent foreground-service notification
# Later milestones will add: BIND_DEVICE_ADMIN (lock/wipe trigger),
# RECEIVE_BOOT_COMPLETED (auto-arm at boot, optional).
android.permissions = FOREGROUND_SERVICE, FOREGROUND_SERVICE_SPECIAL_USE, WAKE_LOCK, POST_NOTIFICATIONS

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
