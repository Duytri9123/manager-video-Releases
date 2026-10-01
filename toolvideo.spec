# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


project_root = Path(SPECPATH)
app_name = "DuyTrisCustomer" if os.environ.get("DUYTRIS_BUILD_EDITION") == "customer" else "DuyTrisDownloader"

datas = [
    (str(project_root / "templates"), "templates"),
    (str(project_root / "static"), "static"),
    (str(project_root / "img"), "img"),
    (str(project_root / "config/default_config.py"), "config"),
    (str(project_root / "config/translation_style.txt"), "config"),

    (str(project_root / "config.example.yml"), "."),
    (str(project_root / "client_secrets.example.json"), "."),

]

binaries = []
hiddenimports = []

# Add PyArmor-obfuscated security modules if present
obf_src = project_root / "obf_src"
if obf_src.exists() and obf_src.is_dir():
    for pyfile in obf_src.glob("*.py"):
        datas.append((str(pyfile), "."))
    # PyArmor runtime is a C extension (.pyd) — MUST be in binaries, not datas
    rt_dir = obf_src / "pyarmor_runtime_000000"
    if rt_dir.exists():
        rt_pyd = rt_dir / "pyarmor_runtime.pyd"
        if rt_pyd.exists():
            binaries.append((str(rt_pyd), "pyarmor_runtime_000000"))
        datas.append((str(rt_dir / "__init__.py"), "pyarmor_runtime_000000"))

# Force-include utils/*.py (PyInstaller auto-import may miss them)
utils_dir = project_root / "utils"
for pyfile in utils_dir.glob("*.py"):
    if pyfile.name != "__init__.py":
        datas.append((str(pyfile), "utils"))

# Blueprints are imported dynamically in extensions.py.
hiddenimports += [".".join(p.relative_to(project_root).with_suffix("").parts) for p in (project_root / "templates/pages").rglob("*.py") if p.name != "__init__.py"]
hiddenimports += collect_submodules("vieneu")
hiddenimports += collect_submodules("vieneu_utils")
datas += collect_data_files("vieneu")
datas += collect_data_files("vieneu_utils")
hiddenimports += collect_submodules("sea_g2p")
datas += collect_data_files("sea_g2p")
binaries += collect_dynamic_libs("sea_g2p")

python_dll = Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
if python_dll.exists():
    binaries.append((str(python_dll), "."))

# Rely on PyInstaller auto-detection from desktop_launcher.py imports.
# Dynamic imports are covered by hiddenimports below.
for package in (
    "ctranslate2",
    "onnxruntime",
    "tokenizers",
    "curl_cffi",
):
    binaries += collect_dynamic_libs(package)

for package in (
    "faster_whisper",
    "playwright",
    "pyngrok",
    "google.genai",
    "curl_cffi",
):
    datas += collect_data_files(package)

for distribution in (
    "ctranslate2",
    "faster-whisper",
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-genai",
    "onnxruntime",
    "playwright",
    "pyngrok",
    "tokenizers",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

hiddenimports += [
    "curl_cffi",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtNetwork",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWidgets",
    "aiofiles",
    "ctranslate2",
    "edge_tts",
    "engineio.async_drivers.threading",
    "faster_whisper",
    "google.genai",
    "googleapiclient.discovery",
    "googleapiclient.discovery_cache",
    "google_auth_oauthlib.flow",
    "onnxruntime",
    "playwright.async_api",
    "pyngrok.ngrok",
    "simple_websocket",
    "socks",
    "tokenizers",
    "unicodedata",
    # Explicitly import utils modules that PyInstaller may miss
    "utils.security",
    "utils.auto_updater",
    "utils.license_guard",
    "utils.licensing_client",
    "utils.licensing_routes",
    "utils.security_core",
]

a = Analysis(
    ["desktop_launcher.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "ruff",
        "datasets",
        "gradio",
        "llvmlite",
        "matplotlib",
        "numba",
        "pandas",
        "pyarrow",
        "sklearn",
        "speechbrain",
        "tensorflow",
        "tensorflow_intel",
        "torchtext",
        "torchvision",
        "whisper",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
    ],
    noarchive=False,
    optimize=0,
)

# Qt6Core links against the Windows ICU shim in System32. PyInstaller can pick
# up Poppler's incompatible icuuc.dll from the build host's PATH; bundling it
# beside the EXE makes importing PySide6.QtCore fail with WinError 127.
a.binaries = [entry for entry in a.binaries if entry[0].lower() != "icuuc.dll"]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory=".",
    icon=str(project_root / "img" / "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
