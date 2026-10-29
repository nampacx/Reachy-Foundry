# Creates the robot's service principal, grants it Foundry User via azd, and appends its
# credentials to reachy_foundry_agent/.env. Run from the repo root after `azd up`.
param(
    [string]$Name = 'reachy-robot'
)
$ErrorActionPreference = 'Stop'

$sp = az ad sp create-for-rbac -n $Name -o json | ConvertFrom-Json   # no --role: no subscription rights
$objectId = az ad sp show --id $sp.appId --query id -o tsv

azd env set ROBOT_PRINCIPAL_ID $objectId
azd provision --no-prompt                                            # assigns Foundry User, rewrites .env

$envFile = Join-Path $PSScriptRoot '..\reachy_foundry_agent\.env'
$lines = @(Get-Content $envFile | Where-Object { $_ -notmatch '^#?\s*AZURE_(TENANT_ID|CLIENT_ID|CLIENT_SECRET)=' })
$lines += "AZURE_TENANT_ID=$($sp.tenant)", "AZURE_CLIENT_ID=$($sp.appId)", "AZURE_CLIENT_SECRET=$($sp.password)"
Set-Content -Path $envFile -Value $lines
Write-Host "Robot credentials written to $envFile"
