# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


datas = [("assets", "assets"), ("config", "config")]
private_assets = Path("user_assets")
if os.environ.get("XIAOU_INCLUDE_USER_ASSETS") == "1" and private_assets.exists():
    private_runtime_assets = (
        (private_assets / "pet", "user_assets/pet"),
        (private_assets / "selfie.png", "user_assets"),
        (private_assets / "workflow.json", "user_assets"),
        (private_assets / "interaction_pack.json", "user_assets"),
    )
    datas.extend(
        (str(source), destination)
        for source, destination in private_runtime_assets
        if source.exists()
    )

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XiaoU",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="XiaoU",
)
app = BUNDLE(
    coll,
    name="XiaoU.app",
    icon="assets/icons/xiaou.icns",
    bundle_identifier="io.github.pixel1766054554.xiaou",
    info_plist={
        "CFBundleDisplayName": "小u",
        "CFBundleName": "小u",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
    },
)
