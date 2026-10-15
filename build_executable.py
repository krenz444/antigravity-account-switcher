#!/usr/bin/env python3
"""build_executable.py - Builds hardened Windows executable for Antigravity Switchboard.

Usage:
    python build_executable.py [--clean]
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE = os.path.join(SCRIPT_DIR, "antigravity_switcher.spec")


def build():
    print("=" * 70)
    print("  Antigravity Switchboard - Binary Hardening & Packaging")
    print("=" * 70)

    # Check for PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[NOTICE] PyInstaller is not installed in the current Python environment.")
        print("To compile a standalone binary, run:")
        print("    pip install pyinstaller")
        print("    python build_executable.py")
        print("=" * 70)
        return False

    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "-y", SPEC_FILE]
    print(f"[BUILD] Executing: {' '.join(cmd)}")
    ret = subprocess.call(cmd, cwd=SCRIPT_DIR)
    if ret == 0:
        dist_exe = os.path.join(SCRIPT_DIR, "dist", "AntigravitySwitchboard.exe")
        print(f"\n[SUCCESS] Built hardened executable: {dist_exe}")
        return True
    else:
        print(f"\n[ERROR] PyInstaller build failed with exit code {ret}")
        return False


if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
