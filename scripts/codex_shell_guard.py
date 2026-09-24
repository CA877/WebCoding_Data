#!/usr/bin/env python3
"""Bound read-only shell probes issued by fast-generation Codex tasks."""
from __future__ import annotations

import os
import subprocess
import sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
real = {
    "rg": "/Applications/ChatGPT.app/Contents/Resources/rg",
    "sed": "/usr/bin/sed",
    "cat": "/bin/cat",
    "find": "/usr/bin/find",
    "ls": "/bin/ls",
    "head": "/bin/head",
    "tail": "/bin/tail",
}.get(name)
if not real:
    raise SystemExit(127)
if name == "rg" and "--files" in args:
    print("shell guard: project-wide file listing is disabled", file=sys.stderr)
    raise SystemExit(2)
if name in {"cat", "sed", "head", "tail"} and any(".agents/skills" in arg and "/references/" in arg for arg in args):
    print("shell guard: full reference source is hidden; use the matching SKILL.md API signature", file=sys.stderr)
    raise SystemExit(2)
try:
    completed = subprocess.run([real, *args], capture_output=True, text=True, timeout=8)
except subprocess.TimeoutExpired:
    print("shell guard: read command timed out", file=sys.stderr)
    raise SystemExit(124)
if completed.stdout:
    sys.stdout.write(completed.stdout[:20000])
    if len(completed.stdout) > 20000:
        sys.stdout.write("\n[shell guard: output truncated]\n")
if completed.stderr:
    sys.stderr.write(completed.stderr[:4000])
raise SystemExit(completed.returncode)
