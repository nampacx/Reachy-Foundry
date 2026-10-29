"""Robot capabilities exposed to the Microsoft Agent Framework agent as tools.

The model only picks tools and arguments; every argument is validated/clamped here
because tool arguments are untrusted. Motion uses ``goto_target`` (smooth gestures).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import threading
import time
from typing import Annotated, Any, Awaitable, Callable

import numpy as np
from pydantic import Field

from agent_framework import Content, Message, tool
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

log = logging.getLogger(__name__)

_DIRECTIONS = {  # (yaw, pitch) unit vectors; positive yaw = robot's left
    "left": (1.0, 0.0),
    "right": (-1.0, 0.0),
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
    "front": (0.0, 0.0),
}
_TILTS = {"none": 0.0, "left": -1.0, "right": 1.0}  # roll about the forward axis; + = right ear down
_MOODS = {  # antenna pose (right, left) in degrees, plus wiggle count
    "happy": ((40.0, -40.0), 4),
    "excited": ((60.0, -60.0), 6),
    "curious": ((30.0, 10.0), 2),
    "sad": ((-60.0, 60.0), 1),
    "surprised": ((70.0, -70.0), 1),
}
MAX_ANGLE_DEG = 35.0
# Sleep/wake clips (sleep1, mini-deep-sleep, wake-mini-up) are for the idle/active transitions, which the app
# drives itself; the model only runs during a conversation, so it must not see or play them.
_RESERVED_EMOTION_WORDS = ("sleep", "wake")


def _is_reserved_emotion(name: str) -> bool:
    return any(word in name.lower() for word in _RESERVED_EMOTION_WORDS)


_ASLEEP_MSG = "error: I am asleep; call wake_up first"

VisionFn = Callable[[bytes, str], Awaitable[str]]


def _logged(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool so each call logs its arguments, result and duration (signature kept for the schema)."""
    name = fn.__name__

    def _args(args: tuple, kwargs: dict) -> str:
        return ", ".join([repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()])

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def awrapper(*args, **kwargs):
            log.info("tool call: %s(%s)", name, _args(args, kwargs))
            start = time.monotonic()
            result = await fn(*args, **kwargs)
            log.info("tool result: %s -> %r (%.2fs)", name, result, time.monotonic() - start)
            return result

        return awrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        log.info("tool call: %s(%s)", name, _args(args, kwargs))
        start = time.monotonic()
        result = fn(*args, **kwargs)
        log.info("tool result: %s -> %r (%.2fs)", name, result, time.monotonic() - start)
        return result

    return wrapper


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


class RobotTools:
    """Bundles the SDK handle with the tool implementations."""

    def __init__(
        self,
        mini: ReachyMini,
        vision: VisionFn | None = None,
        stop_event: threading.Event | None = None,
        emotions_dataset: str = "pollen-robotics/reachy-mini-emotions-library",
        detector: Any | None = None,
    ) -> None:
        self._mini = mini
        self._vision = vision
        self._detector = detector  # on-robot PersonDetector, or None when unavailable
        self._stop = stop_event
        self._emotions_dataset = emotions_dataset
        self._emotions = None
        self._lock = threading.Lock()  # one physical action at a time
        self._asleep = False  # the app wakes the robot on start
        self._pending_emotion: str | None = None  # queued by play_emotion(when="after_reply")
        self._emotion_thread: threading.Thread | None = None

    # --- helpers -----------------------------------------------------------------
    def _goto(self, yaw=0.0, pitch=0.0, roll=0.0, antennas=None, duration=0.7) -> None:
        head = create_head_pose(yaw=yaw, pitch=pitch, roll=roll, degrees=True)
        ant = None if antennas is None else np.deg2rad(np.asarray(antennas, dtype=float))
        with self._lock:
            self._mini.goto_target(head=head, antennas=ant, duration=duration)

    def _load_emotions(self):
        if self._emotions is None:
            from reachy_mini.motion.recorded_move import RecordedMoves

            self._emotions = RecordedMoves(self._emotions_dataset)
        return self._emotions

    # --- tools -------------------------------------------------------------------
    def move_head(
        self,
        direction: Annotated[
            str,
            Field(
                description="One of: left, right, up, down, front, or a combination such as "
                "'up left' or 'down right'"
            ),
        ] = "front",
        degrees: Annotated[float, Field(description="How far to turn, 0-35")] = 20.0,
        tilt: Annotated[
            str, Field(description="Tilt the head sideways like a curious dog: none, left or right")
        ] = "none",
        tilt_degrees: Annotated[float, Field(description="How far to tilt, 0-35")] = 20.0,
    ) -> str:
        """Move the head: turn/look in a direction (optionally diagonal) and/or tilt it sideways."""
        if self._asleep:
            return _ASLEEP_MSG
        words = direction.lower().replace("-", " ").replace("_", " ").split()
        if not words or any(w not in _DIRECTIONS for w in words):
            return f"error: direction must be one of {sorted(_DIRECTIONS)}, or a combination"
        tilt = tilt.lower()
        if tilt not in _TILTS:
            return f"error: tilt must be one of {sorted(_TILTS)}"
        deg = _clamp(degrees, 0.0, MAX_ANGLE_DEG)
        yaw = _clamp(sum(_DIRECTIONS[w][0] for w in words), -1.0, 1.0) * deg
        pitch = _clamp(sum(_DIRECTIONS[w][1] for w in words), -1.0, 1.0) * deg
        roll = _TILTS[tilt] * _clamp(tilt_degrees, 0.0, MAX_ANGLE_DEG)
        self._goto(yaw=yaw, pitch=pitch, roll=roll)
        parts = [f"looking {' '.join(words)}"] if direction.strip() else []
        if tilt != "none":
            parts.append(f"tilted {tilt}")
        return ", ".join(parts)

    def nod(self, times: Annotated[int, Field(description="Number of nods, 1-4")] = 2) -> str:
        """Nod the head 'yes' to agree or acknowledge."""
        if self._asleep:
            return _ASLEEP_MSG
        for _ in range(int(_clamp(times, 1, 4))):
            self._goto(pitch=15, duration=0.3)
            self._goto(pitch=-5, duration=0.3)
        self._goto(duration=0.4)
        return "nodded"

    def shake_head(self, times: Annotated[int, Field(description="Number of shakes, 1-4")] = 2) -> str:
        """Shake the head 'no' to disagree or express doubt."""
        if self._asleep:
            return _ASLEEP_MSG
        for _ in range(int(_clamp(times, 1, 4))):
            self._goto(yaw=20, duration=0.3)
            self._goto(yaw=-20, duration=0.3)
        self._goto(duration=0.4)
        return "shook head"

    def express_mood(
        self,
        mood: Annotated[str, Field(description="One of: happy, excited, curious, sad, surprised")],
    ) -> str:
        """Wiggle the antennas to show a feeling. Quick, lightweight reaction."""
        if self._asleep:
            return _ASLEEP_MSG
        if mood not in _MOODS:
            return f"error: mood must be one of {sorted(_MOODS)}"
        (right, left), wiggles = _MOODS[mood]
        for i in range(wiggles):
            sign = 1 if i % 2 == 0 else -0.5
            self._goto(antennas=[right * sign, left * sign], duration=0.25)
        self._goto(antennas=[0, 0], duration=0.4)
        return f"showed {mood}"

    def list_emotions(self) -> str:
        """List the names of recorded emotion animations the robot can play."""
        return ", ".join(sorted(self._available_emotions()))

    def _available_emotions(self) -> list[str]:
        return [n for n in self._load_emotions().list_moves() if not _is_reserved_emotion(n)]

    def play_emotion(
        self,
        name: Annotated[str, Field(description="Emotion name from list_emotions, e.g. 'happy'")],
        when: Annotated[
            str,
            Field(
                description="'now' (default) plays it right away while you keep talking; 'after_reply' "
                "plays it once you have finished speaking, e.g. as the reaction after telling a joke"
            ),
        ] = "now",
    ) -> str:
        """Play a recorded, expressive emotion animation (with sound if the clip has any). Returns immediately; the animation runs in the background."""
        if self._asleep:
            return _ASLEEP_MSG
        if when not in ("now", "after_reply"):
            return "error: when must be 'now' or 'after_reply'"
        if name not in self._available_emotions():
            return "error: unknown emotion; call list_emotions first"
        if when == "after_reply":
            self._pending_emotion = name
            return f"will play {name} after the reply"
        self._start_emotion(name)
        return f"playing {name}"

    def _start_emotion(self, name: str) -> None:
        move = self._load_emotions().get(name)

        def run() -> None:
            try:
                with self._lock:
                    self._mini.play_move(move, initial_goto_duration=1.0)
                log.info("emotion finished: %s", name)
            except Exception:
                log.exception("emotion %s failed", name)

        self._emotion_thread = threading.Thread(target=run, name=f"emotion-{name}", daemon=True)
        self._emotion_thread.start()

    def clear_pending_emotion(self) -> None:
        self._pending_emotion = None

    def play_pending_emotion(self) -> None:
        """Start the emotion queued with when='after_reply' (called by the app once speech has played)."""
        name, self._pending_emotion = self._pending_emotion, None
        if name and not self._asleep:
            self._start_emotion(name)

    def go_to_sleep(self) -> str:
        """Go to sleep: fold the head down and go limp. Use when asked to sleep, rest or say goodnight. Say a short goodnight, then stay quiet until asked to wake up."""
        if self._asleep:
            return "already asleep"
        with self._lock:
            self._mini.goto_sleep()
        self._asleep = True
        return "fell asleep"

    def wake_up(self) -> str:
        """Wake up from sleep: lift the head and play the wake-up sound. Use when asked to wake up."""
        if not self._asleep:
            return "already awake"
        self._wake()
        return "woke up"

    def ensure_awake(self) -> None:
        """Physically raise the head even if we believe we are awake (app-side; not exposed to the model).

        The app calls this when a conversation starts, so a head that is down while the flag says "awake"
        (e.g. it was put to sleep from the dashboard) still comes up.
        """
        log.info("raising head (believed asleep: %s)", self._asleep)
        self._wake()

    def _wake(self) -> None:
        # Clear the flag first so tools called while the head is still rising are not refused;
        # they wait on the lock until the wake-up motion has finished.
        self._asleep = False
        try:
            with self._lock:
                self._mini.wake_up()
                # wake_up() alone can leave the head tucked down, so command a neutral upright pose too.
                self._mini.goto_target(head=create_head_pose(), antennas=np.zeros(2), duration=1.0)
        except Exception:
            self._asleep = True
            log.exception("wake-up failed")
            raise
        log.info("head raised")

    def _capture_jpeg(self) -> bytes | None:
        import cv2  # only needed for the camera, which is currently not wired in

        self._goto(pitch=-8, duration=0.4)  # lift the head a little: 'looking' reaction
        frame = self._mini.media.get_frame()
        if frame is None:
            return None
        ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return None
        self.express_mood("surprised")  # shutter reaction
        return jpeg.tobytes()

    async def describe_view(
        self,
        question: Annotated[
            str, Field(description="What to look for, e.g. 'What do you see?' or 'Read the text on the sign'")
        ] = "Describe what you see in two or three sentences.",
    ) -> str:
        """Take a picture with the robot's camera and get a description of it. Use whenever the user asks you to look, take a picture, or say what you see."""
        if self._asleep:
            return _ASLEEP_MSG
        jpeg = await asyncio.to_thread(self._capture_jpeg)
        if jpeg is None:
            return "error: the camera did not return an image"
        return await self._vision(jpeg, question)

    def _look_at_person(self) -> str:
        frame = self._mini.media.get_frame()
        if frame is None:
            return "error: the camera did not return an image"
        try:
            hit = self._detector.find_person(frame)
        except Exception:
            log.exception("person detection failed")
            return "error: person detection failed"
        if hit is None:
            return "I can't see anyone right now"
        u, v = hit
        with self._lock:
            self._mini.look_at_image(int(u), int(v), duration=0.8)
        return "looking at the person"

    async def look_at_person(self) -> str:
        """Find a person in front of the camera and turn the head to look at them. Runs on the robot, quick. Use when asked to look at me, find someone, or greet whoever is there."""
        if self._asleep:
            return _ASLEEP_MSG
        return await asyncio.to_thread(self._look_at_person)

    # --- registration ------------------------------------------------------------
    def as_tools(self) -> list[Any]:
        fns = [
            self.move_head,
            self.nod,
            self.shake_head,
            self.express_mood,
            self.list_emotions,
            self.play_emotion,
            self.go_to_sleep,
            self.wake_up,
        ]
        if self._vision is not None:
            fns.append(self.describe_view)
        if self._detector is not None:
            fns.append(self.look_at_person)
        return [tool(_logged(fn), name=fn.__name__, description=(fn.__doc__ or "").strip()) for fn in fns]


async def describe_image(client, jpeg: bytes, question: str) -> str:
    """One-shot vision call on the same Foundry chat client (no tools, no history)."""
    from agent_framework import Agent

    vision_agent = Agent(
        client=client,
        instructions="You are the eyes of a small friendly robot. Answer briefly and concretely.",
    )
    msg = Message("user", [Content.from_text(question), Content.from_data(jpeg, "image/jpeg")])
    result = await vision_agent.run(msg)
    return result.text
