#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title MX Switch to Mac
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 🖥️
# @raycast.packageName KVM
# @raycast.description Switch all Logitech Easy-Switch devices to channel 2 and BetterDisplay to USB-C (Mac)

"""
Raycast Script Command (Windows) that launches python/mxswitch.py.

Setup:
  1. Raycast Settings → Extensions → Script Commands → Add Directories
  2. Add this folder:  <repo>/windows/raycast
  3. Ensure `python` or `python3` is on PATH (or edit PYTHON below)
  4. Search "MX Switch to Mac" in Raycast; optionally bind a hotkey via
     Action Panel → Configure Command → Record Hotkey
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Prefer the Windows py launcher / python on PATH. Override if needed:
#   setx MXSWITCH_PYTHON "C:\\Users\\you\\AppData\\Local\\Programs\\Python\\Python312\\pythonw.exe"
PYTHON = os.environ.get("MXSWITCH_PYTHON", "").strip() or "pythonw"

HERE = Path(__file__).resolve().parent
MXSWITCH = (HERE / ".." / ".." / "python" / "mxswitch.py").resolve()

if not MXSWITCH.is_file():
    print(f"mxswitch.py not found: {MXSWITCH}", file=sys.stderr)
    sys.exit(1)

# pythonw = no console window when launched from Raycast
cmd = [PYTHON, str(MXSWITCH)]
try:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
except FileNotFoundError:
    # Fallback if pythonw is missing
    cmd[0] = "python"
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

if proc.stdout:
    print(proc.stdout.strip())
if proc.returncode != 0:
    err = (proc.stderr or proc.stdout or "mxswitch failed").strip()
    print(err, file=sys.stderr)
    sys.exit(proc.returncode)
