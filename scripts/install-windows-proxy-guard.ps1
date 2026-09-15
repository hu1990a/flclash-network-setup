[CmdletBinding(SupportsShouldProcess)]
param(
  [ValidateSet('Install','Verify')][string]$Mode = 'Install',
  [ValidateRange(1,65535)][int]$DefaultPort = 7890,
  [string]$CliTimeZone = 'America/Los_Angeles',
  [string[]]$ProfilePath
)

$ErrorActionPreference = 'Stop'
$beginMarker = '# === flclash-skill windows env begin ==='
$endMarker = '# === flclash-skill windows env end ==='

function Get-DefaultProfilePaths {
  $documents = [Environment]::GetFolderPath('MyDocuments')
  @(
    (Join-Path $documents 'WindowsPowerShell\profile.ps1')
    (Join-Path $documents 'PowerShell\profile.ps1')
  )
}

function New-GuardBlock([int]$fallbackPort,[string]$timeZone) {
  $safeTimeZone = $timeZone.Replace("'", "''")
  @"
$beginMarker
`$global:FlClashProxyForcedOff = `$false
`$global:FlClashProxyDefaultPort = $fallbackPort

function Get-FlClashProxyPort {
  `$candidates = [System.Collections.Generic.List[int]]::new()
  if (`$env:FLCLASH_PORT -match '^\d+$') { `$candidates.Add([int]`$env:FLCLASH_PORT) }

  `$root = Join-Path `$env:APPDATA 'com.follow\clash'
  `$prefsPath = Join-Path `$root 'shared_preferences.json'
  if (Test-Path -LiteralPath `$prefsPath) {
    try {
      `$outer = Get-Content -LiteralPath `$prefsPath -Raw | ConvertFrom-Json
      `$configValue = `$outer.'flutter.config'
      `$config = if (`$configValue -is [string]) { `$configValue | ConvertFrom-Json } else { `$configValue }
      `$mixedPort = `$config.patchClashConfig.'mixed-port'
      if (`$mixedPort -match '^\d+$') { `$candidates.Add([int]`$mixedPort) }

      `$profileId = [string]`$config.currentProfileId
      if (`$profileId) {
        `$activeProfile = Join-Path (Join-Path `$root 'profiles') (`$profileId + '.yaml')
        if (Test-Path -LiteralPath `$activeProfile) {
          `$line = Select-String -LiteralPath `$activeProfile -Pattern '^mixed-port:\s*(\d+)\s*$' | Select-Object -First 1
          if (`$line) { `$candidates.Add([int]`$line.Matches[0].Groups[1].Value) }
        }
      }
    } catch {
      # A malformed preference file is handled by the fail-closed check below.
    }
  }

  # Do not trust the fallback alone: an unrelated program may listen on that port.
  # Protected CLIs require a port confirmed by FlClash state or explicit FLCLASH_PORT.
  `$valid = `$candidates | Where-Object { `$_ -ge 1 -and `$_ -le 65535 } | Select-Object -First 1
  if (`$null -eq `$valid) { return `$null }
  return [int]`$valid
}

function Test-FlClashProxyPort([int]`$Port) {
  if (`$Port -lt 1 -or `$Port -gt 65535) { return `$false }
  `$client = [System.Net.Sockets.TcpClient]::new()
  try {
    `$pending = `$client.BeginConnect('127.0.0.1', `$Port, `$null, `$null)
    if (-not `$pending.AsyncWaitHandle.WaitOne(800, `$false)) { return `$false }
    `$client.EndConnect(`$pending)
    return `$true
  } catch {
    return `$false
  } finally {
    `$client.Dispose()
  }
}

function Clear-FlClashProxyEnvironment {
  'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy' |
    ForEach-Object { Remove-Item -Path ('Env:' + `$_) -ErrorAction SilentlyContinue }
}

function Set-FlClashProxyEnvironment([int]`$Port) {
  `$http = "http://127.0.0.1:`$Port"
  `$socks = "socks5://127.0.0.1:`$Port"
  `$env:HTTP_PROXY = `$http
  `$env:HTTPS_PROXY = `$http
  `$env:ALL_PROXY = `$socks
  `$env:http_proxy = `$http
  `$env:https_proxy = `$http
  `$env:all_proxy = `$socks
}

function Test-FlClashProxyConfirmed {
  if (`$global:FlClashProxyForcedOff) { return `$false }
  `$port = Get-FlClashProxyPort
  if (-not `$port -or -not (Test-FlClashProxyPort `$port)) { return `$false }
  `$expected = "http://127.0.0.1:`$port"
  if (`$env:HTTP_PROXY -ne `$expected -or `$env:HTTPS_PROXY -ne `$expected) {
    Set-FlClashProxyEnvironment `$port
  }
  return (`$env:HTTP_PROXY -eq `$expected -and `$env:HTTPS_PROXY -eq `$expected)
}

function proxy_on {
  `$global:FlClashProxyForcedOff = `$false
  `$port = Get-FlClashProxyPort
  if (-not `$port -or -not (Test-FlClashProxyPort `$port)) {
    Clear-FlClashProxyEnvironment
    throw '[flclash-network-setup] FAIL-CLOSED: cannot confirm a listening FlClash proxy port.'
  }
  Set-FlClashProxyEnvironment `$port
  Write-Output ("FlClash proxy enabled on 127.0.0.1:{0}" -f `$port)
}

function proxy_off {
  `$global:FlClashProxyForcedOff = `$true
  Clear-FlClashProxyEnvironment
  Write-Output 'FlClash proxy disabled for this PowerShell session.'
}

function Resolve-FlClashProtectedCli([string]`$Name) {
  return Get-Command `$Name -All -ErrorAction SilentlyContinue |
    Where-Object { `$_.CommandType -in @('Application','ExternalScript') } |
    Select-Object -First 1
}

function Invoke-FlClashProtectedCli([string]`$Name,[object[]]`$Arguments) {
  if (-not (Test-FlClashProxyConfirmed)) {
    Clear-FlClashProxyEnvironment
    throw ("[flclash-network-setup] FAIL-CLOSED: cannot confirm proxy for {0}; command was not started. Start FlClash and run proxy_on." -f `$Name)
  }
  `$command = Resolve-FlClashProtectedCli `$Name
  if (-not `$command) { throw ("Executable not found: {0}" -f `$Name) }
  & `$command.Source @Arguments
  if (`$LASTEXITCODE -ne 0) { `$global:LASTEXITCODE = `$LASTEXITCODE }
}

function claude { Invoke-FlClashProtectedCli 'claude' `$args }
function codex { Invoke-FlClashProtectedCli 'codex' `$args }

`$env:TZ = '$safeTimeZone'
`$env:ANTHROPIC_BASE_URL = 'https://api.anthropic.com'
`$env:OPENAI_BASE_URL = 'https://api.openai.com'
`$startupPort = Get-FlClashProxyPort
if (`$startupPort -and (Test-FlClashProxyPort `$startupPort)) {
  Set-FlClashProxyEnvironment `$startupPort
} else {
  Clear-FlClashProxyEnvironment
}
$endMarker
"@
}

function Install-Guard([string]$target,[string]$block) {
  $parent = Split-Path -Parent $target
  if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  $existing = if (Test-Path -LiteralPath $target) { Get-Content -LiteralPath $target -Raw } else { '' }
  $pattern = '(?s)' + [regex]::Escape($beginMarker) + '.*?' + [regex]::Escape($endMarker)
  $updated = if ($existing -match $pattern) {
    [regex]::Replace($existing,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block },1)
  } else {
    ($existing.TrimEnd() + "`r`n`r`n" + $block + "`r`n").TrimStart("`r","`n")
  }
  if ($updated -eq $existing) { Write-Output "UNCHANGED $target"; return }
  if (Test-Path -LiteralPath $target) {
    $backup = $target + '.bak.' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    Copy-Item -LiteralPath $target -Destination $backup
    Write-Output "BACKUP $backup"
  }
  Set-Content -LiteralPath $target -Value $updated -Encoding UTF8
  Write-Output "INSTALLED $target"
}

$targets = if ($ProfilePath) { @($ProfilePath) } else { @(Get-DefaultProfilePaths) }
$block = New-GuardBlock $DefaultPort $CliTimeZone

if ($Mode -eq 'Install') {
  foreach ($target in $targets) {
    if ($PSCmdlet.ShouldProcess($target,'install or update FlClash proxy guard')) { Install-Guard $target $block }
  }
  exit 0
}

$failed = $false
foreach ($target in $targets) {
  if (-not (Test-Path -LiteralPath $target)) { Write-Output "FAIL missing $target"; $failed = $true; continue }
  $text = Get-Content -LiteralPath $target -Raw
  if ($text.Contains($beginMarker) -and $text.Contains($endMarker)) { Write-Output "PASS $target" }
  else { Write-Output "FAIL guard markers missing $target"; $failed = $true }
}
if ($failed) { exit 2 }
exit 0
