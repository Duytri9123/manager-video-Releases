#!/usr/bin/env python3
"""Obfuscate security-critical modules using PyArmor before PyInstaller build.

Usage:
    python cli/obfuscate_modules.py

Requires: pyarmor>=14.0.0 installed in the active venv.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBF_DIR = ROOT / "obf_src"
SECURITY_MODULES = [
    "utils/security_core.py",
    "utils/licensing_client.py",
    "utils/license_guard.py",
]


def clean_obf_dir():
    if OBF_DIR.exists():
        shutil.rmtree(OBF_DIR)
    OBF_DIR.mkdir(parents=True, exist_ok=True)


def check_pyarmor():
    """Check if pyarmor CLI is available in the current venv."""
    # Try pyarmor.exe next to python.exe first
    import os as _os
    pyarmor_exe = Path(_os.path.dirname(sys.executable)) / "pyarmor.exe"
    if pyarmor_exe.exists():
        return str(pyarmor_exe)
    # Fallback: check PATH
    import shutil
    found = shutil.which("pyarmor")
    if found:
        return found
    return None


def obfuscate():
    pyarmor_path = check_pyarmor()
    if not pyarmor_path:
        print("[!] PyArmor not found. Install: pip install pyarmor")
        print("[!] Falling back: using unobfuscated source files.")
        return False

    # PyArmor obfuscates entire project — we'll copy only security modules to a
    # temp dir, obfuscate, then copy results to obf_src/
    temp_dir = ROOT / ".tmp_obf_src"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for mod_rel in SECURITY_MODULES:
        src = ROOT / mod_rel
        if not src.exists():
            print(f"[!] Source not found: {src}")
            continue
        dest = temp_dir / src.name
        shutil.copy2(src, dest)

    print("[*] Running PyArmor obfuscation...")
    # PyArmor 9.x uses: pyarmor gen --output <dir> [--recursive] <source>
    # Sources will be a single temp dir with our files
    result = subprocess.run(
        [
            pyarmor_path, "gen",
            "--output", str(OBF_DIR),
            "--recursive",
            str(temp_dir),
        ],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        print(f"[!] PyArmor failed: {result.stderr}")
        print("[!] Falling back: using unobfuscated source files.")
        clean_obf_dir()
        return False

    print(f"[+] PyArmor obfuscation complete -> {OBF_DIR}")

    # PyArmor 9.x creates output in OBF_DIR/<src_dirname>/
    # Copy all .py files to flat obf_src/ for easy inclusion
    for pyfile in OBF_DIR.rglob("*.py"):
        if pyfile.name == "__init__.py":
            continue
        dest = OBF_DIR / pyfile.name
        if not dest.exists():
            shutil.copy2(pyfile, dest)
            print(f"    v {pyfile.name}")

    # Clean temp
    shutil.rmtree(temp_dir)
    return True


def main():
    print(f"[*] Obfuscating security modules for {sys.platform}...")
    success = obfuscate()
    if success:
        print("[+] All modules obfuscated successfully.")
        print(f"[+] Obfuscated files: {OBF_DIR}")
    else:
        print("[*] Skipping obfuscation (PyArmor not available).")


if __name__ == "__main__":
    main()
