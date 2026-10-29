<#
.SYNOPSIS
Deploy reachy_foundry_agent to a Reachy Mini Wireless over SSH (no Hugging Face needed).

.EXAMPLE
.\scripts\deploy-to-robot.ps1
.\scripts\deploy-to-robot.ps1 -Restart
.\scripts\deploy-to-robot.ps1 -NoEnv -RobotHost 192.168.1.50

.NOTES
Needs the Windows OpenSSH client (ssh) and tar, both built into Windows 10/11.

Everything (source, install script, .env) is streamed to the robot in ONE ssh connection, so a password login
asks for the password once. The service restart is not part of that: it only happens with -Restart, in a
separate ssh call (which asks again). To avoid all prompts, set up a key once:
  type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh pollen@reachy-mini.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
#>
[CmdletBinding()]
param(
    [string]$RobotHost    = $(if ($env:ROBOT_HOST) { $env:ROBOT_HOST } else { 'reachy-mini.local' }),
    [string]$RobotUser    = $(if ($env:ROBOT_USER) { $env:ROBOT_USER } else { 'pollen' }),
    # The apps venv the daemon scans for apps (repaired automatically if its interpreter is missing).
    [string]$RobotVenv    = $(if ($env:ROBOT_VENV) { $env:ROBOT_VENV } else { '/venvs/apps_venv' }),
    [string]$RobotService = $(if ($env:ROBOT_SERVICE) { $env:ROBOT_SERVICE } else { 'reachy-mini-daemon' }),
    [switch]$NoEnv,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$root    = Split-Path -Parent $PSScriptRoot
$appDir  = Join-Path $root 'reachy_foundry_agent'
$envFile = Join-Path $appDir '.env'
$remote  = "$RobotUser@$RobotHost"

$installScript = @'
set -euo pipefail
src="$DEPLOY_DIR"
meta="$src.deploy"
mv "$src/_deploy" "$meta"   # keep the deploy files out of the package that gets installed
trap 'rm -rf "$src" "$meta"' EXIT
export PATH="$PATH:/opt/uv"
venv="$ROBOT_VENV"
daemon_py=/venvs/mini_daemon/bin/python
py="$venv/bin/python"
echo "apps venv: $venv"

# The daemon lists apps by running $venv/bin/python; repair the interpreter if it is missing
# (existing site-packages are kept).
if [ ! -x "$py" ]; then
  echo "interpreter missing in $venv; re-creating it (packages are kept)"
  base="$(readlink -f "$daemon_py")"
  uv venv --allow-existing --python "$base" "$venv"
fi
# Same SDK version as the daemon, like the daemon's own pre-install step.
if ! "$py" -c "import reachy_mini" 2>/dev/null; then
  ver="$("$daemon_py" -c 'import importlib.metadata as m; print(m.version("reachy_mini"))')"
  uv pip install --python "$py" "reachy-mini==$ver"
fi
uv pip install --python "$py" --reinstall-package reachy_foundry_agent "$src"

# Earlier versions of this script installed into the daemon's own venv by mistake.
if "$daemon_py" -m pip show reachy_foundry_agent >/dev/null 2>&1; then
  echo "removing stray reachy_foundry_agent from the daemon venv"
  "$daemon_py" -m pip uninstall -y reachy_foundry_agent
fi
"$py" -c "from importlib.metadata import entry_points; print('entry points:', [e.name for e in entry_points(group='reachy_mini_apps')])"

if [ -f "$meta/env" ]; then
  echo "==> Copying .env to ~/.reachy_foundry.env"
  install -m 600 "$meta/env" "$HOME/.reachy_foundry.env"
fi
'@

if (-not (Test-Path (Join-Path $appDir 'pyproject.toml'))) { throw "pyproject.toml not found in $appDir" }

$stage   = Join-Path ([IO.Path]::GetTempPath()) "reachy_deploy_$([guid]::NewGuid().ToString('N'))"
$payload = "$stage.tar"
try {
    Write-Host '==> Packing source'
    New-Item -ItemType Directory -Path (Join-Path $stage '_deploy') -Force | Out-Null
    # LF line endings, no BOM, so bash on the robot does not choke.
    [IO.File]::WriteAllText((Join-Path $stage '_deploy/run.sh'), ($installScript -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    if (-not $NoEnv) {
        if (Test-Path $envFile) { Copy-Item $envFile (Join-Path $stage '_deploy/env') }
        else { Write-Warning "$envFile not found (run 'azd provision' or scripts\write_env.py); skipping env copy" }
    }
    Invoke-Native tar @(
        '-cf', $payload,
        '--exclude=.venv', '--exclude=build', '--exclude=*.egg-info', '--exclude=__pycache__',
        '--exclude=.pytest_cache', '--exclude=.env', '--exclude=tests',
        '-C', $appDir, '.',
        '-C', $stage, '_deploy'
    )

    Write-Host "==> Deploying to $remote (one connection)"
    # The remote command has no double quotes, so it survives Start-Process argument joining.
    $remoteCmd = 'd=$(mktemp -d) && tar -C $d -xf - && exec env ' +
        "ROBOT_VENV=$RobotVenv " +
        'DEPLOY_DIR=$d bash $d/_deploy/run.sh'
    # Start-Process feeds the tar to stdin byte-for-byte (a PowerShell pipe would corrupt it); ssh still
    # prompts for the password on the console.
    $p = Start-Process ssh -ArgumentList @('-o', 'ConnectTimeout=10', $remote, "`"$remoteCmd`"") `
        -RedirectStandardInput $payload -NoNewWindow -Wait -PassThru
    $null = $p.Handle  # keeps ExitCode available after -Wait
    $code = $p.ExitCode
}
finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $payload -Force -ErrorAction SilentlyContinue
}

if ($code -ne 0) { throw "Remote deploy failed with exit code $code" }

# Optional and separate from the deploy: it opens its own connection (and may ask for the sudo password).
if ($Restart) {
    Write-Host "==> Restarting $RobotService"
    Invoke-Native ssh @('-t', $remote, "sudo systemctl restart '$RobotService'")
}

Write-Host "Done. Open http://${RobotHost}:8000 and start 'reachy_foundry_agent' from the dashboard."
