import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from duo_panel.brightness import BOTTOM, TOP, SyncEngine, Write  # noqa: E402

MAXES = {TOP: 4095, BOTTOM: 3445}  # the Duo's real ranges


class Panels:
    """Two fake backlights that apply writes after an optional delay and can round like a driver."""

    def __init__(self, top, bottom, lag=0.0, round_to=1):
        self.raw = {TOP: top, BOTTOM: bottom}
        self.queue = []
        self.lag = lag
        self.round_to = round_to
        self.writes = []

    def apply(self, now, writes):
        for w in writes:
            self.writes.append(w)
            self.queue.append((now + self.lag, w.screen, (w.raw // self.round_to) * self.round_to))

    def tick(self, now):
        due = [q for q in self.queue if q[0] <= now]
        self.queue = [q for q in self.queue if q[0] > now]
        for _, screen, raw in due:
            self.raw[screen] = raw
        return dict(self.raw)


def run(engine, panels, t0, steps, dt=0.1):
    now = t0
    for _ in range(steps):
        now += dt
        panels.apply(now, engine.step(now, panels.tick(now)))
    return now


def pct(engine, raw, screen):
    return raw[screen] / engine.max[screen]


class SyncEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = SyncEngine(MAXES, locked=True)
        self.panels = Panels(2368, 2067)

    def test_first_sample_aligns_bottom_to_top_by_fraction(self):
        writes = self.engine.step(0.0, self.panels.raw)
        self.assertEqual(writes, [Write(BOTTOM, round(2368 / 4095 * 3445))])

    def test_settles_and_stays_quiet(self):
        run(self.engine, self.panels, 0, 40)
        self.assertEqual(len(self.panels.writes), 1)
        self.assertAlmostEqual(pct(self.engine, self.panels.raw, TOP), pct(self.engine, self.panels.raw, BOTTOM), delta=0.004)

    def test_top_change_moves_bottom_and_bottom_change_moves_top(self):
        now = run(self.engine, self.panels, 0, 10)
        self.panels.raw[TOP] = 1000
        now = run(self.engine, self.panels, now, 10)
        self.assertAlmostEqual(self.panels.raw[BOTTOM] / 3445, 1000 / 4095, delta=0.004)
        self.panels.raw[BOTTOM] = 3000
        run(self.engine, self.panels, now, 10)
        self.assertAlmostEqual(self.panels.raw[TOP] / 4095, 3000 / 3445, delta=0.004)

    def test_no_ping_pong_with_driver_rounding_and_lag(self):
        panels = Panels(2368, 2067, lag=0.25, round_to=8)
        engine = SyncEngine(MAXES, locked=True)
        now = run(engine, panels, 0, 30)
        before = len(panels.writes)
        run(engine, panels, now, 200)
        self.assertEqual(len(panels.writes), before, "writes kept happening with nothing changing")
        # change top; exactly one follow-up write, and it never writes the top panel
        panels.raw[TOP] = 3300
        now = run(engine, panels, now, 40)
        self.assertEqual([w.screen for w in panels.writes[before:]], [BOTTOM])

    def test_slider_drag_follows_every_step_and_never_touches_the_source(self):
        now = run(self.engine, self.panels, 0, 10)
        base = len(self.panels.writes)
        for value in range(2368, 600, -90):
            self.panels.raw[TOP] = value
            now = run(self.engine, self.panels, now, 2)
        now = run(self.engine, self.panels, now, 10)
        new = self.panels.writes[base:]
        self.assertTrue(new and all(w.screen == BOTTOM for w in new))
        self.assertAlmostEqual(self.panels.raw[BOTTOM] / 3445, self.panels.raw[TOP] / 4095, delta=0.004)

    def test_slow_write_is_not_repeated_while_in_flight(self):
        panels = Panels(2368, 2067, lag=0.45)
        engine = SyncEngine(MAXES, locked=True)
        run(engine, panels, 0, 12)
        self.assertEqual(len(panels.writes), 1)

    def test_write_that_never_lands_is_dropped_not_retried_forever(self):
        panels = Panels(2368, 2067)
        engine = SyncEngine(MAXES, locked=True)
        issued = 0
        now = 0
        for _ in range(60):
            now += 0.1
            issued += len(engine.step(now, panels.raw))   # the write is never applied
        self.assertEqual(issued, 1)

    def test_a_one_step_change_inside_the_tolerance_is_not_mirrored(self):
        now = run(self.engine, self.panels, 0, 10)
        base = len(self.panels.writes)
        self.panels.raw[TOP] += 1
        run(self.engine, self.panels, now, 10)
        self.assertEqual(len(self.panels.writes), base)

    def test_coarse_driver_rounding_cannot_cause_a_ping_pong(self):
        # A panel that only moves in big steps (40 raw units, about 1.2%): the readback lands well away from
        # the requested value. That must never look like the user moving the bottom panel.
        panels = Panels(2368, 2067, lag=0.2, round_to=40)
        engine = SyncEngine(MAXES, locked=True)
        now = run(engine, panels, 0, 20)
        for top in range(1000, 4000, 97):
            before = len(panels.writes)
            panels.raw[TOP] = top
            now = run(engine, panels, now, 12)
            fresh = panels.writes[before:]
            self.assertTrue(fresh, f"bottom did not follow top={top}")
            self.assertEqual({w.screen for w in fresh}, {BOTTOM}, f"top was written after the user set top={top}")
            settled = len(panels.writes)
            now = run(engine, panels, now, 30)
            self.assertEqual(len(panels.writes), settled, f"kept writing after settling at top={top}")

    def test_unlocked_never_writes_but_tracks(self):
        engine = SyncEngine(MAXES, locked=False)
        panels = Panels(2368, 2067)
        now = run(engine, panels, 0, 10)
        panels.raw[TOP] = 500
        now = run(engine, panels, now, 10)
        self.assertEqual(panels.writes, [])
        self.assertEqual(engine.last[TOP], 500)

    def test_locking_realigns_bottom_to_top(self):
        engine = SyncEngine(MAXES, locked=False)
        panels = Panels(2368, 900)
        now = run(engine, panels, 0, 5)
        engine.set_locked(True)
        run(engine, panels, now, 10)
        self.assertAlmostEqual(panels.raw[BOTTOM] / 3445, panels.raw[TOP] / 4095, delta=0.004)

    def test_trim_offsets_the_bottom_panel_in_both_directions(self):
        engine = SyncEngine(MAXES, locked=True, trim=10)
        panels = Panels(2048, 1000)
        now = run(engine, panels, 0, 10)
        self.assertAlmostEqual(panels.raw[BOTTOM] / 3445, panels.raw[TOP] / 4095 + 0.10, delta=0.004)
        panels.raw[BOTTOM] = int(0.80 * 3445)
        run(engine, panels, now, 10)
        self.assertAlmostEqual(panels.raw[TOP] / 4095, 0.70, delta=0.004)

    def test_changing_trim_while_locked_moves_the_bottom_panel(self):
        engine = SyncEngine(MAXES, locked=True, trim=0)
        panels = Panels(2048, 1700)
        now = run(engine, panels, 0, 10)
        engine.set_trim(-20)
        run(engine, panels, now, 10)
        self.assertAlmostEqual(panels.raw[BOTTOM] / 3445, panels.raw[TOP] / 4095 - 0.20, delta=0.004)

    def test_targets_are_clamped_to_the_panel_range(self):
        engine = SyncEngine(MAXES, locked=True, trim=30)
        panels = Panels(4095, 100)
        run(engine, panels, 0, 10)
        self.assertEqual(panels.raw[BOTTOM], 3445)
        engine = SyncEngine(MAXES, locked=True, trim=-30)
        panels = Panels(500, 3000)
        run(engine, panels, 0, 10)
        self.assertEqual(panels.raw[BOTTOM], 0)

    def test_both_panels_changed_in_one_poll_prefers_the_last_source(self):
        now = run(self.engine, self.panels, 0, 10)
        self.engine.last_source = BOTTOM
        self.panels.raw[TOP] = 3000
        self.panels.raw[BOTTOM] = 1000
        self.panels.apply(now + 0.1, self.engine.step(now + 0.1, self.panels.raw))
        self.assertEqual([w.screen for w in self.panels.writes[-1:]], [TOP])

    def test_a_lone_zero_reading_is_ignored_but_a_held_zero_is_followed(self):
        now = run(self.engine, self.panels, 0, 10)
        base = len(self.panels.writes)
        self.panels.raw[TOP] = 0
        self.panels.apply(now + 0.1, self.engine.step(now + 0.1, self.panels.raw))   # first 0: ignored
        self.assertEqual(len(self.panels.writes), base)
        self.panels.raw[TOP] = 2368                                                    # glitch over
        now = run(self.engine, self.panels, now + 0.1, 5)
        self.assertEqual(len(self.panels.writes), base)
        self.panels.raw[TOP] = 0
        run(self.engine, self.panels, now, 6)                                          # held 0: followed
        self.assertEqual(self.panels.raw[BOTTOM], 0)

    def test_bottom_changed_flag_reports_accepted_bottom_changes(self):
        now = run(self.engine, self.panels, 0, 10)
        self.panels.raw[BOTTOM] = 777
        self.engine.step(now + 0.1, self.panels.raw)
        self.assertTrue(self.engine.bottom_changed)
        self.engine.step(now + 0.2, self.panels.raw)
        self.assertFalse(self.engine.bottom_changed)


if __name__ == "__main__":
    unittest.main()
