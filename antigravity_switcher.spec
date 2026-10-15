# -*- mode: python ; coding: utf-8 -*-
"""antigravity_switcher.spec - PyInstaller spec for Antigravity Multi-Account Switchboard & Quota Monitor.

Builds a self-contained, hardened Windows desktop binary with:
- Per-Monitor v2 High-DPI Windows application manifest
- Full app icon bundling (app_icon.ico, app_icon.png)
- Embedded config.json template and guide.html documentation
- Clean module exclusions to minimize executable bloat and surface area
"""

import os

block_cipher = None

a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app_icon.ico', '.'),
        ('app_icon.png', '.'),
        ('config.json', '.'),
        ('guide.html', '.'),
    ],
    hiddenimports=[
        'router',
        'ctypes',
        'ctypes.wintypes',
        'json',
        'ssl',
        'urllib.request',
        'urllib.parse',
        'concurrent.futures',
        'secrets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'torch',
        'IPython',
        'jupyter',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AntigravitySwitchboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)
