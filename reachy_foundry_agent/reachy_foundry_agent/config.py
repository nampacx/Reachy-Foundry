"""Runtime configuration, read from environment variables (optionally a local .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from ./.env or ~/.reachy_foundry.env without overriding the environment."""
    for path in (Path.cwd() / ".env", Path.home() / ".reachy_foundry.env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _phrases(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated phrase list from the environment."""
    parsed = tuple(p.strip().lower() for p in os.environ.get(name, "").split(",") if p.strip())
    return parsed or default


@dataclass(frozen=True)
class Settings:
    foundry_project_endpoint: str
    foundry_model: str
    speech_endpoint: str
    speech_api_key: str
    # Reasoning effort for reasoning models: none/low/medium/high, or "default" to send nothing (the model's own).
    # "none" by default: spoken replies are short and latency matters more than deep thinking.
    reasoning_effort: str = "none"
    speech_locale: str = "en-US"
    speech_voice: str = "en-US-Harper:MAI-Voice-2.1-Flash"
    speech_stt_model: str = "MAI-Transcribe-2"  # fast-transcription enhancedMode.model
    emotions_dataset: str = "pollen-robotics/reachy-mini-emotions-library"
    person_model: str = "yolov8n.pt"  # on-robot person detector (ultralytics weights name or path)
    follow_person: bool = True  # keep the head on the person in view while awake (needs ultralytics)
    start_phrases: tuple[str, ...] = ("hey reachy", "hello reachy", "hi reachy", "ok reachy")
    end_phrases: tuple[str, ...] = ("goodbye", "bye", "end conversation", "stop conversation")
    conversation_timeout_s: float = 60.0  # back to idle after this much silence; 0 disables
    # Voice-activity threshold (RMS) while idle. Lower than the active one because the folded-down sleeping
    # head muffles the microphone.
    idle_vad_threshold: float = 0.008
    debug_gate: bool = False  # log the text of dropped idle utterances (privacy: off by default)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        missing = [
            name
            for name in (
                "FOUNDRY_PROJECT_ENDPOINT",
                "FOUNDRY_MODEL",
                "AZURE_SPEECH_ENDPOINT",
                "AZURE_SPEECH_API_KEY",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
        return cls(
            foundry_project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            foundry_model=os.environ["FOUNDRY_MODEL"],
            speech_endpoint=os.environ["AZURE_SPEECH_ENDPOINT"].rstrip("/"),
            speech_api_key=os.environ["AZURE_SPEECH_API_KEY"],
            reasoning_effort=os.environ.get("FOUNDRY_REASONING_EFFORT", "none").strip().lower(),
            speech_locale=os.environ.get("AZURE_SPEECH_LOCALE", "en-US"),
            speech_voice=os.environ.get("AZURE_SPEECH_VOICE", "en-US-Harper:MAI-Voice-2.1-Flash"),
            speech_stt_model=os.environ.get("AZURE_SPEECH_STT_MODEL", "MAI-Transcribe-2"),
            person_model=os.environ.get("REACHY_PERSON_MODEL", "yolov8n.pt"),
            follow_person=os.environ.get("REACHY_FOLLOW_PERSON", "1") != "0",
            start_phrases=_phrases("REACHY_START_PHRASES", cls.start_phrases),
            end_phrases=_phrases("REACHY_END_PHRASES", cls.end_phrases),
            conversation_timeout_s=float(os.environ.get("REACHY_CONVERSATION_TIMEOUT_S", "60")),
            idle_vad_threshold=float(os.environ.get("REACHY_IDLE_VAD_THRESHOLD", "0.008")),
            debug_gate=os.environ.get("REACHY_DEBUG_GATE", "") == "1",
        )
