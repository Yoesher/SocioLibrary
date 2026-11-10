$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read application version' }
& python scripts/create_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
$arguments = @('-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--name','SocioLibrary','--icon','build/desktop.ico',
  '--paths','src','--add-data','src/sociolit/ocr.ps1;sociolit','--add-data','src/sociolit/update.ps1;sociolit','--add-data','src/sociolit/static;sociolit/static','--add-data','config/public-journals.toml;sociolit/defaults',
  '--collect-all','webview','--collect-all','sentence_transformers','--collect-all','transformers',
  '--collect-all','tokenizers','--collect-all','torch','--collect-all','pypdfium2',
  '--hidden-import','uvicorn.logging','--hidden-import','uvicorn.loops.auto',
  '--hidden-import','uvicorn.protocols.http.auto','--hidden-import','uvicorn.lifespan.on',
  '--exclude-module','pytest','--exclude-module','IPython','--exclude-module','tensorflow',
  '--exclude-module','torchvision','--exclude-module','torchaudio','scripts/desktop_entry.py')
& python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
& python scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'Dependency license collection failed' }
New-Item -ItemType Directory -Force release-dist | Out-Null
Copy-Item LICENSE,THIRD_PARTY_NOTICES.md -Destination dist/SocioLibrary
$iscc = 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) { throw 'Install Inno Setup 6 from jrsoftware.org before building the installer' }
& $iscc "/DAppVersion=$version" packaging/windows.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Compress-Archive -Path dist/SocioLibrary -DestinationPath "release-dist/SocioLibrary-$version-Windows-x64-Portable.zip" -Force
Get-ChildItem release-dist -File | Where-Object Name -ne 'SHA256SUMS.txt' | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)"
} | Set-Content release-dist/SHA256SUMS.txt -Encoding ascii
