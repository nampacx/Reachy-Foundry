# 🦾 Robot tools

Defined in `robot_tools.py` (`RobotTools`) and registered with `tool(...)`. Every call is logged with arguments, result and duration. All tool arguments are validated or clamped, because the model's output is untrusted.

Only one physical action runs at a time (a lock), so overlapping gestures queue instead of fighting.

| Tool | What it does | Limits |
|---|---|---|
| `move_head(direction, degrees, tilt, tilt_degrees)` | Look left/right/up/down/front or diagonal (`"up left"`); optionally tilt sideways | angles clamped to 0-35° |
| `nod(times)` | Nod "yes" | 1-4 times |
| `shake_head(times)` | Shake "no" | 1-4 times |
| `express_mood(mood)` | Wiggle antennas: `happy`, `excited`, `curious`, `sad`, `surprised` | fixed moods |
| `list_emotions()` | Names of the recorded emotion clips | hides sleep/wake clips |
| `play_emotion(name, when)` | Play a recorded animation (with sound if the clip has any) in the background. `when`: `now` or `after_reply` | name must exist in the library |
| `go_to_sleep()` | Fold the head and go limp | |
| `wake_up()` | Lift the head | |

While the robot is asleep, every motion tool answers `error: I am asleep; call wake_up first`.

## 😄 Recorded emotions

Clips come from the Hugging Face dataset `pollen-robotics/reachy-mini-emotions-library` (override with `emotions_dataset` in `Settings`). They play in a background thread so the answer isn't delayed. `sleep*`, `mini-deep-sleep` and `wake-mini-up` are filtered out: the app drives sleep and wake itself.

`after_reply` stores the name; `main.py` plays it once the reply has finished playing.

## 🔧 App-only helpers (not exposed to the model)

- `ensure_awake()` physically raises the head when a conversation starts, even if the robot was put to sleep from the dashboard.
- `go_to_sleep()` is also called by the app when a conversation ends.
- `clear_pending_emotion()` / `play_pending_emotion()` manage the `after_reply` queue.

## 📷 Camera tools (implemented, not registered)

- `describe_view(question)`: captures a frame and asks a vision-capable model about it, using a one-shot call so images never enter the chat history.
- `look_at_person()`: finds a person with a YOLO detector (`vision_local.py`, needs `ultralytics`) and turns the head towards them.

They are only registered when a vision function or detector is passed to `RobotTools`; `build_agent` currently passes neither. This is why `gpt-6.1-astra` (image input) was chosen for the future.

## ➕ Adding a tool

1. Add a method to `RobotTools` with `Annotated[..., Field(description=...)]` parameters and a docstring (the docstring becomes the tool description).
2. Validate and clamp inputs; return a short string.
3. Add it to the list in `as_tools()`.
4. Mention when to use it in `INSTRUCTIONS` ([agent](agent.md)).
5. Add a test in `reachy_foundry_agent/tests/`.
