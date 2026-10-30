# 🚚 Deploying to the robot

The app is a normal Reachy Mini Python app (entry point `reachy_mini_apps`). It is installed into the daemon's apps venv over SSH, no Hugging Face needed.

## 1️⃣ Credentials for a headless robot

On your dev machine `az login` is enough. The robot has no browser login, so give it a service principal:

```powershell
./scripts/create-robot-sp.ps1            # optional: -Name <displayName>
```

It creates the principal (without subscription roles), grants it *Foundry User* through `azd provision`, and appends `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` to `reachy_foundry_agent/.env`. Every run creates a fresh client secret.

## 2️⃣ Deploy

```bash
./scripts/deploy-to-robot.sh              # Linux / macOS / Git Bash
./scripts/deploy-to-robot.sh --restart    # also restart the daemon
```

```powershell
.\scripts\deploy-to-robot.ps1             # Windows (OpenSSH + tar built in)
.\scripts\deploy-to-robot.ps1 -Restart
.\scripts\deploy-to-robot.ps1 -NoEnv -RobotHost 192.168.1.50
```

What happens:

1. Source is packed (without `.venv`, tests, `.env`).
2. On the robot it is installed into `/venvs/apps_venv` with `uv` (the interpreter is repaired if missing and the same `reachy-mini` version as the daemon is ensured).
3. `.env` is copied to `~/.reachy_foundry.env` with mode 600.
4. Optionally the `reachy-mini-daemon` service is restarted.

Defaults can be overridden: `ROBOT_HOST` (`reachy-mini.local`), `ROBOT_USER` (`pollen`), `ROBOT_VENV`, `ROBOT_SERVICE`. The PowerShell version sends everything in one SSH connection (one password prompt); set up an SSH key to avoid prompts entirely:

```bash
ssh-copy-id pollen@reachy-mini.local
```

## 3️⃣ Start it

Open `http://reachy-mini.local:8000`, start **reachy_foundry_agent**. Reachy says it's ready, goes to sleep and waits for "Hey Reachy" ([details](wake-and-goodbye.md)).

## ⚙️ Configuration

Environment variables or `.env` / `~/.reachy_foundry.env` (never commit):

| Variable | Meaning |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint |
| `FOUNDRY_MODEL` | chat deployment name |
| `FOUNDRY_REASONING_EFFORT` | optional: `none` (default), `low`, `medium`, `high` or `default` ([models](models.md)) |
| `AZURE_SPEECH_ENDPOINT`, `AZURE_SPEECH_API_KEY` | Speech endpoint and key |
| `AZURE_SPEECH_LOCALE`, `AZURE_SPEECH_VOICE`, `AZURE_SPEECH_STT_MODEL` | see [models](models.md) |
| `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` | robot service principal |
| `REACHY_*` | wake/goodbye tuning, see [wake & goodbye](wake-and-goodbye.md) |

## 📜 Logs

The app logs to the daemon's log: every conversation event and tool call, with arguments and duration. On the robot:

```bash
journalctl -u reachy-mini-daemon -f
```

Idle speech is only logged as a word count unless `REACHY_DEBUG_GATE=1`.

## 🧪 Local development

```bash
cd reachy_foundry_agent
pip install -e ".[dev]"
pytest
```

The tests use a mocked robot and mocked Speech endpoints, so no hardware or Azure is needed.

## 🩺 Troubleshooting

- **App missing in the dashboard**: re-run the deploy script; it prints the registered entry points. Try `--restart`.
- **"Missing environment variables"**: the `.env` wasn't copied, run without `--no-env`.
- **Sign-in warnings in the log**: service principal variables are missing; run `create-robot-sp.ps1`.
- **"Hey Reachy" isn't heard while asleep**: lower `REACHY_IDLE_VAD_THRESHOLD`.
- **Head moves the wrong way**: the pitch sign convention (up = negative) is set in `robot_tools.py`; adjust if your hardware differs.
