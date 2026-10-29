# ☁️ Infrastructure

Bicep in `infra/`, deployed with the Azure Developer CLI. Only infrastructure is deployed; the app itself runs on the robot (`azure.yaml` has no services).

```bash
azd auth login
azd up        # asks for environment name, subscription and region
```

Prerequisites: `azd`, Azure CLI (`az login`), Python 3 (for the `.env` hook), and quota for the chosen model in your region.

## 🧱 What gets created (resource group `rg-<env>`)

| Resource | Notes |
|---|---|
| Foundry resource (`Microsoft.CognitiveServices/accounts`, kind `AIServices`) | Also provides Azure Speech (STT/TTS), no separate deployment |
| Foundry project `reachy` | `.../accounts/projects` |
| Chat model deployment | default `gpt-5.4-mini`, `GlobalStandard`, 50K TPM |
| Role assignment | *Azure AI User* ("Foundry User") on the Foundry resource, for you and optionally the robot's service principal |

Files: `main.bicep` (subscription scope), `foundry.bicep`, `main.parameters.json` (maps `azd env` values to parameters).

## 📝 The `.env` hook

After provisioning, `scripts/write_env.py` writes `reachy_foundry_agent/.env` (git-ignored): project endpoint, model, Speech endpoint and key. The Speech key is read with the Azure CLI, never stored as an azd output. Credentials of a robot service principal already in the file are preserved on re-provisioning.

## 🎛️ Parameters

Set with `azd env set NAME value`, then `azd provision`:

`CHAT_MODEL_NAME`, `CHAT_MODEL_VERSION`, `CHAT_SKU_NAME`, `CHAT_CAPACITY`, `ROBOT_PRINCIPAL_ID`. See [models](models.md).

## 🔐 Security notes

- The Speech key lives only in the git-ignored `.env` and in `~/.reachy_foundry.env` on the robot (mode 600).
- The robot's service principal gets **no subscription roles**, only the resource-scoped Foundry User role.
- The Foundry resource keeps local auth enabled only for Speech REST; model calls use Entra ID.

## 🧹 Clean up

```bash
azd down --purge
```
