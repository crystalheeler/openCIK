"""
Shared state-file IO between the Activity (main.py) and the foreground
Service (service/monitor.py).

These are simple atomic JSON files under the app's private files dir.
We don't use SharedPreferences because both the Activity process and
the Service process need to read/write, and SharedPreferences across
processes is unreliable on modern Android.

Files:
    arm.json       — armed flag + chosen delay
    settings.json  — trigger toggles (lock, wipe, confirm, wipe-on-disable)
    pin.json       — PIN hash + salt
    status.json    — written by service, read by UI (live state)
"""

import hashlib
import json
import os
import secrets
import time

from kivy.utils import platform


# ---------- paths ----------

def files_dir():
    """App private files dir. Falls back to ~ on desktop for layout debug."""
    if platform != 'android':
        return os.path.expanduser('~')
    from jnius import autoclass
    activity = autoclass('org.kivy.android.PythonActivity').mActivity
    if activity is None:
        # Called from service — use PythonService instead
        try:
            service = autoclass('org.kivy.android.PythonService').mService
            return service.getFilesDir().getAbsolutePath()
        except Exception:
            return '/data/local/tmp'
    return activity.getFilesDir().getAbsolutePath()


def _path(name):
    return os.path.join(files_dir(), name)


# ---------- atomic IO ----------

def _read_json(name, default=None):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _write_json(name, data):
    tmp = _path(name) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, _path(name))


# ---------- arm state ----------

def read_arm():
    """Returns dict with at least: armed (bool), armed_at (float), delay (int)."""
    s = _read_json('arm.json', {})
    return {
        'armed': bool(s.get('armed', False)),
        'armed_at': float(s.get('armed_at', 0)),
        'delay': int(s.get('delay', 3)),
    }


def write_arm(armed, delay=3):
    _write_json('arm.json', {
        'armed': bool(armed),
        'armed_at': time.time() if armed else 0,
        'delay': int(delay),
    })


# ---------- trigger settings (M7) ----------

DEFAULT_SETTINGS = {
    # Triggers — what to do on OnlyKey removal
    'trig_lock': True,           # call DevicePolicyManager.lockNow()
    'trig_wipe': False,          # call DevicePolicyManager.wipeData() — DESTRUCTIVE
    'wipe_confirm': False,       # require user confirmation popup before wipe
    # Tampering defenses (M8) — fire wipe on these events
    'wipe_on_admin_disable': False,
    'wipe_on_force_stop': False,
}


def read_settings():
    s = _read_json('settings.json', {})
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS})
    return out


def write_settings(settings):
    # Only persist known keys
    out = {k: bool(v) for k, v in settings.items() if k in DEFAULT_SETTINGS}
    _write_json('settings.json', out)


def any_trigger_enabled(settings=None):
    s = settings or read_settings()
    return bool(s['trig_lock'] or s['trig_wipe'])


# ---------- PIN (M6) ----------

# Scrypt is heavy — for our use case (short numeric PIN, infrequent verify)
# PBKDF2-HMAC-SHA256 at 200k iterations is fine and ships with stdlib.
_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16


def _hash_pin(plaintext, salt):
    return hashlib.pbkdf2_hmac(
        'sha256',
        plaintext.encode('utf-8'),
        salt,
        _PBKDF2_ITERS,
    )


def pin_is_set():
    s = _read_json('pin.json', {})
    return bool(s.get('salt') and s.get('hash'))


def set_pin(plaintext):
    if not plaintext:
        # Clear the PIN
        _write_json('pin.json', {})
        return
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _hash_pin(plaintext, salt)
    _write_json('pin.json', {
        'salt': salt.hex(),
        'hash': digest.hex(),
    })


def verify_pin(plaintext):
    s = _read_json('pin.json', {})
    if not (s.get('salt') and s.get('hash')):
        return True  # no PIN set — anyone can disarm
    try:
        salt = bytes.fromhex(s['salt'])
        expected = bytes.fromhex(s['hash'])
    except Exception:
        return False
    candidate = _hash_pin(plaintext, salt)
    return secrets.compare_digest(candidate, expected)
