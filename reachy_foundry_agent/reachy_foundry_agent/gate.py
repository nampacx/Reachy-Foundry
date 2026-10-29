"""Conversation gate: only transcripts of an active conversation may reach the LLM.

IDLE  - every utterance is transcribed, matched against the start phrases and then dropped.
ACTIVE - utterances go to the agent until an end phrase is heard or the idle timeout expires.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Literal

Action = Literal["ignore", "start", "end", "forward"]

_NON_WORD = re.compile(r"[^\w\s']", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _NON_WORD.sub(" ", text.lower()).split()


def find_phrase(tokens: list[str], phrase: str, min_ratio: float = 0.7) -> tuple[int, int] | None:
    """Locate ``phrase`` in ``tokens`` with a fuzzy match (STT often mangles names, e.g. 'Richie').

    Returns the (start, end) token span of the best window, or None.
    """
    words = tokenize(phrase)
    n = len(words)
    if n == 0 or len(tokens) < n:
        return None
    target = " ".join(words)
    best: tuple[float, int] | None = None
    for i in range(len(tokens) - n + 1):
        ratio = SequenceMatcher(None, " ".join(tokens[i : i + n]), target).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, i)
    return (best[1], best[1] + n) if best else None


@dataclass(frozen=True)
class GateResult:
    action: Action
    text: str = ""  # for "start": what was said after the wake phrase (may be empty); for "forward": the transcript


class ConversationGate:
    def __init__(
        self,
        start_phrases: tuple[str, ...],
        end_phrases: tuple[str, ...],
        idle_timeout_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.start_phrases = start_phrases
        self.end_phrases = end_phrases
        self.idle_timeout_s = idle_timeout_s
        self._clock = clock
        self.active = False
        self._last_activity = 0.0

    def touch(self) -> None:
        """Mark activity (call after a turn finished so long replies do not eat the timeout)."""
        self._last_activity = self._clock()

    def expired(self) -> bool:
        return self.active and self.idle_timeout_s > 0 and self._clock() - self._last_activity > self.idle_timeout_s

    def stop(self) -> None:
        self.active = False

    @staticmethod
    def _is_farewell(tokens: list[str], phrase: str) -> bool:
        """An end phrase only counts in a short utterance ("goodbye", "ok bye Reachy"), matched strictly.

        End phrases are short, common words, so a loose match inside a longer sentence ("by the way ...")
        must not end the conversation.
        """
        n = len(tokenize(phrase))
        return len(tokens) <= n + 3 and find_phrase(tokens, phrase, min_ratio=0.85) is not None

    def process(self, transcript: str) -> GateResult:
        """Decide what to do with one transcribed utterance."""
        if self.expired():
            self.stop()
        tokens = tokenize(transcript)
        if not self.active:
            for phrase in self.start_phrases:
                span = find_phrase(tokens, phrase)
                if span:
                    self.active = True
                    self.touch()
                    return GateResult("start", " ".join(tokens[span[1] :]))
            return GateResult("ignore")
        if any(self._is_farewell(tokens, p) for p in self.end_phrases):
            self.stop()
            return GateResult("end")
        self.touch()
        return GateResult("forward", transcript)
