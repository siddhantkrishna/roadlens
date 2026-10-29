# Build with: .venv/bin/python scripts/build_app.py
import hashlib
from importlib.metadata import distribution
from pathlib import Path

from roadlens.detection import MODEL_SHA256

root = Path(SPECPATH)
model = root / 'models/yolov8n.onnx'
if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
    raise RuntimeError('Run roadlens fetch-model before building; pinned offline weights are required.')
datas = [(str(model), 'models'),
         (str(root / 'THIRD_PARTY.md'), 'licenses'),
         (str(root / 'LICENSE'), 'licenses'), (str(root / 'NOTICE'), 'licenses'),
         (str(root / 'docs/LICENSING.md'), 'docs'),
         (str(root / 'README.md'), 'docs'), (str(root / 'DESKTOP.md'), 'docs'),
         (str(root / 'build/ROADLENS.icns'), '.')]
for package in ('numpy', 'opencv-python', 'supervision', 'scipy', 'matplotlib',
                'requests', 'PySide6-Essentials', 'shiboken6'):
    dist = distribution(package)
    for file in dist.files or []:
        if 'license' in str(file).lower() or 'copying' in str(file).lower():
            source = Path(dist.locate_file(file))
            if source.is_file():
                datas.append((str(source), f'licenses/{package}/{file.parent}'))
a = Analysis([str(root / 'scripts/desktop_entry.py')], pathex=[str(root / 'src')],
             binaries=[], datas=datas,
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest', 'tkinter', 'IPython', 'torch', 'PyQt5', 'PyQt6'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ROADLENS', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          target_arch='x86_64', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ROADLENS')
app = BUNDLE(coll, name='ROADLENS.app', icon=str(root / 'build/ROADLENS.icns'),
             bundle_identifier='local.roadlens.desktop', version='0.1.0',
             info_plist={
                 'CFBundleDisplayName': 'ROADLENS',
                 'LSMinimumSystemVersion': '14.0',
                 'NSHighResolutionCapable': True,
                 'NSCameraUsageDescription': 'ROADLENS previews your selected cameras and detects vehicles locally.',
                 'NSCameraUseContinuityCameraDeviceType': True,
                 'NSHumanReadableCopyright': 'Copyright (C) 2026 ROADLENS contributors. AGPL-3.0-only.',
             })
