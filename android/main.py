"""
openCIK Android - M3: foreground-service-backed monitoring.

The actual USB polling now lives in service/monitor.py, started as a
foreground Android service. This UI is a thin observer that reads the
JSON status file the service writes to app-private storage.

This means USB monitoring survives backgrounding the app — exactly
what we'll need once the trigger logic lands in later milestones.
"""

import json
import os
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.utils import platform


ONLYKEY_VID = 0x1D50
ONLYKEY_PID = 0x60FC

# JS-ish "package name . capitalized service name" — see buildozer.spec:
#   services = monitor:service/monitor.py:foreground
# p4a generates a Java class named ServiceMonitor under our package.
SERVICE_CLASS = 'io.crystalheeler.opencik.ServiceMonitor'


def request_notification_permission():
    """
    Request POST_NOTIFICATIONS at runtime (Android 13+ requirement).
    Without this, the foreground-service notification is silently
    suppressed and Android may then kill our 'foreground' service
    after a few minutes under battery pressure (Samsung is notably
    aggressive about this).

    Uses python-for-android's android.permissions helper. This is
    fire-and-forget — Android shows a system dialog asynchronously
    and the user accepts or declines. We don't block on the result;
    the service still tries to start either way.
    """
    if platform != 'android':
        return
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.POST_NOTIFICATIONS])
    except Exception as e:
        # On Android < 13, Permission.POST_NOTIFICATIONS may not be
        # defined in the android.permissions enum. That's fine —
        # pre-API-33 doesn't need runtime grant for notifications.
        print(f'[opencik] notification permission request skipped: {e!r}')


def start_monitor_service():
    """
    Start the foreground monitor service. Idempotent — Android will
    not start it twice if already running. No-op on desktop.
    """
    if platform != 'android':
        return None
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    activity = PythonActivity.mActivity
    svc = autoclass(SERVICE_CLASS)
    # p4a's generated service start() takes (context, argument-string)
    svc.start(activity, '')
    return svc


def get_status_path():
    """
    Path to the shared status JSON file written by the service.
    Falls back to a per-user path on desktop so the file still imports
    cleanly for layout debugging.
    """
    if platform != 'android':
        return os.path.join(os.path.expanduser('~'), 'opencik-status.json')
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    activity = PythonActivity.mActivity
    return os.path.join(
        activity.getFilesDir().getAbsolutePath(),
        'status.json',
    )


class OpenCikRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 20
        self.spacing = 10

        self.status_path = get_status_path()
        self.service = None

        # --- Title ---
        self.add_widget(Label(
            text='openCIK',
            font_size='36sp',
            bold=True,
            size_hint=(1, 0.11),
        ))

        # --- Headline state ---
        self.status_label = Label(
            text='OnlyKey: ...',
            font_size='28sp',
            bold=True,
            size_hint=(1, 0.14),
        )
        self.add_widget(self.status_label)

        # --- Service status line ---
        self.svc_label = Label(
            text='service: starting...',
            font_size='13sp',
            size_hint=(1, 0.05),
            color=(0.7, 0.7, 0.7, 1),
        )
        self.add_widget(self.svc_label)

        # --- Hint line ---
        self.hint_label = Label(
            text='',
            font_size='13sp',
            size_hint=(1, 0.05),
            color=(0.85, 0.85, 0.85, 1),
        )
        self.add_widget(self.hint_label)

        # --- Divider ---
        self.add_widget(Label(
            text='---- attached USB devices ----',
            font_size='13sp',
            size_hint=(1, 0.04),
            color=(0.6, 0.6, 0.6, 1),
        ))

        # --- Scrollable device list ---
        scroll = ScrollView(size_hint=(1, 0.51))
        self.device_grid = GridLayout(
            cols=1, spacing=6, size_hint_y=None,
        )
        self.device_grid.bind(
            minimum_height=self.device_grid.setter('height'),
        )
        scroll.add_widget(self.device_grid)
        self.add_widget(scroll)

        # --- Manual refresh ---
        refresh_btn = Button(
            text='Refresh now',
            size_hint=(1, 0.09),
            font_size='17sp',
        )
        refresh_btn.bind(on_release=lambda _b: self._refresh())
        self.add_widget(refresh_btn)

        # Request POST_NOTIFICATIONS (Android 13+) BEFORE starting the
        # service so the foreground-service notification is permitted
        # to show. The dialog is async; if the user denies we still
        # start the service but Android may eventually kill it.
        request_notification_permission()

        # Start service
        try:
            self.service = start_monitor_service()
            if self.service is not None:
                self.svc_label.text = 'service: started'
                self.svc_label.color = (0.6, 1, 0.6, 1)
            else:
                self.svc_label.text = 'service: N/A (desktop)'
        except Exception as e:
            self.svc_label.text = f'service start failed: {e}'
            self.svc_label.color = (1, 0.4, 0.4, 1)

        # Initial UI populate + 1-Hz poll of status file
        self._refresh()
        Clock.schedule_interval(self._refresh_clock, 1.0)

    # --- helpers ---

    def _refresh_clock(self, _dt):
        self._refresh()

    def _refresh(self):
        status = None
        read_err = None
        try:
            with open(self.status_path) as f:
                status = json.load(f)
        except FileNotFoundError:
            read_err = 'no status file yet (service may still be starting)'
        except Exception as e:
            read_err = f'read error: {e!r}'

        if status is None:
            self.status_label.text = 'OnlyKey: (unknown)'
            self.status_label.color = (0.7, 0.7, 0.7, 1)
            self.hint_label.text = read_err or ''
            self.hint_label.color = (1, 0.65, 0.4, 1)
            self.device_grid.clear_widgets()
            self.device_grid.add_widget(Label(
                text='(waiting for first service tick)',
                font_size='14sp',
                size_hint_y=None,
                height=42,
                color=(0.65, 0.65, 0.65, 1),
            ))
            return

        age = time.time() - status.get('ts', 0)
        devices = status.get('devices', [])
        onlykey = status.get('onlykey_present', False)
        tick = status.get('tick', '?')

        # Headline
        if onlykey:
            self.status_label.text = 'OnlyKey: PRESENT'
            self.status_label.color = (0.3, 1, 0.4, 1)
        else:
            self.status_label.text = 'OnlyKey: absent'
            self.status_label.color = (1, 0.65, 0.25, 1)

        # Hint: show service freshness
        if age > 5:
            self.hint_label.text = (
                f'⚠ status stale ({age:.1f}s old) — service may be stopped'
            )
            self.hint_label.color = (1, 0.55, 0.3, 1)
        elif onlykey:
            self.hint_label.text = f'detection live · tick {tick}'
            self.hint_label.color = (0.85, 1, 0.85, 1)
        else:
            self.hint_label.text = f'plug in OnlyKey to test · tick {tick}'
            self.hint_label.color = (0.85, 0.85, 0.85, 1)

        # Device list
        self.device_grid.clear_widgets()
        if not devices:
            self.device_grid.add_widget(Label(
                text='(no USB devices)',
                font_size='14sp',
                size_hint_y=None,
                height=42,
                color=(0.65, 0.65, 0.65, 1),
            ))
            return

        for d in devices:
            is_ok = (
                d['vid'] == ONLYKEY_VID and d['pid'] == ONLYKEY_PID
            )
            prefix = '[OnlyKey] ' if is_ok else ''
            text = (
                f"{prefix}{d['product']}\n"
                f"VID:{d['vid']:04X}  PID:{d['pid']:04X}"
            )
            self.device_grid.add_widget(Label(
                text=text,
                font_size='14sp',
                size_hint_y=None,
                height=68,
                halign='left',
                valign='middle',
                color=(0.3, 1, 0.4, 1) if is_ok else (1, 1, 1, 1),
            ))


class OpenCikApp(App):
    title = 'openCIK'

    def build(self):
        return OpenCikRoot()


if __name__ == '__main__':
    OpenCikApp().run()
