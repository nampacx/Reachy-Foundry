"""Azure Speech (Foundry Tools) clients over REST: fast transcription (STT) and neural TTS.

REST is used instead of the Speech SDK because the SDK's native wheels are not
available for the Wireless robot's ARM64 Linux, and it would try to grab the
microphone/speaker that the Reachy daemon owns.
"""

from __future__ import annotations

import io
import json
import wave
from xml.sax.saxutils import escape

import httpx
import numpy as np

from .config import Settings

TTS_SAMPLE_RATE = 16000
_STT_API_VERSION = "2025-10-15"


def pcm_to_wav(pcm: np.ndarray, samplerate: int) -> bytes:
    """Encode mono float32 [-1, 1] samples as 16-bit PCM WAV bytes."""
    clipped = np.clip(pcm, -1.0, 1.0)
    data = (clipped * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(data)
    return buf.getvalue()


def wav_to_float(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Decode 16-bit PCM WAV bytes to mono float32 samples and the sample rate."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


class SpeechClient:
    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self._s = settings
        self._http = httpx.Client(
            base_url=settings.speech_endpoint,
            headers={"Ocp-Apim-Subscription-Key": settings.speech_api_key},
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def transcribe(self, wav_bytes: bytes) -> str:
        """Fast-transcription of one utterance. Returns '' when nothing was recognised."""
        definition = {
            # MAI-Transcribe takes a language code ("en"), not a full locale ("en-US").
            "locales": [self._s.speech_locale.split("-")[0]],
            "enhancedMode": {
                "enabled": True,
                "model": self._s.speech_stt_model,
                "modelOptions": {"transcribeStyle": "clean"},  # no fillers: better input for the agent
            },
        }
        resp = self._http.post(
            "/speechtotext/transcriptions:transcribe",
            params={"api-version": _STT_API_VERSION},
            files={
                "audio": ("utterance.wav", wav_bytes, "audio/wav"),
                "definition": (None, json.dumps(definition), "application/json"),
            },
        )
        resp.raise_for_status()
        phrases = resp.json().get("combinedPhrases") or []
        return " ".join(p.get("text", "") for p in phrases).strip()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Neural TTS. Returns mono float32 samples and their sample rate."""
        ssml = (
            f"<speak version='1.0' xml:lang='{self._s.speech_locale}'>"
            f"<voice name='{self._s.speech_voice}'>{escape(text)}</voice></speak>"
        )
        resp = self._http.post(
            "/tts/cognitiveservices/v1",
            content=ssml.encode("utf-8"),
            headers={
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
            },
        )
        resp.raise_for_status()
        return wav_to_float(resp.content)
