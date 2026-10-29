"""Microphone endpointing (light energy VAD, no torch) and speaker playback via mini.media."""

from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np


def to_mono(chunk: np.ndarray) -> np.ndarray:
    chunk = np.asarray(chunk, dtype=np.float32)
    return chunk.mean(axis=1) if chunk.ndim == 2 else chunk


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.float32)
    n_out = int(round(samples.size * dst_rate / src_rate))
    x_old = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


class EnergyEndpointer:
    """Detects the end of an utterance from per-chunk RMS energy.

    Feed chunks with ``push``; it returns the finished utterance (mono float32) once
    speech was heard and followed by ``silence_s`` of quiet, else ``None``.
    """

    def __init__(
        self,
        samplerate: int,
        threshold: float = 0.015,
        silence_s: float = 0.9,
        min_speech_s: float = 0.25,
        max_utterance_s: float = 15.0,
        preroll_s: float = 0.3,
    ) -> None:
        self.samplerate = samplerate
        self.threshold = threshold
        self.silence_s = silence_s
        self.min_speech_s = min_speech_s
        self.max_utterance_s = max_utterance_s
        self._preroll_max = int(preroll_s * samplerate)
        self.reset()

    def reset(self) -> None:
        self._preroll: list[np.ndarray] = []
        self._preroll_len = 0
        self._chunks: list[np.ndarray] = []
        self._speech_s = 0.0
        self._quiet_s = 0.0
        self.in_speech = False

    def push(self, chunk: np.ndarray) -> np.ndarray | None:
        chunk = to_mono(chunk)
        if chunk.size == 0:
            return None
        dur = chunk.size / self.samplerate
        loud = float(np.sqrt(np.mean(chunk**2))) >= self.threshold

        if not self.in_speech:
            if loud:
                self.in_speech = True
                self._chunks = list(self._preroll) + [chunk]
                self._speech_s, self._quiet_s = dur, 0.0
            else:
                self._preroll.append(chunk)
                self._preroll_len += chunk.size
                while self._preroll_len > self._preroll_max and len(self._preroll) > 1:
                    self._preroll_len -= self._preroll.pop(0).size
            return None

        self._chunks.append(chunk)
        if loud:
            self._speech_s += dur
            self._quiet_s = 0.0
        else:
            self._quiet_s += dur

        total_s = sum(c.size for c in self._chunks) / self.samplerate
        if self._quiet_s >= self.silence_s or total_s >= self.max_utterance_s:
            utterance = np.concatenate(self._chunks)
            enough = self._speech_s >= self.min_speech_s
            self.reset()
            return utterance if enough else None
        return None


def listen_for_utterance(
    media,
    stop_event: threading.Event,
    endpointer_factory: Callable[[int], EnergyEndpointer] = EnergyEndpointer,
    should_abort: Callable[[], bool] | None = None,
) -> tuple[np.ndarray, int] | None:
    """Block until a full utterance is captured. Returns (mono samples, samplerate).

    Returns None if ``stop_event`` is set or ``should_abort()`` turns true (checked while no speech is in progress).
    """
    rate = media.get_input_audio_samplerate()
    endpointer = endpointer_factory(rate)
    media.start_recording()
    try:
        while not stop_event.is_set():
            if should_abort is not None and not endpointer.in_speech and should_abort():
                return None
            chunk = media.get_audio_sample()
            if chunk is None or len(chunk) == 0:
                time.sleep(0.01)
                continue
            utterance = endpointer.push(chunk)
            if utterance is not None:
                return utterance, rate
    finally:
        media.stop_recording()
    return None


def play_samples(media, samples: np.ndarray, src_rate: int, stop_event: threading.Event) -> None:
    """Play mono float32 samples through the robot speaker, in ~100 ms chunks."""
    out_rate = media.get_output_audio_samplerate()
    channels = max(1, media.get_output_channels())
    data = resample(samples, src_rate, out_rate)
    if channels > 1:
        data = np.repeat(data[:, None], channels, axis=1)
    step = max(1, out_rate // 10)
    media.start_playing()
    started = time.monotonic()
    try:
        for i in range(0, len(data), step):
            if stop_event.is_set():
                break
            media.push_audio_sample(np.ascontiguousarray(data[i : i + step], dtype=np.float32))
        # Pushing does not wait for playback, so stopping now would cut the reply off.
        # Wait until the whole clip has played (plus a little for the output buffer).
        end = started + len(data) / out_rate + 0.4
        while not stop_event.is_set() and time.monotonic() < end:
            time.sleep(0.05)
    finally:
        media.stop_playing()
