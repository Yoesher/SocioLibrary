"""Build a native, ad-hoc-signed preview .app/ZIP on a disposable macOS runner."""
import hashlib
import importlib.util
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

if sys.platform != 'darwin':
    raise SystemExit('macOS builds must run on macOS.')
root = Path(__file__).resolve().parents[1]
os.chdir(root)
version = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
arch = platform.machine()
if arch not in ('arm64', 'x86_64'):
    raise SystemExit('Unsupported Mac architecture')
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
        '--name', 'SocioLibrary', '--osx-bundle-identifier', 'org.yoesher.sociolibrary',
        '--target-architecture', arch, '--paths', 'src',
        '--add-data', 'src/sociolit/static:sociolit/static',
        '--add-data', 'config/public-journals.toml:sociolit/defaults',
        '--add-data', 'src/sociolit/ocr.ps1:sociolit', '--add-data', 'src/sociolit/update.ps1:sociolit',
        '--collect-all', 'webview', '--collect-all', 'pypdfium2',
        '--hidden-import', 'keyring.backends.macOS', '--hidden-import', 'webview.platforms.cocoa',
        '--hidden-import', 'uvicorn.logging', '--hidden-import', 'uvicorn.loops.auto',
        '--hidden-import', 'uvicorn.protocols.http.auto', '--hidden-import', 'uvicorn.lifespan.on',
        '--exclude-module', 'pytest', '--exclude-module', 'IPython', '--exclude-module', 'tensorflow',
        '--exclude-module', 'torchvision', '--exclude-module', 'torchaudio']
if importlib.util.find_spec('sentence_transformers'):
    for name in ('sentence_transformers', 'transformers', 'tokenizers', 'torch'):
        args += ['--collect-all', name]
args.append('scripts/desktop_entry.py')
subprocess.run(args, check=True)
app = Path('dist/SocioLibrary.app')
resources = app / 'Contents/Resources'
resources.mkdir(exist_ok=True)
for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
    shutil.copy2(name, resources / name)
subprocess.run([sys.executable, 'scripts/collect_licenses.py'], check=True)
shutil.copytree('dist/SocioLibrary/third-party-licenses', resources / 'third-party-licenses', dirs_exist_ok=True)
info = app / 'Contents/Info.plist'
with info.open('rb') as f:
    data = plistlib.load(f)
data.update(CFBundleShortVersionString=version, CFBundleVersion=version,
            CFBundleDisplayName='SocioLibrary', CFBundleName='SocioLibrary',
            NSHighResolutionCapable=True, LSMinimumSystemVersion='15.0')
with info.open('wb') as f:
    plistlib.dump(data, f)
subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
output = Path('release-dist')
output.mkdir(exist_ok=True)
stem = f'SocioLibrary-{version}-macOS-{arch}'
subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(output / (stem+'.zip'))], check=True)
lines = []
for suffix in ('zip',):
    path = output / (stem+'.'+suffix)
    lines.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name)
(output / f'SHA256SUMS-macOS-{arch}.txt').write_text('\n'.join(lines)+'\n', encoding='ascii')
