$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
$pythonExe = Join-Path $projectDir '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
$dependencyStatus = & $pythonExe -c "import importlib.util; print('ready' if all(importlib.util.find_spec(m) is not None for m in ('sociolit','fastapi','pypdf','pypdfium2','httpx','defusedxml','filelock','fontTools')) else 'missing')"
if ($dependencyStatus -ne 'ready') {
    & $pythonExe -m pip install -e .
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network and retry.' }
}
if (-not (Test-Path -LiteralPath 'config.local.toml')) {
    Copy-Item -LiteralPath 'config/local.example.toml' -Destination 'config.local.toml'
    $publicConfig = Get-Content -LiteralPath 'config/public-journals.toml' -Raw -Encoding UTF8
    $journalOffset = $publicConfig.IndexOf('[[journals]]')
    Add-Content -LiteralPath 'config.local.toml' -Value $publicConfig.Substring($journalOffset) -Encoding UTF8
    Write-Host 'Created config.local.toml. Set zotero.allowed_roots once to enable PDF import.'
}
$existingApp = $null
try {
    $probe = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/' -UseBasicParsing -TimeoutSec 3
    if ($probe.Content -match '<title>SocioLibrary') { $existingApp = 'sociolit' } else { $existingApp = 'other' }
} catch {
    # No reachable local page: start the service below.
}
if ($existingApp -eq 'sociolit') {
    & $pythonExe -c "import webbrowser; webbrowser.open('http://127.0.0.1:8765/')"
    exit 0
}
if ($existingApp -eq 'other') { throw 'Port 8765 is already used by another local application.' }
& $pythonExe -m sociolit serve --config config.local.toml --open-browser
