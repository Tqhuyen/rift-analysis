# Register a Windows Scheduled Task that snapshots Rift Report every N minutes.
# Run from an elevated or normal PowerShell in the repo:
#   powershell -ExecutionPolicy Bypass -File scripts\install-snapshot-task.ps1
# Remove with:
#   Unregister-ScheduledTask -TaskName "RiftReportSnapshot" -Confirm:$false

param(
  [int]$IntervalMinutes = 30,
  [string]$TaskName = "RiftReportSnapshot"
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$script = Join-Path $repo "snapshot.py"

if (-not (Test-Path $script)) {
  throw "snapshot.py not found at $script"
}

$action = New-ScheduledTaskAction `
  -Execute $python `
  -Argument "`"$script`" --quiet" `
  -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger `
  -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Rift Report: snapshot ARAM Mayhem stats while the League client is open." `
  -Force | Out-Null

Write-Host "Registered '$TaskName' every $IntervalMinutes minute(s)."
Write-Host "Python : $python"
Write-Host "Script : $script"
Write-Host "Snapshots: $(Join-Path $repo 'snapshots')"
