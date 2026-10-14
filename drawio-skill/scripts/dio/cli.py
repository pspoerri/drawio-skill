"""Locating and calling the draw.io desktop CLI (Mermaid conversion, ELK layout, image export)."""

import glob
import os
import shutil
import subprocess
from pathlib import Path


class CliError(RuntimeError):
    pass


def find_cli():
    """Path of the draw.io desktop executable, or None. Honours $DRAWIO_CMD."""
    candidates = [os.environ.get("DRAWIO_CMD"), shutil.which("drawio"), shutil.which("draw.io"),
                  "/Applications/draw.io.app/Contents/MacOS/draw.io",
                  str(Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA") and os.environ["LOCALAPPDATA"] + "\\Programs"):
        if base:
            candidates.append(os.path.join(base, "draw.io", "draw.io.exe"))
    candidates += sorted(glob.glob("/mnt/*/Program Files/draw.io/draw.io.exe"))            # WSL2
    candidates += sorted(glob.glob("/mnt/c/Users/*/AppData/Local/Programs/draw.io/draw.io.exe"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_cli(args, expect=None, timeout=180):
    """Run the CLI; `expect` is a file that must exist afterwards."""
    exe = find_cli()
    if not exe:
        raise CliError("draw.io desktop is not installed (or not found; set DRAWIO_CMD to its executable)")
    if expect and os.path.exists(expect):
        before = os.stat(expect).st_mtime_ns
    else:
        before = None
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliError(f"could not run {exe}: {exc}") from exc
    produced = expect is None or (os.path.exists(expect) and os.stat(expect).st_mtime_ns != before)
    if proc.returncode != 0 or not produced:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
        hint = ""
        if "sandbox" in tail.lower():
            hint = " (the app was blocked by a sandbox: run this command outside the sandbox)"
        elif "GPU process" in tail:
            hint = " (retry with --disable-gpu)"
        raise CliError(f"draw.io CLI failed{hint}: {tail or 'no output'}")
    return proc
