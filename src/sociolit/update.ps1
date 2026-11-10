$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$result = @{success=$false; version=$request.version; installer_exit_code=$null}
$handedOff = $false
function Write-JsonAtomic($path, $value) {
    $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath ($path + '.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($path + '.tmp') -Destination $path -Force
}
function Write-Result {
    Write-JsonAtomic $request.result_file $result
}
try {
    if ($request.request_id -notmatch '^[a-f0-9]{32}$' -or $request.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid update request' }
    if ($request.test_mode -and $env:GITHUB_ACTIONS -ne 'true') { throw 'Test mode is restricted to a disposable runner' }
    $installer = Get-Item -LiteralPath $request.installer
    if ($installer.Name -ne "SocioLibrary-$($request.version)-Windows-x64-Setup.exe" -or
        $installer.Length -ne $request.size -or $request.sha256 -notmatch '^[a-f0-9]{64}$' -or
        (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sha256) {
        throw 'Installer verification failed'
    }
    # Acquire a handle before acknowledging readiness; later PID reuse cannot target another process.
    $parentProcess = Get-Process -Id $request.parent_pid -ErrorAction Stop
    $null = $parentProcess.Handle
    $handedOff = $true
    Write-JsonAtomic $request.ready_file @{request_id=$request.request_id}
    if (-not $parentProcess.WaitForExit(300000)) { throw 'The application did not finish closing; no installation was attempted' }
    if (Test-Path -LiteralPath $request.result_file) {
        $previousResult = Get-Content -LiteralPath $request.result_file -Raw | ConvertFrom-Json
        if ($previousResult.cancelled -eq $true) { exit 0 }
    }
    if ((Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $request.sha256) {
        throw 'Installer changed after handoff'
    }
    $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/SP-','/NORESTART','/NOCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS',
        ('/DIR="' + $request.target_dir + '"'),('/LOG="' + $request.result_file + '.install.log"'))
    $setup = Start-Process -FilePath $installer.FullName -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $setup.WaitForExit(600000)) { throw 'The installer is still running; inspect its log before retrying' }
    $result.installer_exit_code = $setup.ExitCode
    if ($setup.ExitCode -ne 0) { throw "Installation stopped with code $($setup.ExitCode)" }
    $program = Join-Path $request.target_dir 'SocioLibrary.exe'
    if (-not (Test-Path -LiteralPath $program -PathType Leaf)) { throw 'Updated application was not found' }
    $launchArgs = @('--data-dir', ('"' + $request.data_dir + '"'))
    if ($request.test_mode) { $launchArgs = @('--smoke-test') + $launchArgs }
    $style = if ($request.test_mode) { 'Hidden' } else { 'Normal' }
    $application = Start-Process -FilePath $program -ArgumentList $launchArgs -WindowStyle $style -PassThru
    if ($request.test_mode) {
        if (-not $application.WaitForExit(180000) -or $application.ExitCode -ne 0) { throw 'Updated application verification failed' }
        $smoke = Get-Content -LiteralPath (Join-Path $request.data_dir 'smoke-result.json') -Raw | ConvertFrom-Json
        if (-not $smoke.data_inherited -or -not $smoke.snapshot_verified -or $smoke.updater_mode -ne 'installed') { throw 'Updated library did not pass verification' }
    }
    $result.success = $true
    Write-Result
} catch {
    $result.error = $_.Exception.Message
    Write-Result
    if (-not $request.test_mode -and $handedOff -and $parentProcess.HasExited) {
        try {
            if ((Test-Path -LiteralPath $request.fallback_exe -PathType Leaf) -and
                [System.IO.Path]::GetFileName($request.fallback_exe) -eq 'SocioLibrary.exe') {
                Start-Process -FilePath $request.fallback_exe -ArgumentList @('--data-dir', ('"' + $request.data_dir + '"')) -WindowStyle Normal | Out-Null
            }
        } catch { }
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show('更新未完成，已尝试重新打开原软件。资料库仍在原目录，可在“软件更新”中查看记录并重试。', 'SocioLibrary') | Out-Null
    }
    exit 1
}
