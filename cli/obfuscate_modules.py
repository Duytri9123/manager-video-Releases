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
    try:
        subprocess.run(
            [sys.executable, "-m", "pyarmor", "--version"],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except Exception:
        return False


def obfuscate():
    if not check_pyarmor():
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
    result = subprocess.run(
        [
            sys.executable, "-m", "pyarmor", "gen",
            "--output", str(OBF_DIR),
            "--exact",
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

    # Copy resulting .py files from obfuscated output
    obf_output = OBF_DIR
    for src_file in temp_dir.iterdir():
        if src_file.suffix == ".py":
            # PyArmor creates output with same filenames
            obf_file = obf_output / src_file.name
            if obf_file.exists():
                print(f"    √ {src_file.name}")
            else:
                # Search recursively
                found = list(obf_output.rglob(src_file.name))
                if found:
                    shutil.copy2(found[0], obf_output / src_file.name)
                    print(f"    √ {src_file.name} (found in subdir)")

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
