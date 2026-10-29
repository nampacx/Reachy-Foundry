# 🎙️ Models

Three models, one Foundry resource.

| Job | Model | Where it runs | Setting |
|---|---|---|---|
| Speech to text | `MAI-Transcribe-2` | Azure Speech fast transcription (`enhancedMode.model`) | `AZURE_SPEECH_STT_MODEL` |
| Text to speech | `en-US-Harper:MAI-Voice-2.1-Flash` | Azure Speech TTS (SSML voice name) | `AZURE_SPEECH_VOICE` |
| Reasoning / chat | deployment named in `FOUNDRY_MODEL` (author uses `gpt-6.1-astra`) | Foundry model deployment | `FOUNDRY_MODEL` |

## 🗣️ Speech (MAI)

Both go through the Speech resource that comes with the Foundry resource, with REST and the resource key:

- STT: `POST /speechtotext/transcriptions:transcribe?api-version=2025-10-15`, a WAV plus a `definition` with the language code (`en`, not `en-US`), `enhancedMode` and `transcribeStyle: clean` (no filler words, better input for the agent).
- TTS: `POST /tts/cognitiveservices/v1` with SSML, output `riff-16khz-16bit-mono-pcm`.

Change language or voice with `AZURE_SPEECH_LOCALE` and `AZURE_SPEECH_VOICE`. Note that the wake and goodbye phrases are English by default ([wake & goodbye](wake-and-goodbye.md)).

## 🧠 Chat model

Requirements: **tool calling** (the robot is driven by tools) and, for the planned camera, **image input**. Because the output is spoken, short and fast beats big and slow.

The Bicep default is `gpt-5.4-mini` so a fresh `azd up` works without special quota. To use another one:

```bash
azd env set CHAT_MODEL_NAME gpt-6.1-astra
azd env set CHAT_MODEL_VERSION <version from the Foundry model catalog>
azd provision
```

Then copy the new `.env` to the robot (`./scripts/deploy-to-robot.sh --restart`). Newer models may need a quota request; check availability in your region first. You can also change `CHAT_SKU_NAME` and `CHAT_CAPACITY` (thousand tokens per minute).

## 🤔 Why not MAI Thinking 1 for the chat?

It would have been the all-Microsoft-MAI choice, but the planned camera needs image input, so a general chat model it is. Swapping it later is only a deployment change, since the app only knows a deployment name.
