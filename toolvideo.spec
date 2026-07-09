# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


project_root = Path(SPECPATH)
obf_src = project_root / "obf_src"
if obf_src.exists():
    # Use PyArmor-obfuscated sources for security modules
    datas += collect_data_files(str(obf_src))

datas = [
    (str(project_root / "templates"), "templates"),
    (str(project_root / "static"), "static"),
    (str(project_root / "img"), "img"),
    (str(project_root / "config"), "config"),
    (str(project_root / "config.yml"), "."),
    (str(project_root / "config.example.yml"), "."),
    (str(project_root / "client_secrets.example.json"), "."),
]

binaries = []
hiddenimports = []

# Blueprints are imported dynamically in extensions.py.
hiddenimports += collect_submodules("routes")

python_dll = Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
if python_dll.exists():
    binaries.append((str(python_dll), "."))

# Rely on PyInstaller auto-detection from desktop_launcher.py imports.
# Dynamic imports are covered by hiddenimports below.
for package in (
    "ctranslate2",
    "onnxruntime",
    "tokenizers",
):
    binaries += collect_dynamic_libs(package)

for package in (
    "faster_whisper",
    "playwright",
    "pyngrok",
    "google.genai",
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
        "scipy",
        "sklearn",
        "speechbrain",
        "tensorflow",
        "tensorflow_intel",
        "torch",
        "torchaudio",
        "torchtext",
        "torchvision",
        "transformers",
        "whisper",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DuyTrisDownloader",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DuyTrisDownloader",
)
