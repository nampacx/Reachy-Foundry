"""azd postprovision hook: write reachy_foundry_agent/.env from the azd environment.

The Speech key is fetched with the Azure CLI (it is a secret, so it is never an azd output).
The resulting .env is git-ignored; copy it to the robot as ~/.reachy_foundry.env.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    env = os.environ
    account, rg = env.get("FOUNDRY_ACCOUNT_NAME"), env.get("AZURE_RESOURCE_GROUP")
    if not account or not rg:
        print("write_env: azd outputs missing; skipping .env", file=sys.stderr)
        return 0
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        print("write_env: Azure CLI not found; skipping .env", file=sys.stderr)
        return 0
    key = subprocess.run(
        [az, "cognitiveservices", "account", "keys", "list", "-n", account, "-g", rg,
         "--query", "key1", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if key.returncode != 0:
        print(f"write_env: could not read Speech key: {key.stderr.strip()}", file=sys.stderr)
        return 0

    lines = [
        f"FOUNDRY_PROJECT_ENDPOINT={env['FOUNDRY_PROJECT_ENDPOINT']}",
        f"FOUNDRY_MODEL={env['FOUNDRY_MODEL']}",
        *([f"# A/B test: swap in the second deployment\n# FOUNDRY_MODEL={env['FOUNDRY_ALT_MODEL']}"]
          if env.get("FOUNDRY_ALT_MODEL") else []),
        f"AZURE_SPEECH_ENDPOINT={env['AZURE_SPEECH_ENDPOINT']}",
        f"AZURE_SPEECH_API_KEY={key.stdout.strip()}",
    ]
    target = Path(__file__).resolve().parent.parent / "reachy_foundry_agent" / ".env"
    # Keep the robot's service principal credentials (added by create-robot-sp.ps1) across re-provisioning.
    kept = []
    if target.is_file():
        kept = [
            l for l in target.read_text(encoding="utf-8").splitlines()
            if l.startswith(
                ("AZURE_TENANT_ID=", "AZURE_CLIENT_ID=", "AZURE_CLIENT_SECRET=", "FOUNDRY_REASONING_EFFORT=")
            )
        ]
    lines += kept or [
        "# Robot (headless) auth: run scripts/create-robot-sp.ps1 to add a service principal",
        "# AZURE_TENANT_ID=",
        "# AZURE_CLIENT_ID=",
        "# AZURE_CLIENT_SECRET=",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"write_env: wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
