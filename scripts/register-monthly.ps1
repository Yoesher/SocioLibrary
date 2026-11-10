param([string]$TaskName = 'SocioLit monthly journal discovery')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv/Scripts/python.exe'
$configPath = Join-Path $projectDir 'config.local.toml'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run scripts/start.ps1 first.' }
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Create config.local.toml first.' }
# Daily eligibility check; the CLI updates each source only once per calendar month.
# StartWhenAvailable catches up after the computer was off. Current-user privileges only.
$arguments = '-m sociolit discover --due --config "' + $configPath + '"'
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Daily -At '10:17'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Check public journal metadata once per month; no PDF downloads.'
Write-Host 'Registered. Requires a logged-in user and network. Review reminders in the local app.'
