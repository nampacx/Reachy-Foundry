# 🧠 The agent

Built in `agent.py` with the [Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/):

```python
client = FoundryChatClient(
    project_endpoint=settings.foundry_project_endpoint,
    model=settings.foundry_model,
    credential=DefaultAzureCredential(),
)
agent = Agent(client=client, name="Reachy", instructions=INSTRUCTIONS, tools=robot.as_tools())
```

`DefaultAzureCredential` picks up the service principal from the environment on the robot, or `az login` on your dev machine.

## 🎭 Persona (instructions)

Reachy is a small, curious, friendly desktop robot. The instructions tell it to:

- keep replies to **one to three sentences**, no markdown, lists or emoji (it is spoken aloud)
- greet the person, **ask for their name**, remember it and use it now and then
- use its body: nod to agree, shake for no, wiggle antennas, `move_head` when asked to look somewhere
- play a **recorded emotion** (`play_emotion`) for bigger moments, at most one per reply
  - `when="now"` for greetings, thanks, dancing
  - `when="after_reply"` for reactions to what it just said, such as laughing after a joke
- say goodnight and call `go_to_sleep` when asked to rest, and only react to waking up while asleep
- **not** narrate tool calls, and say briefly if a tool fails
- admit it **cannot see** (the camera is not wired in yet)

The emotion names listed in the instructions match the Pollen emotions library; if none fits the model can call `list_emotions`.

## 💬 Sessions

A fresh `AgentSession` is created every time a conversation starts (`agent.create_session()`), and dropped when it ends. Context, including the user's name, never leaks from one conversation into the next.

## 👋 A bare wake phrase

If the user only says "Hey Reachy", the app sends a bracketed hint instead of an empty message so the model greets them. If they say "Hey Reachy, what time is it", the part after the wake phrase is sent as-is.

## ✏️ Changing the personality

Edit `INSTRUCTIONS` in `agent.py`, then redeploy ([deployment](deployment.md)). If you add tools, also mention them there so the model knows when to use them.
