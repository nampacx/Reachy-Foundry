import asyncio
import json
import threading
from unittest.mock import MagicMock

import httpx
import numpy as np

from reachy_foundry_agent.audio_io import EnergyEndpointer, listen_for_utterance, resample
from reachy_foundry_agent.config import Settings
from reachy_foundry_agent.robot_tools import RobotTools
from reachy_foundry_agent.speech import SpeechClient, pcm_to_wav, wav_to_float

RATE = 16000


def tone(seconds, amp=0.2):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def feed(ep, signal, chunk=1600):
    for i in range(0, len(signal), chunk):
        out = ep.push(signal[i : i + chunk])
        if out is not None:
            return out
    return None


def test_endpointer_returns_utterance_after_silence():
    ep = EnergyEndpointer(RATE)
    out = feed(ep, np.concatenate([silence(0.5), tone(1.0), silence(1.2)]))
    # 1.0 s speech + 0.3 s pre-roll + 0.9 s trailing silence (chunk-rounded)
    assert out is not None and 2.0 <= len(out) / RATE <= 2.5


def test_endpointer_ignores_short_blip_and_silence():
    ep = EnergyEndpointer(RATE)
    assert feed(ep, np.concatenate([silence(1), tone(0.1), silence(1.5)])) is None
    assert feed(EnergyEndpointer(RATE), silence(5)) is None


def test_resample_length_and_identity():
    x = tone(1.0)
    assert len(resample(x, RATE, 48000)) == 48000
    assert np.array_equal(resample(x, RATE, RATE), x)


def test_wav_roundtrip():
    x = tone(0.2)
    y, rate = wav_to_float(pcm_to_wav(x, RATE))
    assert rate == RATE and np.allclose(x, y, atol=1e-3)


def test_listen_for_utterance_uses_media_and_stops_recording():
    media = MagicMock()
    media.get_input_audio_samplerate.return_value = RATE
    sig = np.concatenate([tone(1.0), silence(1.2)])
    chunks = [sig[i : i + 1600] for i in range(0, len(sig), 1600)]
    media.get_audio_sample.side_effect = chunks
    result = listen_for_utterance(media, threading.Event())
    assert result is not None and result[1] == RATE
    media.start_recording.assert_called_once()
    media.stop_recording.assert_called_once()


def make_tools(mini=None, vision=None):
    mini = mini or MagicMock()
    vision = vision or (lambda jpeg, q: asyncio.sleep(0, result="a red cube"))
    return RobotTools(mini, vision, threading.Event()), mini


def test_move_head_clamps_and_validates():
    tools, mini = make_tools()
    assert tools.move_head("sideways").startswith("error")
    mini.goto_target.assert_not_called()
    tools.move_head("left", 999)
    head = mini.goto_target.call_args.kwargs["head"]
    assert head.shape == (4, 4)
    yaw = np.arctan2(head[1, 0], head[0, 0])
    assert abs(np.degrees(yaw) - 35.0) < 1.0  # clamped to MAX_ANGLE_DEG


def test_move_head_diagonal_and_tilt():
    tools, mini = make_tools()
    assert tools.move_head("up left", 10, "right", 15) == "looking up left, tilted right"
    head = mini.goto_target.call_args.kwargs["head"]
    rot = head[:3, :3]  # Rz(yaw) @ Ry(pitch) @ Rx(roll)
    yaw = np.degrees(np.arctan2(rot[1, 0], rot[0, 0]))
    pitch = np.degrees(-np.arcsin(rot[2, 0]))
    roll = np.degrees(np.arctan2(rot[2, 1], rot[2, 2]))
    assert abs(yaw - 10) < 1 and abs(pitch + 10) < 1 and abs(roll - 15) < 1
    assert tools.move_head("up", tilt="sideways").startswith("error")
    assert tools.move_head("up banana").startswith("error")


def test_sleep_blocks_motion_until_wake_up():
    tools, mini = make_tools()
    assert tools.wake_up() == "already awake"
    assert tools.go_to_sleep() == "fell asleep"
    assert tools.go_to_sleep() == "already asleep"
    mini.goto_sleep.assert_called_once()
    for result in (tools.move_head("left"), tools.nod(), tools.shake_head(), tools.express_mood("happy"),
                   tools.play_emotion("happy")):
        assert result.startswith("error: I am asleep")
    mini.goto_target.assert_not_called()
    mini.play_move.assert_not_called()
    assert tools.wake_up() == "woke up"
    mini.wake_up.assert_called_once()
    assert tools.move_head("left") == "looking left"


def test_nod_count_is_bounded():
    tools, mini = make_tools()
    tools.nod(100)
    assert mini.goto_target.call_count == 4 * 2 + 1


def test_play_emotion_unknown_is_rejected():
    tools, mini = make_tools()
    tools._emotions = MagicMock()
    tools._emotions.list_moves.return_value = ["happy"]
    assert tools.play_emotion("../../etc").startswith("error")
    mini.play_move.assert_not_called()
    assert tools.play_emotion("happy") == "playing happy"
    tools._emotion_thread.join(timeout=2)
    mini.play_move.assert_called_once()


def test_play_emotion_after_reply_is_deferred():
    tools, mini = make_tools()
    tools._emotions = MagicMock()
    tools._emotions.list_moves.return_value = ["laughing1"]
    assert tools.play_emotion("laughing1", "after_reply") == "will play laughing1 after the reply"
    assert tools.play_emotion("laughing1", "later").startswith("error")
    mini.play_move.assert_not_called()
    tools.play_pending_emotion()
    tools._emotion_thread.join(timeout=2)
    mini.play_move.assert_called_once()
    tools.play_pending_emotion()  # queue was consumed
    assert mini.play_move.call_count == 1


def test_logged_tools_log_arguments(caplog):
    from reachy_foundry_agent.robot_tools import _logged

    tools, _ = make_tools()
    with caplog.at_level("INFO"):
        _logged(tools.move_head)("left", 10)
    assert "tool call: move_head('left', 10)" in caplog.text
    assert "tool result: move_head -> 'looking left'" in caplog.text


def test_describe_view_returns_vision_text():
    mini = MagicMock()
    mini.media.get_frame.return_value = np.zeros((48, 64, 3), dtype=np.uint8)
    tools, _ = make_tools(mini)
    assert asyncio.run(tools.describe_view("what?")) == "a red cube"


def test_describe_view_handles_missing_frame():
    mini = MagicMock()
    mini.media.get_frame.return_value = None
    tools, _ = make_tools(mini)
    assert asyncio.run(tools.describe_view()).startswith("error")


def test_all_tools_registered_with_names():
    tools, _ = make_tools()
    names = {t.name for t in tools.as_tools()}
    assert {"move_head", "nod", "shake_head", "express_mood", "play_emotion", "go_to_sleep", "wake_up", "describe_view"} <= names


def test_look_at_person_only_registered_with_detector():
    tools, _ = make_tools()
    assert "look_at_person" not in {t.name for t in tools.as_tools()}
    with_det = RobotTools(MagicMock(), lambda j, q: None, threading.Event(), detector=MagicMock())
    assert "look_at_person" in {t.name for t in with_det.as_tools()}


def _tools_with_detector(hit, frame=True):
    mini = MagicMock()
    mini.media.get_frame.return_value = np.zeros((48, 64, 3), dtype=np.uint8) if frame else None
    detector = MagicMock()
    detector.find_person.return_value = hit
    return RobotTools(mini, lambda j, q: None, threading.Event(), detector=detector), mini


def test_look_at_person_turns_toward_detection():
    tools, mini = _tools_with_detector((40.4, 12.9))
    assert asyncio.run(tools.look_at_person()) == "looking at the person"
    assert mini.look_at_image.call_args.args == (40, 12)


def test_look_at_person_nobody_or_no_frame_or_failure():
    tools, mini = _tools_with_detector(None)
    assert "can't see" in asyncio.run(tools.look_at_person())
    mini.look_at_image.assert_not_called()
    tools, _ = _tools_with_detector(None, frame=False)
    assert asyncio.run(tools.look_at_person()).startswith("error")
    tools, _ = _tools_with_detector(None)
    tools._detector.find_person.side_effect = RuntimeError("boom")
    assert asyncio.run(tools.look_at_person()).startswith("error")


def _settings():
    return Settings("https://p", "m", "https://speech.example", "KEY")


def test_speech_transcribe_request_shape(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"], seen["key"] = str(request.url), request.headers["Ocp-Apim-Subscription-Key"]
        seen["body"] = request.content
        return httpx.Response(200, json={"combinedPhrases": [{"text": "hello robot"}]})

    client = SpeechClient(_settings())
    client._http = httpx.Client(
        base_url="https://speech.example",
        headers={"Ocp-Apim-Subscription-Key": "KEY"},
        transport=httpx.MockTransport(handler),
    )
    assert client.transcribe(pcm_to_wav(tone(0.5), RATE)) == "hello robot"
    assert "transcriptions:transcribe" in seen["url"] and seen["key"] == "KEY"
    assert b'"locales": ["en"]' in seen["body"]
    assert b"MAI-Transcribe-2" in seen["body"]


def test_speech_synthesize_escapes_ssml():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, content=pcm_to_wav(tone(0.2), RATE))

    client = SpeechClient(_settings())
    client._http = httpx.Client(base_url="https://speech.example", transport=httpx.MockTransport(handler))
    samples, rate = client.synthesize("1 < 2 & <voice>")
    assert rate == RATE and len(samples) > 0
    assert "1 &lt; 2 &amp; &lt;voice&gt;" in seen["body"]


def test_settings_missing_env(monkeypatch, tmp_path):
    for k in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL", "AZURE_SPEECH_ENDPOINT", "AZURE_SPEECH_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    try:
        Settings.from_env()
    except RuntimeError as e:
        assert "FOUNDRY_MODEL" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_settings_reasoning_effort_defaults_to_none(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    for k, v in (("FOUNDRY_PROJECT_ENDPOINT", "https://p"), ("FOUNDRY_MODEL", "gpt-6-luna"),
                 ("AZURE_SPEECH_ENDPOINT", "https://s"), ("AZURE_SPEECH_API_KEY", "K")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("FOUNDRY_REASONING_EFFORT", raising=False)
    assert Settings.from_env().reasoning_effort == "none"
    monkeypatch.setenv("FOUNDRY_REASONING_EFFORT", " Low ")
    assert Settings.from_env().reasoning_effort == "low"


def test_listen_for_utterance_aborts_when_asked():
    media = MagicMock()
    media.get_input_audio_samplerate.return_value = RATE
    media.get_audio_sample.return_value = silence(0.1)
    assert listen_for_utterance(media, threading.Event(), should_abort=lambda: True) is None
    media.stop_recording.assert_called_once()


def test_wake_up_raises_head_and_restores_state_on_failure():
    tools, mini = make_tools()
    tools.go_to_sleep()
    assert tools.wake_up() == "woke up"
    mini.goto_target.assert_called_once()  # neutral upright pose after wake_up()
    tools.go_to_sleep()
    mini.wake_up.side_effect = RuntimeError("boom")
    try:
        tools.wake_up()
    except RuntimeError:
        pass
    assert tools.move_head("left").startswith("error: I am asleep")


def test_sleep_and_wake_emotions_are_hidden_and_rejected():
    tools, mini = make_tools()
    tools._emotions = MagicMock()
    tools._emotions.list_moves.return_value = ["happy", "sleep1", "mini-deep-sleep", "wake-mini-up", "tired1"]
    assert tools.list_emotions() == "happy, tired1"
    for name in ("sleep1", "mini-deep-sleep", "wake-mini-up"):
        assert tools.play_emotion(name).startswith("error")
    mini.play_move.assert_not_called()
    assert tools.play_emotion("tired1") == "playing tired1"
    tools._emotion_thread.join(timeout=2)


def test_ensure_awake_moves_even_when_flag_says_awake():
    tools, mini = make_tools()
    tools.ensure_awake()
    mini.wake_up.assert_called_once()
    assert "ensure_awake" not in {t.name for t in tools.as_tools()}
