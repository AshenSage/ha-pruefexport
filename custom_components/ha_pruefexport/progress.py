"""Bounded progress events; percentages describe work stages, not remaining time."""
import math
import time


class ProgressReporter:
    def __init__(self, callback=None):
        self.callback = callback
        self.last = None
        self.last_sent = 0.0
        self.percent = 0

    def __call__(self, phase, percent, processed=None, total=None, unit=None):
        if not isinstance(percent, (int, float)) or not math.isfinite(percent):
            return
        self.percent = max(self.percent, min(99, max(0, int(percent))))
        event = {"phase": phase, "progress_pct": self.percent,
                 "processed": processed, "total": total, "unit": unit}
        now = time.monotonic()
        changed = self.last is None or phase != self.last["phase"] or self.percent != self.last["progress_pct"]
        if self.callback is not None and (changed or now - self.last_sent >= 0.5):
            self.callback(event)
            self.last, self.last_sent = event, now
