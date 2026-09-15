[CmdletBinding(SupportsShouldProcess)]
param(
  [ValidateSet('Plan','Audit','Apply','Verify','Restore')][string]$Mode = 'Audit',
  [ValidateSet('PreferIPv4','Keep','StrictDisable')][string]$Strategy = 'PreferIPv4',
  [string[]]$AdapterName,
  [switch]$RestoreAdapterBindings,
  [string]$BackupPath = (Join-Path $env:LOCALAPPDATA 'flclash-network-setup\ipv6-policy-backup.json')
)

$ErrorActionPreference = 'Stop'
$registryPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters'
$registryName = 'DisabledComponents'

function Test-Admin {
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  $principal=[Security.Principal.WindowsPrincipal]::new($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RegistryState {
  try {
    $item=Get-ItemProperty -LiteralPath $registryPath -Name $registryName -ErrorAction Stop
    return [pscustomobject]@{Present=$true;Value=[int64]$item.$registryName}
  } catch {
    return [pscustomobject]@{Present=$false;Value=$null}
  }
}

function Get-TargetBindings {
  $adapters=if($AdapterName){
    @($AdapterName | ForEach-Object { Get-NetAdapter -Name $_ -ErrorAction Stop })
  } else {
    @(Get-NetAdapter -Physical -ErrorAction Stop | Where-Object Status -eq 'Up')
  }
  return @($adapters | ForEach-Object {
    $binding=Get-NetAdapterBinding -Name $_.Name -ComponentID ms_tcpip6 -ErrorAction Stop
    [pscustomobject]@{Name=$_.Name;Enabled=[bool]$binding.Enabled}
  })
}

function Get-PrefixState {
  $v4=$null; $v6=$null
  foreach($line in @(& netsh interface ipv6 show prefixpolicies 2>$null)){
    if($line -match '^\s*(\d+)\s+\d+\s+(::ffff:0:0/96|::/0)\s*$'){
      if($Matches[2] -eq '::ffff:0:0/96'){ $v4=[int]$Matches[1] }
      if($Matches[2] -eq '::/0'){ $v6=[int]$Matches[1] }
    }
  }
  [pscustomobject]@{IPv4MappedPrecedence=$v4;IPv6Precedence=$v6;IPv4Preferred=($null -ne $v4 -and $null -ne $v6 -and $v4 -gt $v6)}
}

function Save-Baseline {
  if(Test-Path -LiteralPath $BackupPath){ return }
  $directory=Split-Path -Parent $BackupPath
  if($directory -and -not (Test-Path -LiteralPath $directory)){
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
  }
  $registry=Get-RegistryState
  try { $bindings=@(Get-TargetBindings) } catch { $bindings=@() }
  [pscustomobject]@{
    RegistryValuePresent=$registry.Present
    RegistryValue=$registry.Value
    AdapterBindings=$bindings
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $BackupPath -Encoding UTF8
}

function Write-Result([string]$Status,[string]$Detail,[bool]$RestartRequired=$false) {
  $registry=Get-RegistryState
  $prefix=Get-PrefixState
  try { $bindings=@(Get-TargetBindings); $bindingState='available' } catch { $bindings=@(); $bindingState='unavailable' }
  [pscustomobject]@{
    mode=$Mode
    strategy=$Strategy
    status=$Status
    detail=$Detail
    registryValue=if($registry.Present){$registry.Value}else{$null}
    ipv4MappedPrecedence=$prefix.IPv4MappedPrecedence
    ipv6Precedence=$prefix.IPv6Precedence
    ipv4Preferred=$prefix.IPv4Preferred
    adapterBindingState=$bindingState
    disabledAdapterCount=@($bindings | Where-Object {-not $_.Enabled}).Count
    backup=Split-Path -Leaf $BackupPath
    requiresRestart=$RestartRequired
  } | ConvertTo-Json -Compress
}

if($Mode -eq 'Plan'){
  [pscustomobject]@{
    strategy=$Strategy
    registryValue=if($Strategy -eq 'PreferIPv4'){32}else{$null}
    requiresRestart=($Strategy -eq 'PreferIPv4')
    disableAdapterBindings=($Strategy -eq 'StrictDisable')
    adapterScope='selected active physical adapters'
    requiresExplicitSelection=($Strategy -eq 'StrictDisable')
  } | ConvertTo-Json -Compress
  exit 0
}

if($Mode -eq 'Audit'){
  $registry=Get-RegistryState
  $prefix=Get-PrefixState
  $registryText=if($registry.Present){'0x{0:X}' -f $registry.Value}else{'absent'}
  $prefixText=if($null -ne $prefix.IPv4MappedPrecedence -and $null -ne $prefix.IPv6Precedence){
    'IPv4-mapped {0}, IPv6 {1}' -f $prefix.IPv4MappedPrecedence,$prefix.IPv6Precedence
  } else {'prefix policy unavailable'}
  Write-Result 'INFO' ("DisabledComponents $registryText; $prefixText")
  exit 0
}

if($Mode -eq 'Verify'){
  if($Strategy -eq 'Keep'){
    Write-Result 'NOT_APPLICABLE' 'System IPv6 policy was intentionally kept unchanged'
    exit 0
  }
  if($Strategy -eq 'StrictDisable'){
    try {
      $bindings=@(Get-TargetBindings)
      $disabled=@($bindings | Where-Object {-not $_.Enabled}).Count
      if($bindings.Count -gt 0 -and $disabled -eq $bindings.Count){ Write-Result 'PASS' 'IPv6 is disabled on the selected active physical adapters' }
      else { Write-Result 'FAIL' 'One or more selected active physical adapters still have IPv6 enabled' }
    } catch { Write-Result 'UNKNOWN' 'Unable to read selected adapter bindings' }
    exit 0
  }
  $registry=Get-RegistryState
  $prefix=Get-PrefixState
  if($registry.Present -and $registry.Value -eq 32 -and $prefix.IPv4Preferred){
    Write-Result 'PASS' 'IPv4 is preferred while IPv6 remains available'
  } elseif($registry.Present -and $registry.Value -eq 32){
    Write-Result 'PENDING' 'Registry value is 0x20; restart Windows and verify prefix policy again' $true
  } else {
    Write-Result 'FAIL' 'DisabledComponents is not 0x20'
  }
  exit 0
}

if($Mode -eq 'Restore'){
  if(-not (Test-Path -LiteralPath $BackupPath)){ Write-Result 'FAIL' 'IPv6 baseline backup was not found'; exit 2 }
  if(-not (Test-Admin)){ Write-Result 'PENDING' 'Run Restore in Administrator PowerShell'; exit 0 }
  $backup=Get-Content -LiteralPath $BackupPath -Raw | ConvertFrom-Json
  if($backup.RegistryValuePresent){
    if($PSCmdlet.ShouldProcess($registryPath,'restore DisabledComponents')){
      New-Item -Path $registryPath -Force | Out-Null
      New-ItemProperty -Path $registryPath -Name $registryName -PropertyType DWord -Value ([int64]$backup.RegistryValue) -Force | Out-Null
    }
  } elseif($PSCmdlet.ShouldProcess($registryPath,'remove DisabledComponents')){
    Remove-ItemProperty -LiteralPath $registryPath -Name $registryName -ErrorAction SilentlyContinue
  }
  foreach($binding in @($backup.AdapterBindings)){
    if($binding.Enabled -and $PSCmdlet.ShouldProcess($binding.Name,'enable IPv6 binding')){
      Enable-NetAdapterBinding -Name $binding.Name -ComponentID ms_tcpip6 | Out-Null
    } elseif(-not $binding.Enabled -and $PSCmdlet.ShouldProcess($binding.Name,'disable IPv6 binding')){
      Disable-NetAdapterBinding -Name $binding.Name -ComponentID ms_tcpip6 | Out-Null
    }
  }
  Write-Result 'PENDING' 'Baseline restored; restart Windows to finish applying the registry policy' $true
  exit 0
}

if($Strategy -eq 'Keep'){
  Write-Result 'NOT_APPLICABLE' 'System IPv6 policy was intentionally kept unchanged'
  exit 0
}

if(-not (Test-Admin) -and -not $WhatIfPreference){
  Write-Result 'PENDING' 'Run Apply in Administrator PowerShell'
  exit 0
}

if($WhatIfPreference){
  Write-Result 'PENDING' $(if($Strategy -eq 'PreferIPv4'){'Would set DisabledComponents to 0x20'}else{'Would disable IPv6 only on selected active physical adapters'}) ($Strategy -eq 'PreferIPv4')
  exit 0
}

Save-Baseline

if($Strategy -eq 'PreferIPv4'){
  $existing=Get-RegistryState
  if($existing.Present -and $existing.Value -notin @(0,32)){
    Write-Result 'FAIL' ('Existing DisabledComponents value 0x{0:X} was preserved; review it before migration' -f $existing.Value)
    exit 2
  }
  if($PSCmdlet.ShouldProcess($registryPath,'set DisabledComponents to 0x20')){
    New-Item -Path $registryPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name $registryName -PropertyType DWord -Value 32 -Force | Out-Null
  }
  if($RestoreAdapterBindings){
    foreach($binding in @(Get-TargetBindings | Where-Object {-not $_.Enabled})){
      if($PSCmdlet.ShouldProcess($binding.Name,'enable IPv6 binding')){
        Enable-NetAdapterBinding -Name $binding.Name -ComponentID ms_tcpip6 | Out-Null
      }
    }
  }
  Write-Result 'PENDING' 'IPv4 preference set to 0x20; restart Windows, then verify prefix policy' $true
  exit 0
}

$targets=@(Get-TargetBindings)
if($targets.Count -eq 0){ Write-Result 'FAIL' 'No selected active physical adapters were found'; exit 2 }
foreach($binding in $targets){
  if($binding.Enabled -and $PSCmdlet.ShouldProcess($binding.Name,'strictly disable IPv6 binding')){
    Disable-NetAdapterBinding -Name $binding.Name -ComponentID ms_tcpip6 | Out-Null
  }
}
Write-Result 'PASS' 'Strict mode disabled IPv6 on selected active physical adapters'
