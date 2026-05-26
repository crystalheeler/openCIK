"""
openCIK Android foreground service: USB monitor.

Runs as a separate Python process started by main.py. Polls Android's
UsbManager once per second, writes the current USB state to a JSON
status file in app-private storage so the UI can render it.

Eventually this service will also fire the lock/wipe trigger when an
armed OnlyKey is removed. For M3 it's monitoring-only.

Lifetime:
- Started by main.py via ServiceMonitor.start(activity, '').
- Survives the main Activity being backgrounded because it's a
  foreground service (declared in buildozer.spec: services=monitor:...).
- Foreground services on Android need a persistent notification;
  python-for-android's service template supplies a default one.
"""

import json
import os
import time
import traceback

from jnius import autoclass


# OnlyKey USB identifiers (same constants used everywhere in this app)
ONLYKEY_VID = 0x1D50
ONLYKEY_PID = 0x60FC

POLL_INTERVAL = 1.0  # seconds


def get_service():
    """Get the running Service instance (set by p4a at startup)."""
    PythonService = autoclass('org.kivy.android.PythonService')
    return PythonService.mService


def get_usb_manager(service):
    Context = autoclass('android.content.Context')
    return service.getSystemService(Context.USB_SERVICE)


def get_files_dir(service):
    return service.getFilesDir().getAbsolutePath()


def enumerate_devices(usb_manager):
    """Return [{name, product, vid, pid}, ...] for attached USB devices."""
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
    """Atomic write so readers never see a half-written file."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(content)
    os.replace(tmp, path)


def main():
    service = get_service()
    usb_manager = get_usb_manager(service)
    files_dir = get_files_dir(service)
    status_path = os.path.join(files_dir, 'status.json')

    print(f'[opencik-svc] starting; status file: {status_path}')

    tick = 0
    while True:
        tick += 1
        try:
            devices = enumerate_devices(usb_manager)
        except Exception:
            print('[opencik-svc] enum error:')
            traceback.print_exc()
            devices = []

        onlykey = any(
            d['vid'] == ONLYKEY_VID and d['pid'] == ONLYKEY_PID
            for d in devices
        )

        status = {
            'ts': time.time(),
            'tick': tick,
            'onlykey_present': onlykey,
            'devices': devices,
        }

        try:
            write_atomic(status_path, json.dumps(status))
        except Exception:
            print('[opencik-svc] write error:')
            traceback.print_exc()

        # Heartbeat to logcat. Cheap to filter on:
        #   adb logcat | grep opencik-svc
        # Only log every 10 ticks (~10 sec) to avoid log spam.
        if tick % 10 == 0 or onlykey:
            print(f'[opencik-svc] tick={tick} onlykey={onlykey} '
                  f'devs={len(devices)}')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
