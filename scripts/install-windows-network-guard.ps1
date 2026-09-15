[CmdletBinding(SupportsShouldProcess)]
param(
  [ValidateSet('Install','Uninstall','Pause','Resume','Status','CheckNow')]
  [string]$Mode = 'Status',
  [ValidateRange(1,65535)][int]$DefaultPort = 7890,
  [switch]$AllowExternalIpCheck
)

$ErrorActionPreference = 'Stop'
$taskName = 'FlClash Network Guard'
$installRoot = Join-Path $env:LOCALAPPDATA 'flclash-network-setup\network-guard'
$sourceCore = Join-Path $PSScriptRoot 'network-guard.py'
$targetCore = Join-Path $installRoot 'network-guard.py'
$configPath = Join-Path $installRoot 'config.json'
$statePath = Join-Path $installRoot 'state.json'
$pausedPath = Join-Path $installRoot 'paused.flag'

function Get-PythonCommand {
  $python = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $python) { throw 'Python 3 was not found. Install Python before enabling the network guard.' }
  $windowless = Join-Path (Split-Path $python.Source) 'pythonw.exe'
  [pscustomobject]@{
    Console = $python.Source
    Windowless = $(if (Test-Path -LiteralPath $windowless) { $windowless } else { $python.Source })
  }
}

function Write-GuardConfig {
  param([bool]$ExternalConsent)
  $config = [ordered]@{
    default_port = $DefaultPort
    external_check_consent = $ExternalConsent
    external_endpoint = 'https://ifconfig.co/json'
    local_interval_seconds = 20
    external_interval_seconds = 3600
    confirmations_required = 2
    state_path = $statePath
    paused_path = $pausedPath
  }
  $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
}

switch ($Mode) {
  'Install' {
    $python = Get-PythonCommand
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Copy-Item -LiteralPath $sourceCore -Destination $targetCore -Force
    Write-GuardConfig -ExternalConsent:$AllowExternalIpCheck.IsPresent
    $arguments = ('"{0}" run --config "{1}"' -f $targetCore, $configPath)
    $action = New-ScheduledTaskAction -Execute $python.Windowless -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Checks FlClash locally and shows actionable system notifications after repeated anomalies.' -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Output ('Installed and started. External IP checks: ' + $(if ($AllowExternalIpCheck) { 'CONSENTED' } else { 'DISABLED' }))
  }
  'Pause' {
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Set-Content -LiteralPath $pausedPath -Value 'paused' -Encoding ASCII
    Write-Output 'Paused. The scheduled task stays installed but performs no checks.'
  }
  'Resume' {
    Remove-Item -LiteralPath $pausedPath -Force -ErrorAction SilentlyContinue
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Start-ScheduledTask -TaskName $taskName }
    Write-Output 'Resumed.'
  }
  'CheckNow' {
    $python = Get-PythonCommand
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Network guard is not installed.' }
    & $python.Console $targetCore check --config $configPath --notify
    exit $LASTEXITCODE
  }
  'Status' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    [pscustomobject]@{
      Installed = [bool]$task
      TaskState = $(if ($task) { [string]$task.State } else { 'NotInstalled' })
      Paused = Test-Path -LiteralPath $pausedPath
      ExternalIpChecks = $(if (Test-Path -LiteralPath $configPath) { [bool]((Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).external_check_consent) } else { $false })
    } | ConvertTo-Json
  }
  'Uninstall' {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
      Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
      Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    if ((Test-Path -LiteralPath $installRoot) -and $installRoot.StartsWith($env:LOCALAPPDATA, [System.StringComparison]::OrdinalIgnoreCase)) {
      Remove-Item -LiteralPath $installRoot -Recurse -Force
    }
    Write-Output 'Uninstalled.'
  }
}
