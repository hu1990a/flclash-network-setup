[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'FlClash Network Guard'
$installRoot = Join-Path $env:LOCALAPPDATA 'flclash-network-setup\network-guard'
$startupLauncher = Join-Path ([Environment]::GetFolderPath('Startup')) 'FlClash Network Guard.vbs'
$stoppedProcesses = 0
$processInspection = 'Available'

try {
  $legacyProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
      Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and
        $_.CommandLine -and
        $_.CommandLine.Contains((Join-Path $installRoot 'network-guard.py'), [System.StringComparison]::OrdinalIgnoreCase)
      }
  )
  foreach ($process in $legacyProcesses) {
    if ($PSCmdlet.ShouldProcess("PID $($process.ProcessId)", 'Stop legacy FlClash network guard')) {
      Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
      $stoppedProcesses++
    }
  }
} catch {
  $processInspection = 'Unavailable'
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task -and $PSCmdlet.ShouldProcess($taskName, 'Remove legacy scheduled task')) {
  Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ((Test-Path -LiteralPath $startupLauncher) -and $PSCmdlet.ShouldProcess($startupLauncher, 'Remove legacy startup entry')) {
  Remove-Item -LiteralPath $startupLauncher -Force
}

$expectedRoot = Join-Path $env:LOCALAPPDATA 'flclash-network-setup\network-guard'
if ((Test-Path -LiteralPath $installRoot) -and $installRoot.Equals($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  if ($PSCmdlet.ShouldProcess($installRoot, 'Remove legacy guard files')) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
  }
}

[pscustomobject]@{
  RemovedScheduledTask = -not [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
  RemovedStartupEntry = -not (Test-Path -LiteralPath $startupLauncher)
  RemovedInstallDirectory = -not (Test-Path -LiteralPath $installRoot)
  StoppedProcesses = $stoppedProcesses
  ProcessInspection = $processInspection
} | ConvertTo-Json
