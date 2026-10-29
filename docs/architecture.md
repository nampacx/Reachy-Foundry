# 🏗️ Architecture

Everything runs **on the robot** (Reachy Mini Wireless, Raspberry Pi CM4, ARM64). Azure provides the brains and the voice.

```
 Reachy Mini Wireless                                   Azure (one Foundry resource)
┌────────────────────────────────────┐
│ mic ─► EnergyEndpointer (VAD)      │
│          │ utterance (WAV)         │   REST    ┌────────────────────────────┐
│          ├────────────────────────────────────►│ Speech: MAI-Transcribe-2   │
│          ▼ text                    │◄──────────┤                            │
│ ConversationGate (wake / goodbye)  │           └────────────────────────────┘
│          │ forwarded text          │   Entra ID┌────────────────────────────┐
│ Agent Framework Agent ─────────────────────────►│ Foundry project: chat model│
│   │  ▲ tool calls                  │◄──────────┤ (e.g. gpt-6.1-astra)       │
│   ▼  │                             │           └────────────────────────────┘
│ RobotTools → head, antennas, emotions│  REST   ┌────────────────────────────┐
│          │ reply text              ├────────►  │ Speech: MAI-Voice-2.1-Flash│
│ speaker ◄─ PCM ◄───────────────────┤◄──────────┤                            │
│                                    │           └────────────────────────────┘
└────────────────────────────────────┘
```

## 📦 Modules (`reachy_foundry_agent/reachy_foundry_agent/`)

| File | Job |
|---|---|
| `main.py` | `ReachyFoundryAgent` (a `ReachyMiniApp`): the async voice loop |
| `audio_io.py` | energy-based endpointing, resampling, mic capture and speaker playback via `mini.media` |
| `speech.py` | Azure Speech over REST: fast transcription and TTS (SSML) |
| `gate.py` | wake/goodbye logic and the idle timeout |
| `agent.py` | builds the Agent Framework agent and holds the persona |
| `robot_tools.py` | the tools the model can call, with validation |
| `config.py` | settings from environment / `.env` |
| `vision_local.py` | optional YOLO person detector (not wired in yet) |

## 🔄 A voice turn

1. `listen_for_utterance` records until the speaker has been quiet for 0.9 s.
2. The audio is sent to Speech for transcription.
3. The gate decides: `ignore` (asleep, no wake phrase), `start`, `end`, or `forward`.
4. Forwarded text goes to `agent.run(...)`. The model may call tools; they move the robot.
5. The reply is synthesized and played. An emotion queued with `after_reply` plays now.
6. The conversation timeout restarts from the **end of the reply**.

Logs go to the robot's own log (`journalctl`, see [deployment](deployment.md)); every tool call and conversation event is logged.

## 🧭 Design decisions

- **REST instead of the Speech SDK.** The SDK has no ARM64 wheels for the robot, and it would try to grab the microphone and speaker, which the Reachy daemon owns. Audio goes through `mini.media` instead.
- **Light VAD, no torch.** A plain RMS energy threshold keeps CPU use low on the CM4.
- **Model picks, code validates.** Tool arguments are untrusted: they are clamped and checked in `robot_tools.py`.
- **Two auth types, on purpose.** Foundry uses Entra ID (`DefaultAzureCredential`). Speech uses the resource key, because the REST calls are made directly.
- **No `cv2` dependency declared.** The apps venv on the robot already ships OpenCV, and a second package would overwrite its files.
