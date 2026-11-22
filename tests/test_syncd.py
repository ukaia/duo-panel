import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from duo_panel import ctl  # noqa: E402
from duo_panel.brightness import BOTTOM, TOP  # noqa: E402
from duo_panel.syncd import Daemon, Paths, armada_percent  # noqa: E402

TOP_NAME, BOTTOM_NAME = "ae94000.dsi.0", "ae96000.dsi.0"
MAX = {TOP: 4095, BOTTOM: 3445}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Rig:
    """A fake /sys + /etc/armada tree, a daemon on it, and a copy of armada-control's 2-second restore check."""

    def __init__(self, top=2368, bottom=2067, saved=60, locked=True, trim=0, enforce=True):
        self.dir = tempfile.mkdtemp(prefix="duo-")
        for name, mx, raw in ((TOP_NAME, MAX[TOP], top), (BOTTOM_NAME, MAX[BOTTOM], bottom)):
            d = os.path.join(self.dir, "sys", name)
            os.makedirs(d)
            self._w(os.path.join(d, "max_brightness"), mx)
            self._w(os.path.join(d, "brightness"), raw)
        os.makedirs(os.path.join(self.dir, "etc"))
        self.saved_path = os.path.join(self.dir, "etc", "bottom-screen-brightness")
        if saved is not None:
            self._w(self.saved_path, saved)
        self.config = os.path.join(self.dir, "state", "config.json")
        os.makedirs(os.path.dirname(self.config))
        with open(self.config, "w") as f:
            json.dump({"locked": locked, "trim": trim}, f)
        self.paths = Paths(sys_backlight=os.path.join(self.dir, "sys"), saved_bottom=self.saved_path,
                           config=self.config, run_dir=os.path.join(self.dir, "run"), device_env=os.path.join(self.dir, "nope"))
        self.clock = Clock()
        self.daemon = Daemon(self.paths, clock=self.clock, wall=lambda: 1234.5)
        self.enforce = enforce
        self.reverts = 0
        self.ticks = 0
        real_write = self.daemon.write_panel

        def write_then_armada_checks(screen, raw):
            real_write(screen, raw)
            if self.enforce:
                self.armada_restore()      # worst case: armada-control's check lands right after our write
        self.daemon.write_panel = write_then_armada_checks

    @staticmethod
    def _w(path, value):
        with open(path, "w") as f:
            f.write(f"{value}\n")

    def raw(self, screen):
        name = TOP_NAME if screen == TOP else BOTTOM_NAME
        with open(os.path.join(self.dir, "sys", name, "brightness")) as f:
            return int(f.read())

    def set_raw(self, screen, value):
        name = TOP_NAME if screen == TOP else BOTTOM_NAME
        self._w(os.path.join(self.dir, "sys", name, "brightness"), value)

    def saved(self):
        with open(self.saved_path) as f:
            return int(f.read())

    def armada_restore(self):
        """armada-control.restore_bottom_screen_brightness, copied from the device."""
        try:
            saved = self.saved()
        except (OSError, ValueError):
            return
        if armada_percent(self.raw(BOTTOM), MAX[BOTTOM]) == saved:
            return
        self.reverts += 1
        self.set_raw(BOTTOM, round(saved * MAX[BOTTOM] / 100))

    def run(self, seconds):
        for _ in range(int(seconds / 0.1)):
            self.clock.t += 0.1
            self.ticks += 1
            self.daemon.tick()
            if self.enforce and self.ticks % 20 == 0:   # armada-control wakes every 2 s
                self.armada_restore()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class DaemonTests(unittest.TestCase):
    def rig(self, **kw):
        r = Rig(**kw)
        self.addCleanup(r.close)
        return r

    def test_start_aligns_bottom_and_armada_never_reverts_it(self):
        r = self.rig()
        r.run(10)
        self.assertAlmostEqual(r.raw(BOTTOM) / 3445, 2368 / 4095, delta=0.004)
        self.assertEqual(r.saved(), armada_percent(r.raw(BOTTOM), 3445))
        self.assertEqual(r.reverts, 0)

    def test_top_slider_drag_with_armada_checking_every_two_seconds(self):
        r = self.rig()
        r.run(3)
        for value in range(2368, 400, -40):
            r.set_raw(TOP, value)
            r.run(0.3)
        r.run(6)
        self.assertEqual(r.reverts, 0)
        self.assertAlmostEqual(r.raw(BOTTOM) / 3445, r.raw(TOP) / 4095, delta=0.004)
        self.assertEqual(r.saved(), armada_percent(r.raw(BOTTOM), 3445))

    def test_bottom_changed_by_another_slider_is_kept_and_top_follows(self):
        r = self.rig()
        r.run(3)
        r.set_raw(BOTTOM, 2800)               # e.g. Plasma Mobile's brightness slider
        r.run(5)
        self.assertEqual(r.reverts, 0, "armada-control undid the change")
        self.assertAlmostEqual(r.raw(BOTTOM) / 3445, 2800 / 3445, delta=0.004)
        self.assertAlmostEqual(r.raw(TOP) / 4095, 2800 / 3445, delta=0.004)

    def test_unlocked_bottom_change_sticks_and_top_is_untouched(self):
        r = self.rig(locked=False)
        r.run(3)
        top = r.raw(TOP)
        r.set_raw(BOTTOM, 1000)
        r.run(6)
        self.assertEqual(r.reverts, 0)
        self.assertEqual(r.raw(BOTTOM), 1000)
        self.assertEqual(r.saved(), armada_percent(1000, 3445))
        self.assertEqual(r.raw(TOP), top)

    def test_unlocked_start_leaves_the_saved_value_alone(self):
        r = self.rig(locked=False, enforce=False)
        r.run(3)
        self.assertEqual(r.saved(), 60)

    def test_missing_saved_file_is_created_with_the_current_value(self):
        r = self.rig(saved=None)
        r.run(3)
        self.assertEqual(r.saved(), armada_percent(r.raw(BOTTOM), 3445))

    def test_mutation_without_file_first_ordering_armada_would_revert(self):
        r = self.rig()

        def panel_only(screen, raw):          # the naive version: write the panel, forget the saved file
            with open(r.daemon._file(screen, "brightness"), "w") as f:
                f.write(f"{raw}\n")
            r.armada_restore()
        r.daemon.write_panel = panel_only
        r.run(1)
        r.set_raw(TOP, 900)
        r.run(6)
        self.assertGreater(r.reverts, 0, "this is the failure the real design avoids")

    def test_saved_file_is_only_rewritten_when_the_percent_changes(self):
        import duo_panel.syncd as syncd
        r = self.rig()
        r.run(3)
        calls = []
        original = syncd.atomic_write
        syncd.atomic_write = lambda path, text, mode=0o644: (calls.append(path), original(path, text, mode))[1]
        try:
            r.run(30)                      # nothing changes
            self.assertEqual([c for c in calls if c == r.saved_path], [])
            r.set_raw(TOP, 3000)
            r.run(3)
            self.assertLessEqual(len([c for c in calls if c == r.saved_path]), 1)
        finally:
            syncd.atomic_write = original

    def test_socket_commands_and_validation(self):
        r = self.rig()
        d = r.daemon
        self.assertTrue(d.handle({"cmd": "set_lock", "locked": False})["ok"])
        self.assertFalse(d.engine.locked)
        with open(r.config) as f:
            self.assertEqual(json.load(f)["locked"], False)
        self.assertTrue(d.handle({"cmd": "set_lock", "locked": True})["ok"])
        self.assertTrue(d.handle({"cmd": "set_trim", "trim": -5})["ok"])
        self.assertEqual(d.engine.trim, -5)
        for bad in ({"cmd": "set_trim", "trim": 99}, {"cmd": "set_trim", "trim": 1.5}, {"cmd": "set_trim", "trim": True},
                    {"cmd": "set_lock", "locked": "yes"}, {"cmd": "set_brightness", "screen": "left", "pct": 5},
                    {"cmd": "set_brightness", "screen": "top", "pct": 101}, {"cmd": "set_brightness", "screen": "top", "pct": "x"},
                    {"cmd": "format_disk"}, {}):
            self.assertFalse(d.handle(bad)["ok"], bad)
        before = r.raw(TOP)
        self.assertEqual(before, 2368, "rejected commands must not touch the panels")

    def test_set_brightness_command_moves_that_panel_and_the_lock_follows(self):
        r = self.rig()
        r.run(3)
        self.assertTrue(r.daemon.handle({"cmd": "set_brightness", "screen": "bottom", "pct": 25})["ok"])
        r.run(5)
        self.assertEqual(r.reverts, 0)
        self.assertAlmostEqual(r.raw(BOTTOM) / 3445, 0.25, delta=0.004)
        self.assertAlmostEqual(r.raw(TOP) / 4095, 0.25, delta=0.004)

    def test_real_unix_socket_round_trip(self):
        r = self.rig()
        sock = r.daemon.open_socket()
        sock.setblocking(True)

        def serve_two():
            for _ in range(2):
                conn, _ = sock.accept()
                r.daemon.serve_client(conn)
        t = threading.Thread(target=serve_two, daemon=True)
        t.start()
        got = ctl.request({"cmd": "get"}, path=r.paths.socket)
        self.assertTrue(got["ok"])
        self.assertEqual(got["state"]["top"]["max"], 4095)
        bad = ctl.request({"cmd": "set_trim", "trim": "lots"}, path=r.paths.socket)
        self.assertFalse(bad["ok"])
        t.join(3)
        sock.close()

    def test_state_file_is_published_and_readable(self):
        r = self.rig()
        r.run(1)
        state = ctl.read_state(r.paths.state)
        self.assertEqual(state["locked"], True)
        self.assertAlmostEqual(state["top"]["pct"], 57.8, delta=0.1)
        self.assertIsNone(state["error"])
        self.assertIsNone(ctl.read_state(os.path.join(r.dir, "missing.json")))


if __name__ == "__main__":
    unittest.main()
