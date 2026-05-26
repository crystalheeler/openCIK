"""
openCIK Android - Hello World

Minimal Kivy app used to prove the Buildozer + python-for-android build
pipeline works on this host. Replace with real openCIK logic once we've
confirmed the APK installs and launches on a target device.
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button


class HelloRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 40
        self.spacing = 20

        self.add_widget(Label(
            text='openCIK',
            font_size='42sp',
            bold=True,
            size_hint=(1, 0.3),
        ))
        self.add_widget(Label(
            text='Android build pipeline OK',
            font_size='18sp',
            size_hint=(1, 0.2),
        ))

        self._counter = 0
        self._counter_label = Label(
            text='Taps: 0',
            font_size='22sp',
            size_hint=(1, 0.2),
        )
        self.add_widget(self._counter_label)

        tap_btn = Button(
            text='Tap me',
            size_hint=(1, 0.3),
            font_size='24sp',
        )
        tap_btn.bind(on_release=self._on_tap)
        self.add_widget(tap_btn)

    def _on_tap(self, _btn):
        self._counter += 1
        self._counter_label.text = f'Taps: {self._counter}'


class HelloApp(App):
    title = 'openCIK'

    def build(self):
        return HelloRoot()


if __name__ == '__main__':
    HelloApp().run()
