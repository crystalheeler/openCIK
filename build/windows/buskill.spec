# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the OnlyKey-enabled BusKill fork.
# Used by build/windows/buildExe-onlykey.ps1.
#
# Builds a single-file, windowed buskill.exe with:
#   - Kivy 2.x GUI (SDL2 + GLEW + ANGLE)
#   - pystray + Pillow (system tray support)
#   - pywin32 (HID device-interface notifications)

import os
from kivy_deps import sdl2, glew, angle
from kivy.tools.packaging.pyinstaller_hooks import (
    hookspath as kivy_hookspath,
    runtime_hooks as kivy_runtime_hooks,
)

# PyInstaller resolves relative paths against the spec file's directory.
# Since this spec lives at build/windows/buskill.spec and our source tree is
# at <repo>/src, walk up two levels from SPECPATH to find the repo root.
REPO_ROOT = os.path.normpath(os.path.join(SPECPATH, '..', '..'))
SRC = os.path.join(REPO_ROOT, 'src')

block_cipher = None

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, 'fonts'), 'fonts'),
        (os.path.join(SRC, 'images'), 'images'),
        (os.path.join(SRC, 'buskill.kv'), '.'),
        (os.path.join(SRC, 'buskill_version.py'), '.'),
        (os.path.join(SRC, 'packages', 'buskill', 'settings_buskill.json'),
         os.path.join('packages', 'buskill')),
        (os.path.join(SRC, 'packages', 'garden', 'navigationdrawer',
                      'navigationdrawer_gradient_ltor.png'),
         os.path.join('packages', 'garden', 'navigationdrawer')),
        (os.path.join(SRC, 'packages', 'garden', 'navigationdrawer',
                      'navigationdrawer_gradient_rtol.png'),
         os.path.join('packages', 'garden', 'navigationdrawer')),
    ],
    hiddenimports=[
        # Used in packages/buskill/__init__.py for HID hotplug detection
        'win32api', 'win32con', 'win32gui',
        # pystray's Windows backend
        'pystray._win32',
        # hidapi — used in buskill_gui.py for the live OnlyKey-present
        # indicator and precondition-gating the Arm button
        'hid',
        # garden modules are imported as packages.garden.* in buskill_gui.py
        'packages.garden.navigationdrawer',
        'packages.garden.progressspinner',
        # Kivy uses dynamic imports for its "core" providers, so PyInstaller's
        # static analysis won't find them on its own. Without these the exe
        # boots and then aborts with errors like
        # "[CRITICAL] [App] Unable to get any Image provider, abort."
        'kivy.core.window.window_sdl2',
        'kivy.core.gl.gl_sdl2',
        'kivy.core.image.img_sdl2',
        'kivy.core.image.img_pil',
        'kivy.core.image.img_tex',
        'kivy.core.image.img_dds',
        'kivy.core.text.text_sdl2',
        'kivy.core.clipboard.clipboard_winctypes',
    ],
    hookspath=kivy_hookspath(),
    runtime_hooks=kivy_runtime_hooks(),
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Single-file build: bundle binaries, zipfiles, datas, and the Kivy native
# deps (SDL2 / GLEW / ANGLE DLLs) all into the EXE itself. At runtime the
# bootloader extracts to a temp dir and launches.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    *[Tree(p) for p in (sdl2.dep_bins + glew.dep_bins + angle.dep_bins)],
    [],
    name='buskill',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(SRC, 'images', 'buskill-icon-150.ico'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
