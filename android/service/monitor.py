"""
openCIK Android foreground service: USB monitor + trigger dispatcher.

Polls UsbManager once per second. Writes current state to status.json
so the UI can render. Reads arm.json each tick to see whether the user
has armed the app.

When (armed) AND (OnlyKey was present last tick) AND (OnlyKey is absent
this tick): fires the trigger. M4 only supports the lock-screen trigger
via DevicePolicyManager.lockNow(). M5 adds the configurable countdown
with audio/haptic; M7 adds the wipe trigger.
"""

import json
import os
import time
import traceback

from jnius import autoclass


ONLYKEY_VID = 0x1D50
ONLYKEY_PID = 0x60FC

POLL_INTERVAL = 1.0  # seconds

ADMIN_RECEIVER_CLASS = 'io.crystalheeler.opencik.AdminReceiver'


def get_service():
    return autoclass('org.kivy.android.PythonService').mService


def get_context(service):
    return service.getApplicationContext()


def get_system_service(service, name):
    Context = autoclass('android.content.Context')
    return get_context(service).getSystemService(
        getattr(Context, name)
    )


def get_admin_component(service):
    ComponentName = autoclass('android.content.ComponentName')
    return ComponentName(get_context(service), ADMIN_RECEIVER_CLASS)


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


def write_atomic(path, content):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(content)
    os.replace(tmp, path)


def read_arm_state(arm_path):
    """Read the armed flag written by main.py. Default False if missing."""
    try:
        with open(arm_path) as f:
            return bool(json.load(f).get('armed', False))
    except Exception:
        return False


def fire_lock_trigger(service):
    """
    Call DevicePolicyManager.lockNow(). Requires Device Admin to be
    granted; raises SecurityException otherwise. We catch + log so the
    service doesn't crash; if admin wasn't granted, the trigger just
    no-ops (UI should warn user before allowing arming).
    """
    try:
        dpm = get_system_service(service, 'DEVICE_POLICY_SERVICE')
        admin = get_admin_component(service)
        if not dpm.isAdminActive(admin):
            print('[opencik-svc] TRIGGER: device admin not granted, '
                  'cannot lock')
            return False
        dpm.lockNow()
        print('[opencik-svc] TRIGGER: lockNow() fired')
        return True
    except Exception:
        print('[opencik-svc] TRIGGER: lockNow() failed:')
        traceback.print_exc()
        return False


def main():
    service = get_service()
    usb_manager = get_system_service(service, 'USB_SERVICE')
    files_dir = get_context(service).getFilesDir().getAbsolutePath()
    status_path = os.path.join(files_dir, 'status.json')
    arm_path = os.path.join(files_dir, 'arm.json')

    print(f'[opencik-svc] starting; status: {status_path} arm: {arm_path}')

    tick = 0
    last_onlykey_present = None  # None=first iter, True/False thereafter

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
        armed = read_arm_state(arm_path)

        # ----- detect trigger condition -----
        # Trigger when: armed AND OnlyKey was present last tick AND now absent.
        # Don't trigger on the first iteration (last_onlykey_present is None)
        # since we have no "before" state to compare against.
        triggered = False
        if (armed
                and last_onlykey_present is True
                and onlykey_present is False):
            print(f'[opencik-svc] TRIGGER condition met: armed=True, '
                  f'transition present->absent at tick {tick}')
            triggered = True
            fire_lock_trigger(service)

        # ----- write status -----
        status = {
            'ts': time.time(),
            'tick': tick,
            'onlykey_present': onlykey_present,
            'armed': armed,
            'last_trigger_tick': tick if triggered else None,
            'devices': devices,
        }
        try:
            write_atomic(status_path, json.dumps(status))
        except Exception:
            print('[opencik-svc] write error:')
            traceback.print_exc()

        # Heartbeat — chatty when armed or transitioning, quiet otherwise
        if (tick % 10 == 0
                or armed
                or onlykey_present != last_onlykey_present):
            print(f'[opencik-svc] tick={tick} armed={armed} '
                  f'onlykey={onlykey_present} devs={len(devices)}')

        last_onlykey_present = onlykey_present
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
