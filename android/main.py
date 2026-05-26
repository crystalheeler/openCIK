"""
openCIK Android — M5..M8 build.

UI is now multi-screen:
  - MainScreen: OnlyKey status, ARM/DISARM, delay picker, Settings button
  - SettingsScreen: trigger toggles, PIN management, tampering defenses
  - PinScreen: set/change PIN (used for disarm gating)

Behavior layered in:
  M5 — configurable per-arm countdown (0/3/5/10 sec) with audio + haptic
       (the countdown itself lives in service/monitor.py)
  M6 — PIN-gated disarm
  M7 — independent trigger toggles (lock / wipe), confirmation-before-wipe
       toggle
  M8 — wipe-on-Admin-disable handled in AdminReceiver.java; toggle here
       (wipe-on-force-stop is intentionally deferred — needs WorkManager
       scaffolding + has reliability issues under battery saver)

The service does the heavy lifting; this file is the user-facing
controller + the wipe-confirmation popup handler.
"""

import json
import os
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.utils import platform

# shared state file IO (PIN hashing, settings, arm state)
import state


ONLYKEY_VID = 0x1D50
ONLYKEY_PID = 0x60FC

SERVICE_CLASS = 'io.crystalheeler.opencik.ServiceMonitor'
ADMIN_RECEIVER_CLASS = 'io.crystalheeler.opencik.AdminReceiver'

# Countdown choices on the main screen
DELAY_CHOICES = [0, 3, 5, 10]
DEFAULT_DELAY = 3

# Colors
COLOR_GREEN = (0.25, 0.85, 0.4, 1)
COLOR_RED = (0.85, 0.3, 0.3, 1)
COLOR_AMBER = (1, 0.7, 0.25, 1)
COLOR_DIM = (0.65, 0.65, 0.65, 1)
COLOR_WHITE = (1, 1, 1, 1)
COLOR_NAV_BG = (0.13, 0.59, 0.95, 1)


# ============================================================
# Android API helpers (Pyjnius)
# ============================================================

def _is_android():
    return platform == 'android'


def get_activity():
    if not _is_android():
        return None
    from jnius import autoclass
    return autoclass('org.kivy.android.PythonActivity').mActivity


def get_context():
    a = get_activity()
    return a.getApplicationContext() if a else None


def get_dpm():
    if not _is_android():
        return None
    from jnius import autoclass
    Context = autoclass('android.content.Context')
    return get_context().getSystemService(Context.DEVICE_POLICY_SERVICE)


def get_admin_component():
    if not _is_android():
        return None
    from jnius import autoclass
    ComponentName = autoclass('android.content.ComponentName')
    return ComponentName(get_context(), ADMIN_RECEIVER_CLASS)


def is_admin_active():
    if not _is_android():
        return False
    try:
        return bool(get_dpm().isAdminActive(get_admin_component()))
    except Exception:
        return False


def request_admin():
    if not _is_android():
        return False, 'not on android'
    try:
        from jnius import autoclass, cast
        Intent = autoclass('android.content.Intent')
        DevicePolicyManager = autoclass('android.app.admin.DevicePolicyManager')
        Bundle = autoclass('android.os.Bundle')

        intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
        bundle = Bundle()
        bundle.putParcelable(
            DevicePolicyManager.EXTRA_DEVICE_ADMIN,
            cast('android.os.Parcelable', get_admin_component()),
        )
        bundle.putString(
            DevicePolicyManager.EXTRA_ADD_EXPLANATION,
            'openCIK needs device-admin access so it can lock (and '
            'optionally factory-reset) the device when your OnlyKey is '
            'removed while armed.',
        )
        intent.putExtras(bundle)
        get_activity().startActivity(intent)
        return True, None
    except Exception as e:
        return False, repr(e)


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
    svc = autoclass(SERVICE_CLASS)
    svc.start(get_activity(), '')
    return svc


# ============================================================
# Modal popups
# ============================================================

def _modal(title, body, buttons):
    """
    Generic modal. `buttons` is a list of (label, callback) tuples.
    Callbacks receive the popup instance so they can dismiss it.
    """
    layout = BoxLayout(orientation='vertical', padding=14, spacing=12)
    layout.add_widget(Label(text=body, font_size='15sp', halign='center',
                             valign='middle'))
    row = BoxLayout(orientation='horizontal', spacing=8, size_hint=(1, 0.4))
    popup = Popup(title=title, content=layout,
                   size_hint=(0.85, 0.45), auto_dismiss=False)
    for label, cb in buttons:
        btn = Button(text=label, font_size='15sp')
        btn.bind(on_release=lambda _b, c=cb: c(popup))
        row.add_widget(btn)
    layout.add_widget(row)
    popup.open()
    return popup


class PinPopup(Popup):
    """Modal that asks for a PIN. Calls `on_ok(pin)` if user submits."""

    def __init__(self, title, body, on_ok, **kw):
        super().__init__(title=title, size_hint=(0.85, 0.5),
                          auto_dismiss=False, **kw)
        self._on_ok = on_ok

        root = BoxLayout(orientation='vertical', padding=14, spacing=10)
        root.add_widget(Label(text=body, font_size='14sp',
                               size_hint=(1, 0.3)))
        self.input = TextInput(
            password=True,
            multiline=False,
            input_filter='int',
            font_size='28sp',
            halign='center',
            size_hint=(1, 0.35),
        )
        root.add_widget(self.input)
        self.error = Label(text='', font_size='13sp', color=COLOR_RED,
                            size_hint=(1, 0.1))
        root.add_widget(self.error)

        btns = BoxLayout(orientation='horizontal', spacing=8,
                          size_hint=(1, 0.25))
        cancel_btn = Button(text='Cancel', font_size='15sp')
        cancel_btn.bind(on_release=lambda _b: self.dismiss())
        ok_btn = Button(text='OK', font_size='15sp')
        ok_btn.bind(on_release=lambda _b: self._submit())
        btns.add_widget(cancel_btn)
        btns.add_widget(ok_btn)
        root.add_widget(btns)
        self.content = root

    def set_error(self, msg):
        self.error.text = msg
        self.input.text = ''

    def _submit(self):
        pin = self.input.text.strip()
        if not pin:
            self.set_error('Enter a PIN')
            return
        self._on_ok(self, pin)


# ============================================================
# Main screen
# ============================================================

class MainScreen(Screen):

    def __init__(self, **kw):
        super().__init__(**kw)
        self._delay = DEFAULT_DELAY
        self._status = None
        self._armed_cached = False
        self._showing_wipe_modal = False

        root = BoxLayout(orientation='vertical', padding=14, spacing=8)

        root.add_widget(Label(text='openCIK', font_size='32sp', bold=True,
                                size_hint=(1, 0.10)))

        # OnlyKey + admin headline strip
        self.onlykey_label = Label(text='OnlyKey: ...', font_size='22sp',
                                     bold=True, size_hint=(1, 0.10))
        root.add_widget(self.onlykey_label)
        self.admin_label = Label(text='Device admin: ?', font_size='13sp',
                                  size_hint=(1, 0.04))
        root.add_widget(self.admin_label)

        # Delay header label (own row so it isn't squished)
        root.add_widget(Label(
            text='Delay before trigger',
            font_size='13sp', size_hint=(1, 0.04),
            color=COLOR_DIM,
        ))

        # Delay picker — 4 toggle buttons across the full row
        delay_row = BoxLayout(orientation='horizontal', spacing=6,
                                size_hint=(1, 0.09))
        self._delay_buttons = {}
        for d in DELAY_CHOICES:
            tb = ToggleButton(
                text=f'{d}s' if d > 0 else 'instant',
                group='delay', font_size='14sp',
                state='down' if d == DEFAULT_DELAY else 'normal',
            )
            tb.bind(on_release=lambda b, val=d: self._set_delay(val))
            self._delay_buttons[d] = tb
            delay_row.add_widget(tb)
        root.add_widget(delay_row)

        # Big arm/disarm button
        self.arm_button = Button(
            text='ARM', font_size='28sp', bold=True,
            size_hint=(1, 0.20),
            background_normal='', background_color=COLOR_GREEN,
        )
        self.arm_button.bind(on_release=self._on_arm)
        root.add_widget(self.arm_button)

        # Grant admin button (full-width). Only visible when admin not
        # yet granted; collapses to zero height when granted so the
        # Settings button doesn't shift around.
        self.grant_button = Button(text='Grant device admin', font_size='14sp',
                                     size_hint=(1, 0.08))
        self.grant_button.bind(on_release=self._on_grant)
        root.add_widget(self.grant_button)

        # Spacer to push Settings ~half-inch lower than the Arm button
        root.add_widget(Label(text='', size_hint=(1, 0.06)))

        # Settings button — centered, narrower than full width
        settings_row = BoxLayout(orientation='horizontal',
                                   size_hint=(1, 0.09))
        settings_row.add_widget(Label(text='', size_hint=(0.25, 1)))
        self.settings_button = Button(text='Settings', font_size='15sp',
                                        size_hint=(0.5, 1))
        self.settings_button.bind(on_release=self._on_settings)
        settings_row.add_widget(self.settings_button)
        settings_row.add_widget(Label(text='', size_hint=(0.25, 1)))
        root.add_widget(settings_row)

        # Hidden status label kept around so error/precondition text
        # has somewhere to land. Tiny font, dim color, no service tick
        # spam.
        self.status_label = Label(text='', font_size='12sp',
                                    size_hint=(1, 0.05),
                                    color=COLOR_DIM)
        root.add_widget(self.status_label)

        # Device list
        root.add_widget(Label(text='---- attached USB ----',
                                font_size='11sp', size_hint=(1, 0.03),
                                color=COLOR_DIM))
        scroll = ScrollView(size_hint=(1, 0.18))
        self.device_grid = GridLayout(cols=1, spacing=4, size_hint_y=None)
        self.device_grid.bind(
            minimum_height=self.device_grid.setter('height'))
        scroll.add_widget(self.device_grid)
        root.add_widget(scroll)

        self.add_widget(root)

    def on_pre_enter(self, *a):
        self._refresh(None)
        Clock.schedule_interval(self._refresh, 1.0)
        Clock.schedule_interval(self._check_wipe_confirmation, 0.3)

    def on_pre_leave(self, *a):
        Clock.unschedule(self._refresh)
        Clock.unschedule(self._check_wipe_confirmation)

    # --- handlers ---

    def _set_delay(self, value):
        self._delay = value
        # If armed, update arm.json so service sees the new value
        # next tick (only matters if we're armed; otherwise it's
        # written at arm time).
        if state.read_arm()['armed']:
            state.write_arm(True, delay=value)

    def _on_grant(self, _b):
        ok, err = request_admin()
        if not ok:
            self.status_label.text = err or 'grant failed'
            self.status_label.color = COLOR_RED

    def _on_settings(self, _b):
        self.manager.transition.direction = 'left'
        self.manager.current = 'settings'

    def _on_arm(self, _b):
        armed = state.read_arm()['armed']
        if armed:
            self._try_disarm()
        else:
            self._try_arm()

    def _try_arm(self):
        # Preconditions: OnlyKey present, admin granted (always required —
        # we need admin to fire any trigger), at least one trigger on.
        if not self._onlykey_present():
            self.status_label.text = 'Cannot arm: OnlyKey not detected'
            self.status_label.color = COLOR_AMBER
            return
        if not is_admin_active():
            self.status_label.text = 'Cannot arm: grant device admin first'
            self.status_label.color = COLOR_AMBER
            return
        if not state.any_trigger_enabled():
            self.status_label.text = ('Cannot arm: no triggers enabled '
                                       '(open Settings)')
            self.status_label.color = COLOR_AMBER
            return
        state.write_arm(True, delay=self._delay)
        self._refresh(None)

    def _try_disarm(self):
        if state.pin_is_set():
            # Pop the PIN modal
            def on_ok(popup, pin):
                if state.verify_pin(pin):
                    state.write_arm(False)
                    popup.dismiss()
                    self._refresh(None)
                else:
                    popup.set_error('Wrong PIN')
            PinPopup('Disarm', 'Enter PIN to disarm', on_ok).open()
        else:
            state.write_arm(False)
            self._refresh(None)

    # --- polling ---

    def _onlykey_present(self):
        return bool(self._status and self._status.get('onlykey_present'))

    def _refresh(self, _dt):
        try:
            with open(state._path('status.json')) as f:
                self._status = json.load(f)
        except Exception:
            self._status = None

        admin = is_admin_active()
        onlykey = self._onlykey_present()
        arm = state.read_arm()
        armed = arm['armed']
        self._armed_cached = armed
        countdown = (self._status or {}).get('countdown_remaining')

        # OnlyKey label
        if not _is_android():
            self.onlykey_label.text = 'OnlyKey: N/A (desktop)'
            self.onlykey_label.color = COLOR_DIM
        elif countdown is not None and countdown > 0:
            self.onlykey_label.text = f'TRIGGER IN {countdown}s'
            self.onlykey_label.color = COLOR_RED
        elif onlykey:
            self.onlykey_label.text = 'OnlyKey: PRESENT'
            self.onlykey_label.color = COLOR_GREEN
        else:
            self.onlykey_label.text = 'OnlyKey: absent'
            self.onlykey_label.color = COLOR_AMBER

        # Admin label
        if not _is_android():
            self.admin_label.text = 'Device admin: N/A (desktop)'
        elif admin:
            self.admin_label.text = 'Device admin: GRANTED'
            self.admin_label.color = COLOR_GREEN
        else:
            self.admin_label.text = 'Device admin: NOT GRANTED'
            self.admin_label.color = COLOR_AMBER

        # Grant button visibility
        self.grant_button.opacity = 0 if admin else 1
        self.grant_button.disabled = admin

        # Arm button look
        if armed:
            self.arm_button.text = 'DISARM'
            self.arm_button.background_color = COLOR_RED
        else:
            self.arm_button.text = 'ARM'
            self.arm_button.background_color = COLOR_GREEN
            if not (onlykey and admin and state.any_trigger_enabled()):
                self.arm_button.background_color = (
                    COLOR_GREEN[0] * 0.45, COLOR_GREEN[1] * 0.45,
                    COLOR_GREEN[2] * 0.45, 1)

        # Delay picker — disable while armed (it'd be confusing to let
        # the user change delay mid-arm; the current value is already
        # committed to arm.json). When armed we sync button state from
        # arm.json (so the committed value is shown). When NOT armed
        # we leave button states alone — self._delay is the source of
        # truth and _set_delay() already updated the buttons via the
        # ToggleButton group. (The previous version overwrote button
        # state from arm.json on every poll, making it impossible to
        # change the picker.)
        for d, btn in self._delay_buttons.items():
            btn.disabled = armed
        if armed:
            committed = arm.get('delay', self._delay)
            for d, btn in self._delay_buttons.items():
                btn.state = 'down' if d == committed else 'normal'

        # Service freshness — only surface a warning if stale; under
        # normal operation the live tick counter is noise. The
        # status_label is reserved for error/precondition messages.
        if self._status is not None:
            age = time.time() - self._status.get('ts', 0)
            if age > 5:
                self.status_label.text = (
                    f'⚠ service stale ({age:.1f}s old)'
                )
                self.status_label.color = COLOR_AMBER
            elif self.status_label.text.startswith('⚠ service stale'):
                # Came back to life — clear the warning
                self.status_label.text = ''

        # Device list
        self.device_grid.clear_widgets()
        devices = (self._status or {}).get('devices', []) or []
        if not devices:
            self.device_grid.add_widget(Label(
                text='(no USB devices)',
                font_size='13sp', size_hint_y=None, height=36,
                color=COLOR_DIM))
        else:
            for d in devices:
                is_ok = (d['vid'] == ONLYKEY_VID
                          and d['pid'] == ONLYKEY_PID)
                prefix = '[OnlyKey] ' if is_ok else ''
                self.device_grid.add_widget(Label(
                    text=(f"{prefix}{d['product']}\n"
                          f"VID:{d['vid']:04X}  PID:{d['pid']:04X}"),
                    font_size='13sp', size_hint_y=None, height=58,
                    color=COLOR_GREEN if is_ok else COLOR_WHITE))

    def _check_wipe_confirmation(self, _dt):
        """
        If the service requested a wipe-confirmation, pop a modal
        asking the user. Reads pending_wipe.json; writes the result
        back so the service can proceed or cancel.
        """
        if self._showing_wipe_modal:
            return
        try:
            with open(state._path('pending_wipe.json')) as f:
                req = json.load(f)
        except Exception:
            return
        if req.get('state') != 'requested':
            return

        self._showing_wipe_modal = True

        def confirm(popup):
            with open(state._path('pending_wipe.json'), 'w') as f:
                json.dump({'state': 'confirmed', 'ts': time.time()}, f)
            popup.dismiss()
            self._showing_wipe_modal = False

        def cancel(popup):
            with open(state._path('pending_wipe.json'), 'w') as f:
                json.dump({'state': 'cancelled', 'ts': time.time()}, f)
            popup.dismiss()
            self._showing_wipe_modal = False

        _modal(
            title='CONFIRM FACTORY RESET',
            body=('OnlyKey trigger fired with wipe enabled.\n\n'
                  'Tap WIPE to factory-reset this device now.\n'
                  'Tap Cancel to abort the wipe (lock-screen still '
                  'fires).'),
            buttons=[('Cancel', cancel), ('WIPE', confirm)],
        )


# ============================================================
# Settings screen
# ============================================================

class SettingsScreen(Screen):

    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=14, spacing=10)

        # Header
        header = BoxLayout(orientation='horizontal', size_hint=(1, 0.08))
        back = Button(text='< Back', font_size='14sp', size_hint=(0.25, 1))
        back.bind(on_release=lambda _b: self._go_back())
        header.add_widget(back)
        header.add_widget(Label(text='Settings', font_size='22sp', bold=True,
                                  size_hint=(0.75, 1)))
        root.add_widget(header)

        scroll = ScrollView(size_hint=(1, 0.92))
        body = GridLayout(cols=1, spacing=10, size_hint_y=None,
                           padding=(0, 4, 0, 16))
        body.bind(minimum_height=body.setter('height'))

        # --- Triggers section ---
        body.add_widget(self._section('TRIGGERS'))
        self.cb_lock = self._toggle_row(
            body, 'Lock screen on trigger',
            'Default ON. Calls DevicePolicyManager.lockNow().',
            'trig_lock',
        )
        self.cb_wipe = self._toggle_row(
            body, 'Factory wipe on trigger',
            'DESTRUCTIVE. Default OFF. Wipes the device.',
            'trig_wipe',
        )
        self.cb_confirm = self._toggle_row(
            body, 'Confirm before wipe',
            ('Show a confirm popup before wipe fires. Turn ON for '
             'casual testing; leave OFF for duress.'),
            'wipe_confirm',
        )

        # --- Tampering defenses section ---
        body.add_widget(self._section('TAMPERING DEFENSES'))
        self.cb_wod = self._toggle_row(
            body, 'Wipe on Admin disable attempt',
            ('Fires factory wipe if anyone tries to revoke openCIK\'s '
             'device-admin permission while armed.'),
            'wipe_on_admin_disable',
        )
        # M8 partial: wipe-on-force-stop is deferred (needs WorkManager
        # scaffolding). Showing as disabled toggle.
        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=72)
        row.add_widget(self._bind_text_size(Label(
            text=('Wipe on force-stop\n'
                  '[not yet implemented — coming in later release]'),
            font_size='12sp', halign='left', valign='middle',
            color=COLOR_DIM, size_hint=(0.8, 1))))
        cb = CheckBox(size_hint=(0.2, 1), disabled=True)
        row.add_widget(cb)
        body.add_widget(row)

        # --- PIN section ---
        body.add_widget(self._section('PIN GATE'))
        self.pin_status = self._bind_text_size(Label(
            text='', font_size='13sp', halign='left', valign='middle',
            size_hint_y=None, height=34))
        body.add_widget(self.pin_status)
        pin_row = BoxLayout(orientation='horizontal', spacing=8,
                              size_hint_y=None, height=48)
        self.pin_set_btn = Button(text='Set PIN', font_size='14sp')
        self.pin_set_btn.bind(on_release=lambda _b: self._set_pin_flow())
        pin_row.add_widget(self.pin_set_btn)
        self.pin_clear_btn = Button(text='Remove PIN', font_size='14sp')
        self.pin_clear_btn.bind(on_release=lambda _b: self._clear_pin_flow())
        pin_row.add_widget(self.pin_clear_btn)
        body.add_widget(pin_row)

        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def _bind_text_size(self, lbl):
        """
        Make Label.text_size track the widget's actual rendered width
        so wrap and clip happens against the real on-screen dimensions.
        Without this, text_size defaults to None (unbounded) or to
        whatever value we passed at __init__ time (which is 0/fallback
        before layout has run), producing overflowing or wildly
        narrow text.
        """
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        return lbl

    def _section(self, title):
        return self._bind_text_size(Label(
            text=title, font_size='15sp', bold=True,
            halign='left', valign='middle',
            size_hint_y=None, height=36,
            color=COLOR_NAV_BG,
        ))

    def _toggle_row(self, parent, title, desc, settings_key):
        row = BoxLayout(orientation='horizontal', size_hint_y=None, height=80)
        text = BoxLayout(orientation='vertical', size_hint=(0.8, 1),
                          padding=(0, 4, 8, 4))
        text.add_widget(self._bind_text_size(Label(
            text=title, font_size='15sp',
            halign='left', valign='bottom',
            size_hint=(1, 0.4),
        )))
        text.add_widget(self._bind_text_size(Label(
            text=desc, font_size='11sp', color=COLOR_DIM,
            halign='left', valign='top',
            size_hint=(1, 0.6),
        )))
        row.add_widget(text)
        cb = CheckBox(size_hint=(0.2, 1))
        # Stash the key on the widget so the callback knows which one
        cb._settings_key = settings_key
        cb.bind(active=self._on_toggle)
        row.add_widget(cb)
        parent.add_widget(row)
        return cb

    def on_pre_enter(self, *a):
        # Sync widget states from settings.json
        s = state.read_settings()
        self.cb_lock.active = s['trig_lock']
        self.cb_wipe.active = s['trig_wipe']
        self.cb_confirm.active = s['wipe_confirm']
        self.cb_wod.active = s['wipe_on_admin_disable']
        self._refresh_pin_status()

    def _on_toggle(self, cb, value):
        s = state.read_settings()
        s[cb._settings_key] = bool(value)
        state.write_settings(s)

    def _go_back(self):
        self.manager.transition.direction = 'right'
        self.manager.current = 'main'

    # --- PIN flows ---

    def _refresh_pin_status(self):
        if state.pin_is_set():
            self.pin_status.text = 'PIN is set. Disarming requires entering it.'
            self.pin_status.color = COLOR_GREEN
            self.pin_clear_btn.disabled = False
        else:
            self.pin_status.text = 'No PIN set. Anyone can disarm.'
            self.pin_status.color = COLOR_AMBER
            self.pin_clear_btn.disabled = True

    def _set_pin_flow(self):
        # Two-step: enter PIN, then confirm PIN
        new_pin = {'value': None}

        def on_first(popup, pin):
            if len(pin) < 4:
                popup.set_error('PIN must be at least 4 digits')
                return
            new_pin['value'] = pin
            popup.dismiss()
            PinPopup('Confirm PIN', 'Re-enter your new PIN to confirm',
                      on_confirm).open()

        def on_confirm(popup, pin):
            if pin != new_pin['value']:
                popup.set_error('PINs do not match')
                return
            state.set_pin(pin)
            popup.dismiss()
            self._refresh_pin_status()

        PinPopup('Set PIN',
                  'Enter a numeric PIN (min 4 digits). This will be '
                  'required to disarm openCIK.',
                  on_first).open()

    def _clear_pin_flow(self):
        # Require current PIN to clear it
        def on_ok(popup, pin):
            if not state.verify_pin(pin):
                popup.set_error('Wrong PIN')
                return
            state.set_pin('')
            popup.dismiss()
            self._refresh_pin_status()

        PinPopup('Remove PIN', 'Enter your current PIN to remove it',
                  on_ok).open()


# ============================================================
# App
# ============================================================

class OpenCikApp(App):
    title = 'openCIK'

    def build(self):
        request_notification_permission()
        try:
            self.service = start_monitor_service()
        except Exception as e:
            print(f'[opencik] service start failed: {e!r}')

        sm = ScreenManager(transition=NoTransition())
        sm.add_widget(MainScreen(name='main'))
        sm.add_widget(SettingsScreen(name='settings'))
        return sm


if __name__ == '__main__':
    OpenCikApp().run()
