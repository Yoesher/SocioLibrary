"""Give the frozen Windows executable the same public name as the application."""
import re
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / 'pyproject.toml').read_text('utf-8'))['project']['version']
if not re.fullmatch(r'\d+\.\d+\.\d+', version):
    raise SystemExit('Invalid application version')
numbers = tuple(map(int, version.split('.'))) + (0,)
text = f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f,
                   flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'SocioLibrary'),
    StringStruct('ProductName', 'SocioLibrary'),
    StringStruct('InternalName', 'SocioLibrary'),
    StringStruct('OriginalFilename', 'SocioLibrary.exe'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033,1200])])])
'''
(root / 'build').mkdir(exist_ok=True)
(root / 'build/version-info.txt').write_text(text, encoding='utf-8')
