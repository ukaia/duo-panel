"""Duo Panel: system stats, toggles and brightness link for the Retroid Pocket Duo's bottom screen.

Run:  python3 -m duo_panel.app [--windowed] [--demo] [--screenshot out.png]
The brightness work is done by the root service (syncd.py); this app only reads stats, flips supported
toggles and talks to that service over its socket.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque

from PySide6.QtCore import QLockFile, QStandardPaths, Property, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from . import ctl, themes
from .controls import Controls, syncthing_connected_count
from .sysinfo import Sampler

HISTORY = 90
UI_CONFIG = os.path.expanduser("~/.config/duo-panel/ui.json")


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        self.fn()


class Backend(QObject):
    dataChanged = Signal()
    toastChanged = Signal()
    themeChanged = Signal()
    _slowReady = Signal(dict)
    _actionDone = Signal(str, bool, str)

    def __init__(self, demo=None, sampler=None, controls=None, theme=None, ui_config=UI_CONFIG):
        super().__init__()
        self._demo = demo
        self._ui_config = ui_config
        self._persist_theme = theme is None
        self._theme_id = theme or self._load_theme()
        self._sampler = sampler or Sampler()
        self._controls = controls or Controls(syncthing_api=syncthing_connected_count)
        self._hist = {k: deque(maxlen=HISTORY) for k in ("cpu", "gpu", "temp", "watts")}
        self._slow = {}
        self._pending = {}       # toggle name -> (wanted state, expires)
        self._data = {}
        self._toast = ""
        self._toast_until = 0.0
        self._slow_busy = False
        if demo:
            for key, values in demo.get("history", {}).items():
                self._hist[key].extend(values)
        self._slowReady.connect(self._apply_slow, Qt.QueuedConnection)
        self._actionDone.connect(self._finish_action, Qt.QueuedConnection)
        self._fast = QTimer(self)
        self._fast.setInterval(1000)
        self._fast.timeout.connect(self.refresh)
        self._slowt = QTimer(self)
        self._slowt.setInterval(4000)
        self._slowt.timeout.connect(self.refresh_slow)

    def start(self):
        self.refresh_slow()
        self.refresh()
        self._fast.start()
        self._slowt.start()

    # ---- theme ---------------------------------------------------------
    def _load_theme(self):
        try:
            with open(self._ui_config) as f:
                wanted = json.load(f).get("theme")
            if wanted in themes.IDS:
                return wanted
        except (OSError, ValueError, AttributeError):
            pass
        return themes.DEFAULT_THEME

    @Property("QVariantList", constant=True)
    def themes(self):
        return themes.THEMES

    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        return themes.by_id(self._theme_id)

    @Slot(str)
    def setTheme(self, theme_id):
        if theme_id not in themes.IDS or theme_id == self._theme_id:
            return
        self._theme_id = theme_id
        self.themeChanged.emit()
        if self._persist_theme:
            try:
                os.makedirs(os.path.dirname(self._ui_config), exist_ok=True)
                tmp = self._ui_config + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"theme": theme_id}, f)
                os.replace(tmp, self._ui_config)
            except OSError:
                self._say("Could not save the theme choice", 4)

    # ---- QML properties ------------------------------------------------
    @Property("QVariantMap", notify=dataChanged)
    def data(self):
        return self._data

    @Property(str, notify=toastChanged)
    def toast(self):
        return self._toast if time.monotonic() < self._toast_until else ""

    def _say(self, text, seconds=4.0):
        self._toast = text
        self._toast_until = time.monotonic() + seconds
        self.toastChanged.emit()
        QTimer.singleShot(int(seconds * 1000) + 50, self.toastChanged.emit)

    # ---- refresh -------------------------------------------------------
    @Slot()
    def refresh(self):
        s = self._demo_sample() if self._demo else self._sampler.sample()
        h = self._hist
        h["cpu"].append(s["cpu"]["total"])
        h["gpu"].append(s["gpu"]["pct"] if s.get("gpu") else 0)
        h["temp"].append(s["temps"]["cpu"] or 0)
        h["watts"].append(abs(s["battery"]["watts"]) if s.get("battery") else 0)
        s["history"] = {k: list(v) for k, v in h.items()}
        s["bright"] = self._bright_state()
        s["slow"] = self._merged_slow()
        s["now"] = time.strftime("%-I:%M %p")
        self._data = s
        self.dataChanged.emit()

    def _bright_state(self):
        if self._demo:
            return self._demo["bright"]
        st = ctl.read_state()
        if not st or time.time() - st.get("ts", 0) > 10:
            return {"available": False}
        return {"available": True, "locked": st["locked"], "trim": st["trim"], "top": st["top"]["pct"],
                "bottom": st["bottom"]["pct"], "source": st["last_source"], "error": st.get("error")}

    def _merged_slow(self):
        slow = json.loads(json.dumps(self._slow))
        now = time.monotonic()
        for name, (wanted, expires) in list(self._pending.items()):
            if now > expires:
                del self._pending[name]
                continue
            if name in slow:
                key = "enabled" if name == "wifi" else "powered" if name == "bluetooth" else "active"
                slow[name][key] = wanted
                slow[name]["pending"] = True
        return slow

    @Slot()
    def refresh_slow(self):
        if self._demo:
            self._slow = self._demo["slow"]
            return
        if self._slow_busy:
            return
        self._slow_busy = True

        def work():
            try:
                result = self._controls.read_states()
            except Exception as error:   # never let a failed probe kill the UI
                result = {"error": str(error)}
            try:
                self._slowReady.emit(result)
            except RuntimeError:     # the window closed while the probe was running
                pass
        QThreadPool.globalInstance().start(_Job(work))

    @Slot(dict)
    def _apply_slow(self, result):
        self._slow_busy = False
        if "error" not in result:
            self._slow = result
        self.refresh()

    # ---- actions from QML ---------------------------------------------
    @Slot(str, bool)
    def setToggle(self, name, on):
        if self._demo:
            self._slow[name]["enabled" if name == "wifi" else "powered" if name == "bluetooth" else "active"] = on
            self.refresh()
            return
        self._pending[name] = (on, time.monotonic() + 8)
        self.refresh()

        def work():
            ok, message = self._controls.toggle(name, on)
            try:
                self._actionDone.emit(name, ok, message)
            except RuntimeError:
                pass
        QThreadPool.globalInstance().start(_Job(work))

    @Slot(str)
    def setProfile(self, name):
        if self._demo:
            self._slow["profile"]["name"] = name
            self.refresh()
            return

        def work():
            ok, message = self._controls.set_profile(name)
            try:
                self._actionDone.emit("profile", ok, message)
            except RuntimeError:
                pass
        QThreadPool.globalInstance().start(_Job(work))

    @Slot(str, bool, str)
    def _finish_action(self, name, ok, message):
        self._pending.pop(name, None)
        if not ok:
            self._say(f"Could not change {name}: {message or 'failed'}", 6)
        self._slow_busy = False
        self.refresh_slow()

    def _daemon(self, payload):
        if self._demo:
            return
        try:
            reply = ctl.request(payload)
        except OSError:
            self._say("Brightness service is not running", 5)
            return
        if not reply.get("ok"):
            self._say(reply.get("error", "rejected"), 5)
        self.refresh()

    @Slot(str, float)
    def setBrightness(self, screen, pct):
        self._daemon({"cmd": "set_brightness", "screen": screen, "pct": max(0.0, min(100.0, pct))})

    @Slot(bool)
    def setLocked(self, locked):
        self._daemon({"cmd": "set_lock", "locked": locked})

    @Slot(int)
    def setTrim(self, trim):
        self._daemon({"cmd": "set_trim", "trim": int(trim)})

    # ---- demo ----------------------------------------------------------
    def _demo_sample(self):
        import copy
        return copy.deepcopy(self._demo["sample"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--windowed", action="store_true", help="1280x960 window instead of fullscreen")
    ap.add_argument("--demo", metavar="JSON", help="render a fixture instead of reading the device")
    ap.add_argument("--screenshot", metavar="PNG", help="save the window to a PNG after a few seconds, then quit")
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--report-size", action="store_true", help="print the window size after 3 s (for checking placement)")
    ap.add_argument("--theme", choices=themes.IDS, help="use this theme without saving it")
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Duo Panel")
    app.setDesktopFileName("duo-panel")
    demo = None
    if args.demo:
        with open(args.demo) as f:
            demo = json.load(f)
    lock = None
    if not args.screenshot and not demo:
        runtime = QStandardPaths.writableLocation(QStandardPaths.RuntimeLocation) or "/tmp"
        lock = QLockFile(os.path.join(runtime, "duo-panel-ui.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            print("Duo Panel is already open", file=sys.stderr)
            return 0
    backend = Backend(demo=demo, theme=args.theme)
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [print("QML:", w.toString(), file=sys.stderr, flush=True) for w in warnings])
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("startFullscreen", not args.windowed and not args.screenshot)
    backend.start()          # first sample before the page loads, so the bindings never see empty data
    engine.load(QUrl.fromLocalFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", "Main.qml")))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    if args.report_size:
        QTimer.singleShot(3000, lambda: print("window", window.width(), "x", window.height(), "screen", window.screen().name(), window.screen().size().width(), "x", window.screen().size().height(), flush=True))
    if args.screenshot:

        def grab():
            try:
                image = QQuickWindow.grabWindow(window)
                ok = image.save(args.screenshot)
                print("saved" if ok else "save failed", args.screenshot, image.width(), "x", image.height(), flush=True)
            finally:
                app.quit()
        QTimer.singleShot(int(args.delay * 1000), grab)
    code = app.exec()
    QThreadPool.globalInstance().waitForDone(5000)
    return code


if __name__ == "__main__":
    sys.exit(main())
