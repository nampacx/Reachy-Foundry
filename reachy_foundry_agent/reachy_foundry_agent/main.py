import asyncio
import logging
import os
import threading
from functools import partial

import numpy as np
from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini.utils import create_head_pose

from .agent import build_agent
from .audio_io import EnergyEndpointer, listen_for_utterance, play_samples
from .config import Settings
from .gate import ConversationGate
from .speech import SpeechClient, pcm_to_wav

log = logging.getLogger(__name__)


class ReachyFoundryAgent(ReachyMiniApp):
    """Voice agent: mic -> Azure Speech STT -> Agent Framework (Foundry model + robot tools) -> Azure Speech TTS."""

    # No settings page needed; the app is voice-driven.
    custom_app_url: str | None = None
    request_media_backend: str | None = None

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        logging.basicConfig(level=logging.INFO)
        # Per-request HTTP dumps and credential-chain chatter would flood the robot log.
        for noisy in ("azure.core.pipeline.policies.http_logging_policy", "azure.identity", "httpx"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        settings = Settings.from_env()  # also loads .env
        if not os.environ.get("AZURE_CLIENT_SECRET"):
            log.warning(
                "AZURE_CLIENT_ID/SECRET/TENANT_ID not set: Foundry sign-in will only work "
                "with az login or a managed identity. On the robot run scripts/create-robot-sp.ps1."
            )
        speech = SpeechClient(settings)
        agent, client, robot = build_agent(settings, reachy_mini, stop_event)
        try:
            asyncio.run(self._loop(reachy_mini, stop_event, speech, agent, robot, settings))
        finally:
            speech.close()

    async def _loop(self, mini: ReachyMini, stop_event, speech: SpeechClient, agent, robot, settings: Settings) -> None:
        gate = ConversationGate(settings.start_phrases, settings.end_phrases, settings.conversation_timeout_s)
        session = None  # a fresh agent session per conversation, so context does not leak between them
        await asyncio.to_thread(self._raise_head, mini)
        await self._say(
            mini, speech, f"I'm ready. Say \"{settings.start_phrases[0]}\" when you want to talk.", stop_event
        )
        await asyncio.to_thread(robot.go_to_sleep)  # idle = asleep

        while not stop_event.is_set():
            idle = partial(EnergyEndpointer, threshold=settings.idle_vad_threshold)
            heard = await asyncio.to_thread(
                listen_for_utterance,
                mini.media,
                stop_event,
                endpointer_factory=EnergyEndpointer if gate.active else idle,
                should_abort=gate.expired,
            )
            if heard is None:
                if stop_event.is_set():
                    break
                log.info("conversation timed out")  # should_abort fired
                gate.stop()
                session = None
                await asyncio.to_thread(robot.go_to_sleep)
                continue
            samples, rate = heard
            try:
                text = await asyncio.to_thread(speech.transcribe, pcm_to_wav(samples, rate))
                if not text:
                    continue
                if gate.expired():  # timed out while this utterance was being transcribed
                    gate.stop()
                    session = None
                    await asyncio.to_thread(robot.go_to_sleep)
                decision = gate.process(text)
                if decision.action == "ignore":
                    if settings.debug_gate:
                        log.info("idle: dropped %r (no wake phrase)", text)
                    else:
                        log.info("idle: dropped a %d-word utterance (no wake phrase)", len(text.split()))
                    continue
                if decision.action == "end":
                    log.info("conversation ended by voice command")
                    session = None
                    robot.clear_pending_emotion()
                    await self._say(mini, speech, "Goodbye! Say my name when you need me.", stop_event)
                    await asyncio.to_thread(robot.go_to_sleep)
                    continue
                wake_task = None
                if decision.action == "start":
                    log.info("conversation started by voice command")
                    session = agent.create_session()
                    # Rise while the request is already being processed.
                    wake_task = asyncio.create_task(asyncio.to_thread(robot.ensure_awake))
                    # A bare wake phrase gets a greeting; "hey reachy, what time is it" is answered directly.
                    text = (
                        decision.text
                        if len(decision.text.split()) >= 2
                        else "[The user just said your wake phrase. Greet them briefly and ask how you can help.]"
                    )
                else:
                    text = decision.text
                log.info("user: %s", text)
                robot.clear_pending_emotion()
                try:
                    result = await agent.run(text, session=session)
                finally:
                    if wake_task is not None:
                        await wake_task  # never speak (or leave the turn) before the head is up
                reply = result.text.strip()
                log.info("reachy: %s", reply)
                if reply:
                    await self._say(mini, speech, reply, stop_event)
                robot.play_pending_emotion()  # emotion queued with when="after_reply"
                gate.touch()  # the timeout counts from the end of the reply, not from the question
            except Exception:
                log.exception("turn failed")
                await self._say(mini, speech, "Sorry, something went wrong. Please try again.", stop_event)

    @staticmethod
    def _raise_head(mini: ReachyMini) -> None:
        """Wake the robot, then explicitly lift the head to a neutral, upright pose.

        wake_up() alone can leave the head tucked down, so command the pose ourselves.
        """
        try:
            mini.wake_up()
        except Exception:
            log.exception("wake_up failed; raising head directly")
        mini.goto_target(head=create_head_pose(), antennas=np.zeros(2), duration=1.0)

    async def _say(self, mini: ReachyMini, speech: SpeechClient, text: str, stop_event) -> None:
        samples, rate = await asyncio.to_thread(speech.synthesize, text)
        await asyncio.to_thread(play_samples, mini.media, np.asarray(samples), rate, stop_event)


if __name__ == "__main__":
    app = ReachyFoundryAgent()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
