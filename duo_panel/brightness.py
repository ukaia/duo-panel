"""Brightness sync engine for the Retroid Pocket Duo's two panels. Pure logic, no I/O.

The daemon (syncd.py) feeds it the raw backlight readings of both panels every poll and performs the
writes it returns. Whichever panel changed (Steam's slider moves the top one, the Armada Control or
Plasma slider and this app's sliders move the bottom one) becomes the source and the other panel is set
to the same *fraction of its own range* plus an optional trim.

Rules the tests pin down:
- A panel is only treated as "changed" when its raw value differs from the last value this engine saw,
  so a write the engine made itself (and any rounding the driver applied to it) never counts as a user
  change. That is what stops two panels with different ranges from chasing each other.
- At most one write per step.
- Unlocked: nothing is ever written; changes are just tracked.
- Locking (or changing the trim) re-aligns the bottom panel to the top one.
- A reading of 0 must be seen twice in a row before it counts (guards against a transient glitch while
  a display mode switches).
"""
from __future__ import annotations

from dataclasses import dataclass

TOP = "top"
BOTTOM = "bottom"
OTHER = {TOP: BOTTOM, BOTTOM: TOP}
SCREENS = (TOP, BOTTOM)

MAX_TRIM = 30  # percentage points


@dataclass(frozen=True)
class Write:
    screen: str
    raw: int


def clamp(value, low, high):
    return max(low, min(high, value))


class SyncEngine:
    SETTLE_SECONDS = 0.6  # how long a write may take to show up in the readback

    def __init__(self, maxes, locked=True, trim=0):
        if set(maxes) != set(SCREENS) or any(int(m) <= 0 for m in maxes.values()):
            raise ValueError("maxes needs a positive max for top and bottom")
        self.max = {k: int(v) for k, v in maxes.items()}
        self.locked = bool(locked)
        self.trim = int(clamp(trim, -MAX_TRIM, MAX_TRIM))
        self.last = None            # screen -> raw value this engine last accepted
        self.pending = {}           # screen -> (target raw, deadline) for writes in flight
        self.last_source = TOP
        self._align = self.locked   # mirror top -> bottom on the next step
        self._zero_seen = {}        # screen -> True when a lone 0 reading is waiting for confirmation
        self.bottom_changed = False  # set by step() when the bottom panel's accepted value changed

    # ---- configuration -------------------------------------------------
    def set_locked(self, locked):
        locked = bool(locked)
        if locked and not self.locked:
            self._align = True
        self.locked = locked

    def set_trim(self, trim):
        trim = int(clamp(trim, -MAX_TRIM, MAX_TRIM))
        if trim != self.trim:
            self.trim = trim
            if self.locked:
                self._align = True

    # ---- helpers -------------------------------------------------------
    def pct(self, screen, raw=None):
        raw = self.last[screen] if raw is None else raw
        return raw / self.max[screen]

    def _tolerance(self, screen):
        # A readback this close to the target counts as "the write landed" (driver rounding).
        return max(1, round(0.004 * self.max[screen]))

    def target_for(self, source, source_raw):
        """Raw value the other panel should have for `source` sitting at `source_raw`."""
        dest = OTHER[source]
        pct = source_raw / self.max[source]
        shift = self.trim / 100.0
        pct += shift if dest == BOTTOM else -shift
        return int(round(clamp(pct, 0.0, 1.0) * self.max[dest]))

    def _mirror(self, source, now):
        dest = OTHER[source]
        target = self.target_for(source, self.last[source])
        if abs(target - self.last[dest]) <= self._tolerance(dest):
            return []
        self.pending[dest] = (target, now + self.SETTLE_SECONDS)
        return [Write(dest, target)]

    # ---- main entry ----------------------------------------------------
    def step(self, now, raw):
        """Feed the current raw readings; returns the list of writes to perform (0 or 1)."""
        self.bottom_changed = False
        if self.last is None:
            self.last = {k: int(raw[k]) for k in SCREENS}
            if self.locked:
                self._align = False
                return self._mirror(TOP, now)
            return []

        changed = []
        for screen in SCREENS:
            value = int(raw[screen])
            pending = self.pending.get(screen)
            if pending is not None:
                target, deadline = pending
                old = self.last[screen]
                tol = self._tolerance(screen)
                if abs(value - target) <= tol or (min(old, target) - tol <= value <= max(old, target) + tol and value != old):
                    # our write landed, possibly rounded or partly applied by the driver: never a user change
                    del self.pending[screen]
                    self._accept(screen, value)
                    continue
                if value == self.last[screen]:
                    if now >= deadline:
                        del self.pending[screen]   # the write never showed up; stop waiting, do not retry
                    continue
                del self.pending[screen]          # something else moved it meanwhile: a real change
            if value != self.last[screen]:
                if value == 0 and not self._zero_seen.get(screen):
                    self._zero_seen[screen] = True
                    continue
                self._zero_seen[screen] = False
                changed.append((screen, value))
            else:
                self._zero_seen[screen] = False

        for screen, value in changed:
            self._accept(screen, value)

        if not self.locked:
            self._align = False
            return []
        if self._align:
            self._align = False
            return self._mirror(TOP, now)
        if not changed:
            return []
        sources = [s for s, _ in changed]
        source = self.last_source if self.last_source in sources else sources[0]
        self.last_source = source
        return self._mirror(source, now)

    def _accept(self, screen, value):
        if self.last[screen] != value and screen == BOTTOM:
            self.bottom_changed = True
        self.last[screen] = value
