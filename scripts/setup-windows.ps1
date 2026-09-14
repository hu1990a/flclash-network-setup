[CmdletBinding(SupportsShouldProcess)]
param(
  [ValidateSet('Audit','Apply','Verify')][string]$Mode = 'Audit',
  [string[]]$ProfilePath,
  [switch]$AllProfiles,
  [Alias('TimeZone')][string]$CliTimeZone,
  [string]$ProxyTimeZone,
  [int]$Port = 0,
  [string[]]$AdapterName,
  [switch]$UsesMobileHotspot,
  [switch]$InstallIpcheck,
  [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$script:Results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Step,[string]$Status,[string]$Detail) {
  $script:Results.Add([pscustomobject]@{Step=$Step;Status=$Status;Detail=$Detail})
}

function Test-Admin {
  $id=[Security.Principal.WindowsIdentity]::GetCurrent()
  $p=[Security.Principal.WindowsPrincipal]::new($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FlClashState {
  $root=Join-Path $env:APPDATA 'com.follow\clash'
  if(-not (Test-Path -LiteralPath $root)){ throw 'FlClash data directory not found.' }
  $prefsPath=Join-Path $root 'shared_preferences.json'
  $currentId=$null; $detectedPort=7890; $tun=$null; $systemProxy=$null
  if(Test-Path -LiteralPath $prefsPath){
    $outer=Get-Content -LiteralPath $prefsPath -Raw | ConvertFrom-Json
    if($outer.'flutter.config'){
      $cfg=$outer.'flutter.config' | ConvertFrom-Json
      $currentId=[string]$cfg.currentProfileId
      if($cfg.patchClashConfig.'mixed-port'){ $detectedPort=[int]$cfg.patchClashConfig.'mixed-port' }
      $tun=[bool]$cfg.vpnProps.enable
      $systemProxy=[bool]$cfg.networkProps.systemProxy
    }
  }
  $profile=$null
  if($currentId){
    $candidate=Join-Path (Join-Path $root 'profiles') ($currentId + '.yaml')
    if(Test-Path -LiteralPath $candidate){ $profile=$candidate }
  }
  if(-not $profile){
    $profile=Get-ChildItem -LiteralPath (Join-Path $root 'profiles') -Filter '*.yaml' -File |
      Where-Object { Select-String -LiteralPath $_.FullName -Pattern '^proxies:\s*$' -Quiet } |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
  }
  $profiles=@(Get-ChildItem -LiteralPath (Join-Path $root 'profiles') -Filter '*.yaml' -File |
    Where-Object { Select-String -LiteralPath $_.FullName -Pattern '^proxies:\s*$' -Quiet } |
    Select-Object -ExpandProperty FullName)
  [pscustomobject]@{Root=$root;Profile=$profile;Profiles=$profiles;ProfileId=$currentId;Port=$detectedPort;Tun=$tun;SystemProxy=$systemProxy}
}

function Select-TimeZone {
  if($CliTimeZone){ return $CliTimeZone }
  if($NonInteractive){
    if($ProxyTimeZone){ return $ProxyTimeZone }
    throw 'NonInteractive mode requires -CliTimeZone or -ProxyTimeZone after the exit timezone is detected.'
  }
  Write-Host 'Choose the CLI timezone mode before TZ is written.'
  Write-Host 'This sets the user TZ variable for new terminals and CLI tools only.'
  Write-Host 'It does not change the Windows clock, calendar, or system timezone.'
  Write-Host '1 Fixed 12 hours behind Beijing: America/Puerto_Rico (UTC-4, no DST). Easy for human time conversion, but it may conflict with the proxy exit.'
  Write-Host '2 Match the current or recommended proxy exit. Choice 2 is recommended to reduce location/timezone conflicts and follow local DST.'
  $choice=Read-Host 'Enter 1 or 2; Enter = 2'
  if([string]::IsNullOrWhiteSpace($choice)){ $choice='2' }
  if($choice -eq '1'){ return 'America/Puerto_Rico' }
  if($choice -eq '2'){
    if($ProxyTimeZone){ return $ProxyTimeZone }
    $detected=Read-Host 'Enter the detected proxy IANA timezone, for example America/Los_Angeles'
    if([string]::IsNullOrWhiteSpace($detected)){ throw 'Proxy IANA timezone is required for choice 2.' }
    return $detected
  }
  throw 'Timezone choice must be 1 or 2.'
}

function Get-PhysicalAdapters {
  if($AdapterName){
    return $AdapterName | ForEach-Object { Get-NetAdapter -Name $_ -ErrorAction Stop }
  }
  return Get-NetAdapter -Physical -ErrorAction Stop | Where-Object Status -eq 'Up'
}

function Show-SafeAudit($state) {
  Add-Result 'FlClash' 'PASS' ('Detected; active profile ' + (Split-Path $state.Profile -Leaf))
  Add-Result 'Profiles' 'INFO' ("Detected {0}" -f @($state.Profiles).Count)
  Add-Result 'Proxy port' 'INFO' ([string]$state.Port)
  Add-Result 'System proxy' $(if($state.SystemProxy){'PASS'}else{'PENDING'}) ([string]$state.SystemProxy)
  Add-Result 'TUN' $(if($state.Tun){'PASS'}else{'PENDING'}) ([string]$state.Tun)
  try {
    $bindings=Get-PhysicalAdapters | ForEach-Object { Get-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 }
    $enabled=@($bindings | Where-Object Enabled)
    Add-Result 'Physical adapter IPv6' $(if($enabled.Count -eq 0){'PASS'}else{'PENDING'}) ("Enabled {0} / checked {1}" -f $enabled.Count,@($bindings).Count)
  } catch { Add-Result 'Physical adapter IPv6' 'UNKNOWN' 'Unable to read adapter bindings with current permissions' }
}

function Apply-Profile([string]$target,[int]$chosenPort) {
  if(-not $target){ throw 'No subscription profile was selected.' }
  $tool=Join-Path $PSScriptRoot 'replace-config.py'
  $dry=& python $tool $target --port $chosenPort --dry-run
  if($LASTEXITCODE -ne 0){ throw ('Profile dry-run failed: ' + ($dry -join ' ')) }
  if($PSCmdlet.ShouldProcess((Split-Path $target -Leaf),'backup and optimize profile')){
    $result=& python $tool $target --port $chosenPort
    if($LASTEXITCODE -ne 0){ throw ('Profile update failed: ' + ($result -join ' ')) }
    $safe=$result -join "`n" | ConvertFrom-Json
    Add-Result 'Profile config' 'PASS' ("Backup created; proxies {0}, groups {1}, rules {2}" -f $safe.proxy_entries,$safe.group_entries,$safe.rule_entries)
  }
}

function Apply-Environment([string]$tz,[int]$chosenPort) {
  $vars=@{
    TZ=$tz; HTTP_PROXY="http://127.0.0.1:$chosenPort"; HTTPS_PROXY="http://127.0.0.1:$chosenPort";
    ALL_PROXY="socks5://127.0.0.1:$chosenPort"; ANTHROPIC_BASE_URL='https://api.anthropic.com';
    OPENAI_BASE_URL='https://api.openai.com'
  }
  foreach($item in $vars.GetEnumerator()){
    if($PSCmdlet.ShouldProcess(('user environment ' + $item.Key),'set')){
      [Environment]::SetEnvironmentVariable($item.Key,$item.Value,'User')
      Set-Item -Path ('Env:' + $item.Key) -Value $item.Value
    }
  }
  Add-Result 'Proxy and CLI environment' 'PASS' ('Set; port ' + $chosenPort + ', TZ ' + $tz)
}

function Apply-IPv6 {
  $adapters=@(Get-PhysicalAdapters)
  if($adapters.Count -eq 0){ Add-Result 'Physical adapter IPv6' 'UNKNOWN' 'No active physical adapter detected'; return }
  $enabled=@($adapters | ForEach-Object { Get-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 } | Where-Object Enabled)
  if($enabled.Count -eq 0){ Add-Result 'Physical adapter IPv6' 'PASS' ("Already disabled on {0} active physical adapters" -f $adapters.Count); return }
  if(-not (Test-Admin)){
    Add-Result 'Physical adapter IPv6' 'PENDING' 'Rerun Apply in Administrator PowerShell; active physical adapters only'
    return
  }
  foreach($adapter in $adapters){
    if($PSCmdlet.ShouldProcess($adapter.Name,'disable IPv6 binding')){
      Disable-NetAdapterBinding -Name $adapter.Name -ComponentID ms_tcpip6 | Out-Null
    }
  }
  $stillEnabled=@($adapters | ForEach-Object { Get-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 } | Where-Object Enabled)
  Add-Result 'Physical adapter IPv6' $(if($stillEnabled.Count -eq 0){'PASS'}else{'FAIL'}) ("Checked {0} active physical adapters" -f $adapters.Count)
}

function Ensure-PythonUserScriptsPath {
  $scripts=(& python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))").Trim()
  $userPath=[Environment]::GetEnvironmentVariable('Path','User')
  $parts=@($userPath -split ';' | Where-Object { $_ })
  if($parts -notcontains $scripts){
    [Environment]::SetEnvironmentVariable('Path',(($parts + $scripts) -join ';'),'User')
  }
  if(($env:Path -split ';') -notcontains $scripts){ $env:Path=$env:Path + ';' + $scripts }
}

function Install-Or-CheckIpcheck {
  Ensure-PythonUserScriptsPath
  $cmd=Get-Command ipcheck -ErrorAction SilentlyContinue
  if(-not $cmd -and -not $InstallIpcheck){ Add-Result 'ipcheck' 'PENDING' 'Not installed; add -InstallIpcheck after dependency install approval'; return }
  if(-not $cmd -and $PSCmdlet.ShouldProcess('current user Python environment','install or upgrade ai-ipcheck')){
    & python -m pip install --user --upgrade ai-ipcheck
    if($LASTEXITCODE -ne 0){ Add-Result 'ipcheck' 'FAIL' 'Install failed'; return }
  }
  Ensure-PythonUserScriptsPath
  $cmd=Get-Command ipcheck -ErrorAction SilentlyContinue
  Add-Result 'ipcheck' $(if($cmd){'PASS'}else{'FAIL'}) $(if($cmd){'Installed and available on user PATH'}else{'Installed but executable not found'})
}

function Verify-State($state,[int]$chosenPort) {
  $expected=@{HTTP_PROXY="http://127.0.0.1:$chosenPort";HTTPS_PROXY="http://127.0.0.1:$chosenPort";ALL_PROXY="socks5://127.0.0.1:$chosenPort";ANTHROPIC_BASE_URL='https://api.anthropic.com';OPENAI_BASE_URL='https://api.openai.com'}
  $bad=@($expected.GetEnumerator() | Where-Object { [Environment]::GetEnvironmentVariable($_.Key,'User') -ne $_.Value })
  Add-Result 'Environment verification' $(if($bad.Count -eq 0){'PASS'}else{'FAIL'}) $(if($bad.Count -eq 0){'Proxy and API variables match'}else{'Mismatched names: ' + (($bad | ForEach-Object Key) -join ', ')})
  $userTz=[Environment]::GetEnvironmentVariable('TZ','User')
  $tzPass=if($CliTimeZone){$userTz -eq $CliTimeZone}else{-not [string]::IsNullOrWhiteSpace($userTz)}
  Add-Result 'CLI timezone (TZ only)' $(if($tzPass){'PASS'}else{'FAIL'}) $(if($userTz){$userTz + '; new terminals/CLI only; Windows clock unchanged'}else{'Not set'})
  Add-Result 'System timezone' 'NOT_APPLICABLE' 'Unchanged by this workflow'
  try {
    $answers=@(Resolve-DnsName 'www.cloudflare.com' -Type A -DnsOnly -ErrorAction Stop | Select-Object -ExpandProperty IPAddress)
    $fake=@($answers | Where-Object { $_ -like '198.18.*' })
    Add-Result 'fake-IP DNS' $(if($fake.Count -gt 0){'PASS'}else{'FAIL'}) $(if($fake.Count -gt 0){'Returned 198.18.x.x'}else{'Did not return 198.18.x.x'})
  } catch { Add-Result 'fake-IP DNS' 'FAIL' 'DNS query failed' }
  $listening=(netstat -ano -p tcp | Select-String -Pattern (':' + $chosenPort + '\s+.*LISTENING'))
  Add-Result 'Proxy port' $(if($listening){'PASS'}else{'FAIL'}) $(if($listening){'Listening'}else{'Not listening'})
  Ensure-PythonUserScriptsPath
  if(Get-Command ipcheck -ErrorAction SilentlyContinue){
    Add-Result 'ipcheck test' 'READY' 'Run ipcheck locally; redact the public IP in reports'
  } else { Add-Result 'ipcheck test' 'PENDING' 'Not installed' }
}

$state=Get-FlClashState
$chosenPort=if($Port -gt 0){$Port}else{$state.Port}
Show-SafeAudit $state

if($Mode -eq 'Apply'){
  $tz=Select-TimeZone
  $targets=if($ProfilePath){@($ProfilePath)}elseif($AllProfiles){@($state.Profiles)}else{@($state.Profile)}
  foreach($target in $targets){ Apply-Profile $target $chosenPort }
  Apply-Environment $tz $chosenPort
  Apply-IPv6
  Install-Or-CheckIpcheck
  if($UsesMobileHotspot){ Add-Result 'Mobile hotspot' 'PENDING' 'Set the phone APN protocol to IPv4, then reconnect the hotspot' }
  else { Add-Result 'Mobile hotspot' 'NOT_APPLICABLE' 'Not selected' }
  if(-not $state.Tun){ Add-Result 'TUN' 'PENDING' 'Enable TUN in FlClash and approve the helper service if prompted' }
  if(Get-Process FlClash -ErrorAction SilentlyContinue){ Add-Result 'Load config' 'PENDING' 'Fully quit FlClash from the tray and reopen it; do not refresh the subscription' }
}

if($Mode -eq 'Verify'){
  Verify-State $state $chosenPort
}

$script:Results | Format-Table -AutoSize -Wrap
if(@($script:Results | Where-Object Status -eq 'FAIL').Count -gt 0){ exit 2 }
