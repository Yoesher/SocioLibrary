$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'This installation check is restricted to a disposable GitHub Actions runner.'
}
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read version' }
$root = Join-Path $env:RUNNER_TEMP 'sl-upgrade-check'
New-Item -ItemType Directory -Force $root | Out-Null
$installDir = Join-Path $root 'installed'
$data = Join-Path $env:LOCALAPPDATA 'SocioLit'
if (Test-Path -LiteralPath $data) { throw 'Refusing to use any pre-existing library' }
python -c "from pathlib import Path; import sys; from sociolit.smoke import seed_upgrade_fixture; p=Path(sys.argv[1]); p.mkdir(); seed_upgrade_fixture(p)" $data
if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated synthetic fixture' }
$before = @{}
Get-ChildItem -LiteralPath $data -File -Recurse | ForEach-Object {
    $before[$_.FullName] = (Get-FileHash -LiteralPath $_.FullName).Hash
}
function Assert-ResearchUnchanged {
    foreach ($file in $before.Keys) {
        if (-not (Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file).Hash -ne $before[$file]) {
            throw 'Installer or uninstaller changed research data'
        }
    }
}
function Run-Setup($exe, $arguments, $mustSucceed = $true) {
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(180000)) { throw 'Installer check timed out' }
    if ($mustSucceed -and $process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
    return $process.ExitCode
}
gh release download v0.12.3 --repo $env:GITHUB_REPOSITORY --pattern 'SocioLibrary-0.12.3-Windows-x64-Setup.exe' --dir $root
if ($LASTEXITCODE -ne 0) { throw 'Cannot retrieve previous public installer' }
$previous = Join-Path $root 'SocioLibrary-0.12.3-Windows-x64-Setup.exe'
$common = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-')
Run-Setup $previous ($common + @("/DIR=`"$installDir`"")) | Out-Null
$installedExe = Join-Path $installDir 'SocioLibrary.exe'
$oldHash = (Get-FileHash -LiteralPath $installedExe).Hash
Assert-ResearchUnchanged
$bundle = Get-Content dist/SocioLibrary/bundle-manifest.json -Raw | ConvertFrom-Json
$modifiedHeader = $bundle.pruned | ForEach-Object { Join-Path $installDir $_.path } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $modifiedHeader) {
    # The preceding public release is already slim. Restore a nonmatching
    # user-owned canary at an obsolete header path; it must remain untouched.
    $modifiedHeader = Join-Path $installDir $bundle.pruned[0].path
    New-Item -ItemType Directory -Force (Split-Path -Parent $modifiedHeader) | Out-Null
    [System.IO.File]::WriteAllText($modifiedHeader, 'Synthetic user-owned header in an already slim installation')
}
Add-Content -LiteralPath $modifiedHeader -Value 'Synthetic user-modified header canary'
$modifiedHeaderHash = (Get-FileHash -LiteralPath $modifiedHeader).Hash
$privateCanary = Join-Path $installDir '_internal/torch/include/synthetic-user-paper.pdf'
New-Item -ItemType Directory -Force (Split-Path -Parent $privateCanary) | Out-Null
[System.IO.File]::WriteAllText($privateCanary, 'Synthetic private canary; never delete as part of runtime cleanup')
$privateCanaryHash = (Get-FileHash -LiteralPath $privateCanary).Hash
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutFile = Join-Path $desktop 'SocioLibrary.lnk'
if (Test-Path -LiteralPath $shortcutFile) { throw 'Unexpected existing runner shortcut' }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutFile)
$shortcut.TargetPath = $installedExe
$shortcut.Description = 'SocioLibrary old descriptive shortcut'
$shortcut.Save()
$newSetup = (Resolve-Path "release-dist/SocioLibrary-$version-Windows-x64-Setup.exe").Path
$ready = Join-Path $root 'mutex-ready.txt'
$helper = Join-Path $root 'hold-mutex.py'
@'
import ctypes
import sys
import time
from pathlib import Path
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
kernel.CreateMutexW.restype = ctypes.c_void_p
handle = kernel.CreateMutexW(None, False, 'SocioLibraryDesktop')
assert handle
Path(sys.argv[1]).write_text('ready', encoding='ascii')
time.sleep(120)
'@ | Set-Content -LiteralPath $helper -Encoding utf8
$holder = Start-Process -FilePath (Get-Command python).Source -ArgumentList @("`"$helper`"", "`"$ready`"") -WindowStyle Hidden -PassThru
try {
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path -LiteralPath $ready); $attempt++) { Start-Sleep -Milliseconds 100 }
    if (-not (Test-Path -LiteralPath $ready)) { throw 'Mutex fixture did not start' }
    if ((Run-Setup $newSetup $common $false) -eq 0) { throw 'Installer replaced a running application' }
    if ((Get-FileHash -LiteralPath $installedExe).Hash -ne $oldHash) { throw 'Blocked installer changed the application' }
} finally {
    if (-not $holder.HasExited) { Stop-Process -Id $holder.Id; $holder.WaitForExit() }
}
# Deliberately omit /DIR: the new installer must find the old custom installation.
Run-Setup $newSetup $common | Out-Null
if (-not (Test-Path -LiteralPath $installedExe) -or (Get-FileHash -LiteralPath $installedExe).Hash -eq $oldHash) {
    throw 'New installer did not replace the original custom installation'
}
Assert-ResearchUnchanged
$cleanup = Get-Content (Join-Path $installDir 'bundle-cleanup.json') -Raw | ConvertFrom-Json
if ($cleanup.errors -ne 0 -or $cleanup.preserved_files -lt 2) { throw 'Overlay upgrade did not preserve user-owned files' }
$remainingDeveloperFiles = @(Get-ChildItem -LiteralPath (Join-Path $installDir '_internal/torch/include') -File -Recurse)
if ($remainingDeveloperFiles.Count -ne 2) { throw 'Overlay upgrade reintroduced obsolete developer files' }
if ((Get-FileHash -LiteralPath $modifiedHeader).Hash -ne $modifiedHeaderHash -or
    (Get-FileHash -LiteralPath $privateCanary).Hash -ne $privateCanaryHash) { throw 'Runtime cleanup modified a user canary' }
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutFile)
if ($shortcut.Description -ne 'SocioLibrary' -or $shortcut.TargetPath -ne $installedExe) { throw 'Existing shortcut was not normalized' }
$info = (Get-Item -LiteralPath $installedExe).VersionInfo
if ($info.ProductName -ne 'SocioLibrary' -or $info.FileDescription -ne 'SocioLibrary' -or $info.ProductVersion -ne $version) {
    throw 'Executable application identity is not normalized'
}
'Bundle cleanup verified: legacy development files removed; modified headers and private canaries preserved; shortcut and executable named SocioLibrary.'
$smokeData = Join-Path $root 'inherited-fixture'
$process = Start-Process -FilePath $installedExe -ArgumentList @('--smoke-test','--data-dir',"`"$smokeData`"") -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(180000) -or $process.ExitCode -ne 0) { throw 'Installed upgrade smoke check failed' }
$result = Get-Content (Join-Path $smokeData 'smoke-result.json') -Raw | ConvertFrom-Json
if (-not $result.data_inherited -or -not $result.snapshot_verified -or $result.version -ne $version -or $result.updater_mode -ne 'installed') {
    throw 'Installed application did not inherit the synthetic research library'
}
$handoffReport = Join-Path $root 'handoff-report.json'
$handoffData = Join-Path $root 'updated-by-helper'
python scripts/verify_update_handoff.py --installer $newSetup --target $installDir --data $handoffData --output $handoffReport
if ($LASTEXITCODE -ne 0) { throw 'Updater parent could not hand off installation' }
$resultPath = (Get-Content -LiteralPath $handoffReport -Raw | ConvertFrom-Json).result_file
for ($attempt = 0; $attempt -lt 600 -and -not (Test-Path -LiteralPath $resultPath); $attempt++) { Start-Sleep -Seconds 1 }
if (-not (Test-Path -LiteralPath $resultPath)) { throw 'Updater handoff verification timed out' }
$handoffResult = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
if (-not $handoffResult.success) { $handoffResult | ConvertTo-Json; throw 'Updater installation handoff failed' }
Assert-ResearchUnchanged
'In-app updater verified: parent exit, verified installer, original program directory, relaunch, and inherited data.'
Run-Setup (Join-Path $installDir 'unins000.exe') $common | Out-Null
Assert-ResearchUnchanged
'Upgrade verified: original install directory, running-app protection, data inheritance, backup, and uninstall retention.'
