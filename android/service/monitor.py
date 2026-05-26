"""
openCIK Android foreground service: USB monitor + trigger dispatcher.

Polls UsbManager at 1 Hz under normal conditions. When the user is armed
and the OnlyKey transitions from present -> absent, the service:

  1. Reads the chosen countdown delay (seconds) and trigger toggles from
     arm.json + settings.json.
  2. Enters a 10 Hz countdown loop for `delay` seconds:
       - emits a beep + escalating haptic each tick
       - watches for the OnlyKey being re-plugged (abort)
  3. After the countdown expires, dispatches the enabled triggers:
       - lock-screen via DevicePolicyManager.lockNow()
       - factory wipe via DevicePolicyManager.wipeData() (with optional
         confirmation popup — the popup is presented by the Activity,
         not the service, via a shared 'pending_wipe.json' file)

Status state is written to status.json continuously so the UI can
render the live state.
"""

import json
import os
import sys
import time
import traceback

from jnius import autoclass


ONLYKEY_VID = 0x1D50
ONLYKEY_PID = 0x60FC

POLL_INTERVAL = 1.0       # seconds, normal monitoring
COUNTDOWN_TICK = 0.1      # seconds, during countdown

ADMIN_RECEIVER_CLASS = 'io.crystalheeler.opencik.AdminReceiver'


# ----------------------------------------------------------------
# Android service helpers
# ----------------------------------------------------------------

def get_service():
    return autoclass('org.kivy.android.PythonService').mService


def get_context(service):
    return service.getApplicationContext()


def get_system_service(service, name):
    Context = autoclass('android.content.Context')
    return get_context(service).getSystemService(getattr(Context, name))


def get_admin_component(service):
    ComponentName = autoclass('android.content.ComponentName')
    return ComponentName(get_context(service), ADMIN_RECEIVER_CLASS)


# ----------------------------------------------------------------
# USB enumeration (same as M2/M3)
# ----------------------------------------------------------------

def enumerate_devices(usb_manager):
    device_map = usb_manager.getDeviceList()
    devices = []
    it = device_map.entrySet().iterator()
    while it.hasNext():
        entry = it.next()
        d = entry.getValue()
        try:
            product = d.getProductName() or '(no name)'
        except Exception:
            product = '(no name)'
        devices.append({
            'name': entry.getKey(),
            'product': product,
            'vid': d.getVendorId(),
            'pid': d.getProductId(),
        })
    return devices


def is_onlykey_present(usb_manager):
    try:
        return any(
            d['vid'] == ONLYKEY_VID and d['pid'] == ONLYKEY_PID
            for d in enumerate_devices(usb_manager)
        )
    except Exception:
        return False


# ----------------------------------------------------------------
# File IO — sync with android/state.py schema. Duplicated minimally
# here so the service doesn't have to import the Activity-side state
# helpers (which depend on PythonActivity that doesn't exist in service).
# ----------------------------------------------------------------

def _files_dir(service):
    return service.getFilesDir().getAbsolutePath()


def write_atomic(path, content):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(content)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def read_arm_state(files_dir):
    s = read_json(os.path.join(files_dir, 'arm.json'), {})
    return {
        'armed': bool(s.get('armed', False)),
        'delay': int(s.get('delay', 3)),
    }


def read_settings(files_dir):
    s = read_json(os.path.join(files_dir, 'settings.json'), {})
    return {
        'trig_lock': bool(s.get('trig_lock', True)),
        'trig_wipe': bool(s.get('trig_wipe', False)),
        'wipe_confirm': bool(s.get('wipe_confirm', False)),
        'wipe_on_admin_disable': bool(s.get('wipe_on_admin_disable', False)),
        'wipe_on_force_stop': bool(s.get('wipe_on_force_stop', False)),
    }


# ----------------------------------------------------------------
# Audio + haptic feedback (M5)
# ----------------------------------------------------------------

def play_beep(service, escalation=0):
    """
    Fire-and-forget short tone. `escalation` 0..N — higher = louder/longer.
    Uses ToneGenerator (no audio file needed, no MediaPlayer state to manage).
    """
    try:
        ToneGenerator = autoclass('android.media.ToneGenerator')
        AudioManager = autoclass('android.media.AudioManager')

        # Louder + slightly longer tone as the countdown escalates
        volume = min(80 + escalation * 4, 100)
        # ToneGenerator wants AudioManager stream constants
        tg = ToneGenerator(AudioManager.STREAM_ALARM, volume)
        # TONE_PROP_BEEP is a short alert beep
        duration_ms = 150 + escalation * 30
        tg.startTone(ToneGenerator.TONE_PROP_BEEP, duration_ms)
        # tg goes out of scope; the tone plays asynchronously and tg
        # gets GC'd. Acceptable for short fire-and-forget beeps.
    except Exception:
        # Don't let audio failures stop the trigger
        print('[opencik-svc] beep failed:')
        traceback.print_exc()


def vibrate(service, ms, escalation=0):
    """Short vibration. `escalation` makes it more intense."""
    try:
        Context = autoclass('android.content.Context')
        # On Android 12+ use VibratorManager; older API uses VIBRATOR_SERVICE
        try:
            VibratorManager = autoclass('android.os.VibratorManager')
            vmgr = get_context(service).getSystemService(
                Context.VIBRATOR_MANAGER_SERVICE
            )
            vibrator = vmgr.getDefaultVibrator()
        except Exception:
            vibrator = get_context(service).getSystemService(
                Context.VIBRATOR_SERVICE
            )

        # Build a VibrationEffect (one-shot)
        VibrationEffect = autoclass('android.os.VibrationEffect')
        amplitude = min(120 + escalation * 30, 255)
        effect = VibrationEffect.createOneShot(int(ms), amplitude)
        vibrator.vibrate(effect)
    except Exception:
        print('[opencik-svc] vibrate failed:')
        traceback.print_exc()


# ----------------------------------------------------------------
# Trigger dispatchers (M4 + M7)
# ----------------------------------------------------------------

def fire_lock(service):
    try:
        dpm = get_system_service(service, 'DEVICE_POLICY_SERVICE')
        admin = get_admin_component(service)
        if not dpm.isAdminActive(admin):
            print('[opencik-svc] TRIGGER lock: admin not granted')
            return False
        dpm.lockNow()
        print('[opencik-svc] TRIGGER lock: lockNow() fired')
        return True
    except Exception:
        print('[opencik-svc] TRIGGER lock failed:')
        traceback.print_exc()
        return False


def fire_wipe(service):
    """
    Factory wipe via DevicePolicyManager.wipeData(0).
    Caller must have already handled the optional confirmation prompt
    (if wipe_confirm is True). This is the point-of-no-return.
    """
    try:
        dpm = get_system_service(service, 'DEVICE_POLICY_SERVICE')
        admin = get_admin_component(service)
        if not dpm.isAdminActive(admin):
            print('[opencik-svc] TRIGGER wipe: admin not granted')
            return False
        # 0 = no flags. Use WIPE_RESET_PROTECTION_DATA=2 to also reset
        # FRP (Factory Reset Protection). We leave it at 0; user can
        # add a setting for it later if needed.
        dpm.wipeData(0)
        print('[opencik-svc] TRIGGER wipe: wipeData(0) fired — goodbye')
        return True
    except Exception:
        print('[opencik-svc] TRIGGER wipe failed:')
        traceback.print_exc()
        return False


def request_wipe_confirmation(files_dir):
    """
    Write a sentinel file the Activity polls. The Activity, when it
    sees this file, pops a modal asking the user to confirm or cancel
    the wipe. The Activity writes the result back to the same file.
    The service polls for the result; if 'confirmed', fires wipe.

    Returns 'confirmed' | 'cancelled' | 'timeout'.
    Blocks the service for up to 30 seconds waiting for user decision.
    """
    path = os.path.join(files_dir, 'pending_wipe.json')
    write_atomic(path, json.dumps({'state': 'requested', 'ts': time.time()}))
    print('[opencik-svc] wipe confirmation requested; waiting up to 30s')

    deadline = time.time() + 30
    while time.time() < deadline:
        s = read_json(path, {})
        if s.get('state') == 'confirmed':
            print('[opencik-svc] wipe confirmed by user')
            return 'confirmed'
        if s.get('state') == 'cancelled':
            print('[opencik-svc] wipe cancelled by user')
            return 'cancelled'
        time.sleep(0.2)

    print('[opencik-svc] wipe confirmation timed out')
    return 'timeout'


# ----------------------------------------------------------------
# Countdown + dispatch (M5)
# ----------------------------------------------------------------

def run_countdown_and_fire(service, usb_manager, delay, settings, files_dir):
    """
    Run the countdown after we've detected the trigger condition.
    Returns True if triggers fired, False if aborted (replug).
    """

    print(f'[opencik-svc] countdown start: delay={delay}s')

    # Immediate fire if delay == 0
    if delay <= 0:
        return _dispatch_triggers(service, settings, files_dir)

    # Each second is split into 10 ticks. We beep+vibrate at the start
    # of each second (escalation = seconds elapsed).
    ticks_per_sec = int(1.0 / COUNTDOWN_TICK)
    total_ticks = delay * ticks_per_sec

    for tick in range(total_ticks):
        # Beep + haptic at the top of each second, escalating
        if tick % ticks_per_sec == 0:
            seconds_elapsed = tick // ticks_per_sec
            play_beep(service, escalation=seconds_elapsed)
            vibrate(service, ms=180 + seconds_elapsed * 40,
                    escalation=seconds_elapsed)
            print(f'[opencik-svc] countdown tick: '
                  f'{delay - seconds_elapsed}s remaining')
            # Write status snapshot so UI can render "TRIGGER IN N SEC"
            _write_status_now(
                service, files_dir,
                countdown_remaining=delay - seconds_elapsed,
            )

        # Abort check — was OnlyKey re-plugged?
        if is_onlykey_present(usb_manager):
            print('[opencik-svc] countdown ABORTED — OnlyKey re-plugged')
            _write_status_now(service, files_dir, countdown_remaining=None,
                              last_event='aborted')
            return False

        time.sleep(COUNTDOWN_TICK)

    # Countdown expired — fire
    _write_status_now(service, files_dir, countdown_remaining=0)
    return _dispatch_triggers(service, settings, files_dir)


def _dispatch_triggers(service, settings, files_dir):
    """Fire enabled triggers in order: lock first (fast), then wipe."""
    fired_any = False

    if settings['trig_lock']:
        if fire_lock(service):
            fired_any = True

    if settings['trig_wipe']:
        if settings['wipe_confirm']:
            result = request_wipe_confirmation(files_dir)
            if result != 'confirmed':
                # User cancelled or timed out — skip wipe
                print(f'[opencik-svc] skipping wipe ({result})')
                return fired_any

        if fire_wipe(service):
            fired_any = True
            # Note: device may be partway through wiping at this point —
            # any further code may not execute.

    return fired_any


# ----------------------------------------------------------------
# Status writer
# ----------------------------------------------------------------

# Module-level cache of last-good devices/state for quick snapshot writes
_LAST_STATE = {
    'devices': [],
    'onlykey_present': False,
    'last_event': None,
}


def _write_status_now(service, files_dir, countdown_remaining=None,
                      last_event=None, armed=None, tick=None):
    if last_event is not None:
        _LAST_STATE['last_event'] = last_event
    snap = {
        'ts': time.time(),
        'tick': tick,
        'onlykey_present': _LAST_STATE['onlykey_present'],
        'armed': armed,
        'countdown_remaining': countdown_remaining,
        'last_event': _LAST_STATE['last_event'],
        'devices': _LAST_STATE['devices'],
    }
    try:
        write_atomic(os.path.join(files_dir, 'status.json'),
                     json.dumps(snap))
    except Exception:
        traceback.print_exc()


# ----------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------

def main():
    service = get_service()
    usb_manager = get_system_service(service, 'USB_SERVICE')
    files_dir = _files_dir(service)

    print(f'[opencik-svc] starting; files_dir={files_dir}')

    tick = 0
    last_onlykey_present = None  # None on first iter, then True/False

    while True:
        tick += 1
        try:
            devices = enumerate_devices(usb_manager)
        except Exception:
            print('[opencik-svc] enum error:')
            traceback.print_exc()
            devices = []

        onlykey_present = any(
            d['vid'] == ONLYKEY_VID and d['pid'] == ONLYKEY_PID
            for d in devices
        )
        _LAST_STATE['devices'] = devices
        _LAST_STATE['onlykey_present'] = onlykey_present

        arm = read_arm_state(files_dir)
        settings = read_settings(files_dir)

        # Detect trigger condition: armed AND present->absent transition
        if (arm['armed']
                and last_onlykey_present is True
                and onlykey_present is False):
            print(f'[opencik-svc] TRIGGER CONDITION at tick {tick}: '
                  f'delay={arm["delay"]}s, '
                  f'lock={settings["trig_lock"]}, '
                  f'wipe={settings["trig_wipe"]}, '
                  f'confirm={settings["wipe_confirm"]}')
            _LAST_STATE['last_event'] = 'triggered'

            # Enter countdown — this method blocks until countdown
            # completes or is aborted by replug.
            run_countdown_and_fire(
                service, usb_manager,
                delay=arm['delay'],
                settings=settings,
                files_dir=files_dir,
            )
            # After this point: if wipe was confirmed, the device is
            # being wiped and we may not reach the next line.

        # Write normal status snapshot
        _write_status_now(service, files_dir, tick=tick, armed=arm['armed'])

        # Heartbeat log — chatty when armed
        if tick % 10 == 0 or arm['armed']:
            print(f'[opencik-svc] tick={tick} armed={arm["armed"]} '
                  f'onlykey={onlykey_present} devs={len(devices)}')

        last_onlykey_present = onlykey_present
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
