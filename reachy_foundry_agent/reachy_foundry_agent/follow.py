"""Keep the head pointed at the person in view: an app-side loop, not a tool the model has to call.

Runs on the robot with the local person detector (``vision_local.PersonDetector``); frames never leave it.
It does not identify anyone, it only keeps the biggest person near the middle of the image.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

DEADBAND = 0.08  # fraction of the image size around the centre where the head stays still
GAIN = 0.6  # move this share of the way to the person per step, so detection lag does not overshoot
MOVE_S = 0.35  # duration of one correction
INTERVAL_S = 0.1  # pause between steps (detection itself takes most of the loop time)


class PersonFollower:
    def __init__(
        self,
        mini: Any,
        detector: Any,
        lock: threading.Lock,
        should_track: Callable[[], bool],
        deadband: float = DEADBAND,
        gain: float = GAIN,
        move_s: float = MOVE_S,
    ) -> None:
        self._mini = mini
        self._detector = detector
        self._lock = lock  # the robot's motion lock: never move while a gesture or emotion owns the head
        self._should_track = should_track
        self._deadband = deadband
        self._gain = gain
        self._move_s = move_s
        self._thread: threading.Thread | None = None

    def start(self, stop_event: threading.Event) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, args=(stop_event,), name="person-follower", daemon=True)
        self._thread.start()
        log.info("person follower started")

    def _run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.step()
            except Exception:
                log.exception("person follower step failed")
                stop_event.wait(1.0)  # do not spin on a persistent error (e.g. camera gone)
            stop_event.wait(INTERVAL_S)

    def step(self) -> str:
        """One detect-and-correct cycle. Returns what happened (for logs and tests)."""
        if not self._should_track():
            return "paused"
        frame = self._mini.media.get_frame()
        if frame is None:
            return "no frame"
        hit = self._detector.find_person(frame)
        if hit is None:
            return "no person"  # stay where we are; the person may step back into view
        h, w = frame.shape[:2]
        u, v = hit
        du, dv = u - w / 2, v - h / 2
        if abs(du) < self._deadband * w and abs(dv) < self._deadband * h:
            return "centred"
        # Aim part of the way there; look_at_image needs pixels strictly inside the image.
        tu = int(min(max(w / 2 + self._gain * du, 1), w - 1))
        tv = int(min(max(h / 2 + self._gain * dv, 1), h - 1))
        if not self._lock.acquire(blocking=False):
            return "busy"
        try:
            if not self._should_track():  # e.g. fell asleep while we were detecting
                return "paused"
            self._mini.look_at_image(tu, tv, duration=self._move_s)
        finally:
            self._lock.release()
        return "moved"
