"""
openCIK Android - M4: device-admin grant flow + lock-screen trigger.

Adds on top of M3:
  - Reads & displays device-admin granted/not-granted state.
  - "Grant device admin" button that launches the system Settings dialog.
  - Arm/Disarm toggle. Arming only possible when OnlyKey is present AND
    device admin is granted. Disarming is unrestricted for now —
    PIN-gated disarm comes in M6.
  - Arm state is written to arm.json, which the service reads each tick.
    On a present->absent transition while armed, the service calls
    DevicePolicyManager.lockNow().
  - "Test lock now" button (visible when admin granted) — fires lockNow
    directly so you can verify the trigger plumbing without unplugging.

UI structure (top to bottom):
  - Title
  - Big arm/disarm button
  - OnlyKey status
  - Device admin status + grant button
  - Service status
  - USB device list (scrollable)
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

SERVICE_CLASS = 'io.crystalheeler.opencik.ServiceMonitor'
ADMIN_RECEIVER_CLASS = 'io.crystalheeler.opencik.AdminReceiver'


# -----------------------------------------------------------------------------
# Pyjnius helpers (no-op on desktop)
# -----------------------------------------------------------------------------

def _is_android():
    return platform == 'android'


def get_activity():
    if not _is_android():
        return None
    from jnius import autoclass
    return autoclass('org.kivy.android.PythonActivity').mActivity


def get_context():
    activity = get_activity()
    return activity.getApplicationContext() if activity else None


def get_device_policy_manager():
    """Get Android's DevicePolicyManager system service, or None on desktop."""
    if not _is_android():
        return None
    from jnius import autoclass
    Context = autoclass('android.content.Context')
    return get_context().getSystemService(Context.DEVICE_POLICY_SERVICE)


def get_admin_component():
    """Build the ComponentName for our AdminReceiver."""
    if not _is_android():
        return None
    from jnius import autoclass
    ComponentName = autoclass('android.content.ComponentName')
    return ComponentName(get_context(), ADMIN_RECEIVER_CLASS)


def is_admin_active():
    """True iff the user has granted us Device Admin via Settings."""
    if not _is_android():
        return False
    try:
        dpm = get_device_policy_manager()
        return bool(dpm.isAdminActive(get_admin_component()))
    except Exception as e:
        print(f'[opencik] is_admin_active failed: {e!r}')
        return False


def request_admin():
    """
    Launch the system 'add device admin' dialog.

    Returns (ok: bool, error: str|None). Caller surfaces errors in UI.

    Implementation note: Pyjnius can't reliably pick the correct
    putExtra() overload when handing it a ComponentName (it has many
    overloads, several of which would silently misinterpret the
    object). The safest path is to use a Bundle with the explicitly-
    typed putParcelable, then attach the Bundle via putExtras.
    """
    if not _is_android():
        return False, 'not on android'
    try:
        from jnius import autoclass, cast
        Intent = autoclass('android.content.Intent')
        DevicePolicyManager = autoclass('android.app.admin.DevicePolicyManager')
        Bundle = autoclass('android.os.Bundle')

        intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)

        component = get_admin_component()
        bundle = Bundle()
        bundle.putParcelable(
            DevicePolicyManager.EXTRA_DEVICE_ADMIN,
            cast('android.os.Parcelable', component),
        )
        bundle.putString(
            DevicePolicyManager.EXTRA_ADD_EXPLANATION,
            'openCIK needs device-admin access so it can lock (and '
            'optionally factory-reset) the device when your OnlyKey is '
            'removed while armed. Without this grant, the trigger has '
            'no way to act.',
        )
        intent.putExtras(bundle)

        get_activity().startActivity(intent)
        return True, None
    except Exception as e:
        msg = f'request_admin failed: {e!r}'
        print(f'[opencik] {msg}')
        return False, msg


def request_notification_permission():
    if not _is_android():
        return
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.POST_NOTIFICATIONS])
    except Exception as e:
        print(f'[opencik] notification permission request skipped: {e!r}')


def start_monitor_service():
    if not _is_android():
        return None
    from jnius import autoclass
    activity = get_activity()
    svc = autoclass(SERVICE_CLASS)
    svc.start(activity, '')
    return svc


# -----------------------------------------------------------------------------
# File paths shared with the service
# -----------------------------------------------------------------------------

def app_files_dir():
    if not _is_android():
        return os.path.expanduser('~')
    return get_activity().getFilesDir().getAbsolutePath()


def status_path():
    return os.path.join(app_files_dir(), 'status.json')


def arm_path():
    return os.path.join(app_files_dir(), 'arm.json')


def write_arm_state(armed):
    payload = {'armed': bool(armed), 'armed_at': time.time() if armed else 0}
    tmp = arm_path() + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, arm_path())


def read_arm_state():
    try:
        with open(arm_path()) as f:
            return json.load(f).get('armed', False)
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Root widget
# -----------------------------------------------------------------------------

# Colors
COLOR_GREEN = (0.25, 0.85, 0.4, 1)
COLOR_RED = (0.85, 0.3, 0.3, 1)
COLOR_AMBER = (1, 0.7, 0.25, 1)
COLOR_DIM = (0.65, 0.65, 0.65, 1)


class OpenCikRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 16
        self.spacing = 10

        self._status = None  # last parsed status.json
        self._armed = read_arm_state()

        # --- title ---
        self.add_widget(Label(
            text='openCIK',
            font_size='34sp',
            bold=True,
            size_hint=(1, 0.09),
        ))

        # --- big arm/disarm button ---
        self.arm_button = Button(
            text='ARM',
            font_size='28sp',
            bold=True,
            size_hint=(1, 0.18),
            background_normal='',
            background_color=COLOR_GREEN,
        )
        self.arm_button.bind(on_release=self._on_arm_button)
        self.add_widget(self.arm_button)

        # --- OnlyKey state ---
        self.onlykey_label = Label(
            text='OnlyKey: ...',
            font_size='20sp',
            size_hint=(1, 0.07),
        )
        self.add_widget(self.onlykey_label)

        # --- device admin state ---
        self.admin_label = Label(
            text='Device admin: ?',
            font_size='15sp',
            size_hint=(1, 0.05),
        )
        self.add_widget(self.admin_label)

        # Grant device admin button (only visible when admin not granted)
        self.grant_button = Button(
            text='Grant device admin',
            font_size='14sp',
            size_hint=(1, 0.08),
        )
        self.grant_button.bind(on_release=self._on_grant)
        self.add_widget(self.grant_button)

        # --- service / hint line ---
        self.svc_label = Label(
            text='service: ...',
            font_size='12sp',
            size_hint=(1, 0.04),
            color=COLOR_DIM,
        )
        self.add_widget(self.svc_label)

        # --- divider ---
        self.add_widget(Label(
            text='---- attached USB devices ----',
            font_size='12sp',
            size_hint=(1, 0.03),
            color=COLOR_DIM,
        ))

        # --- scrollable device list ---
        scroll = ScrollView(size_hint=(1, 0.39))
        self.device_grid = GridLayout(cols=1, spacing=4, size_hint_y=None)
        self.device_grid.bind(
            minimum_height=self.device_grid.setter('height'),
        )
        scroll.add_widget(self.device_grid)
        self.add_widget(scroll)

        # Kick off
        request_notification_permission()
        try:
            self.service = start_monitor_service()
            self.svc_label.text = (
                'service: started' if self.service else 'service: N/A (desktop)'
            )
            self.svc_label.color = COLOR_GREEN if self.service else COLOR_DIM
        except Exception as e:
            self.svc_label.text = f'service start failed: {e!r}'
            self.svc_label.color = COLOR_RED

        self._refresh()
        Clock.schedule_interval(self._refresh_clock, 1.0)

    # --- handlers ---

    def _on_grant(self, _btn):
        ok, err = request_admin()
        if not ok:
            self.svc_label.text = err or 'grant failed (unknown)'
            self.svc_label.color = COLOR_RED

    def _on_arm_button(self, _btn):
        if self._armed:
            # disarm — for M4 unrestricted; PIN gate lands in M6
            self._armed = False
            write_arm_state(False)
        else:
            # arm only if preconditions met
            if not self._onlykey_present():
                self.svc_label.text = (
                    'cannot arm: OnlyKey must be plugged in first'
                )
                self.svc_label.color = COLOR_AMBER
                return
            if not is_admin_active():
                self.svc_label.text = (
                    'cannot arm: grant device admin first'
                )
                self.svc_label.color = COLOR_AMBER
                return
            self._armed = True
            write_arm_state(True)
        self._refresh()

    def _refresh_clock(self, _dt):
        self._refresh()

    # --- helpers ---

    def _onlykey_present(self):
        if not self._status:
            return False
        return bool(self._status.get('onlykey_present'))

    def _refresh(self):
        # Pull latest service status
        try:
            with open(status_path()) as f:
                self._status = json.load(f)
        except Exception:
            self._status = None

        admin = is_admin_active()
        onlykey = self._onlykey_present()

        # --- arm button look ---
        if self._armed:
            self.arm_button.text = 'DISARM'
            self.arm_button.background_color = COLOR_RED
        else:
            self.arm_button.text = 'ARM'
            self.arm_button.background_color = COLOR_GREEN
            # dim when preconditions not met
            if not (onlykey and admin):
                self.arm_button.background_color = (
                    self.arm_button.background_color[0] * 0.45,
                    self.arm_button.background_color[1] * 0.45,
                    self.arm_button.background_color[2] * 0.45,
                    1,
                )

        # --- OnlyKey label ---
        if not _is_android():
            self.onlykey_label.text = 'OnlyKey: N/A (desktop)'
            self.onlykey_label.color = COLOR_DIM
        elif onlykey:
            self.onlykey_label.text = 'OnlyKey: PRESENT'
            self.onlykey_label.color = COLOR_GREEN
        else:
            self.onlykey_label.text = 'OnlyKey: absent'
            self.onlykey_label.color = COLOR_AMBER

        # --- admin label ---
        if not _is_android():
            self.admin_label.text = 'Device admin: N/A (desktop)'
            self.admin_label.color = COLOR_DIM
        elif admin:
            self.admin_label.text = 'Device admin: GRANTED'
            self.admin_label.color = COLOR_GREEN
        else:
            self.admin_label.text = 'Device admin: NOT GRANTED'
            self.admin_label.color = COLOR_AMBER

        # Show grant button only when not granted (height collapses too,
        # via a size_hint trick: 0.08 when visible, 0.001 when hidden)
        self.grant_button.opacity = 0 if admin else 1
        self.grant_button.disabled = admin
        self.grant_button.size_hint = (1, 0.001 if admin else 0.08)

        # --- svc status freshness ---
        if self._status is None:
            self.svc_label.text = 'service: waiting for first tick...'
            self.svc_label.color = COLOR_DIM
        else:
            age = time.time() - self._status.get('ts', 0)
            tick = self._status.get('tick', '?')
            if age > 5:
                self.svc_label.text = f'⚠ service stale ({age:.1f}s old)'
                self.svc_label.color = COLOR_AMBER
            else:
                self.svc_label.text = f'service: live · tick {tick}'
                self.svc_label.color = COLOR_GREEN

        # --- device list ---
        self.device_grid.clear_widgets()
        devices = (self._status or {}).get('devices', [])
        if not devices:
            self.device_grid.add_widget(Label(
                text='(no USB devices)',
                font_size='14sp',
                size_hint_y=None,
                height=36,
                color=COLOR_DIM,
            ))
        else:
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
                    font_size='13sp',
                    size_hint_y=None,
                    height=62,
                    color=COLOR_GREEN if is_ok else (1, 1, 1, 1),
                ))


class OpenCikApp(App):
    title = 'openCIK'

    def build(self):
        return OpenCikRoot()


if __name__ == '__main__':
    OpenCikApp().run()
