"""Development runner for the Optiland GUI with automatic restarts.

This module watches Python source files in the Optiland packages and restarts
the GUI process whenever a file changes. It is intended for local development
only and deliberately avoids external watcher dependencies.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

WATCH_EXTENSIONS = {".py", ".qss"}
IGNORED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _watch_roots() -> list[Path]:
    root = _project_root()
    return [root / "optiland", root / "optiland_gui"]


def _iter_watch_files() -> list[Path]:
    files: list[Path] = []
    for watch_root in _watch_roots():
        if not watch_root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(watch_root):
            dirnames[:] = [
                dirname for dirname in dirnames if dirname not in IGNORED_DIR_NAMES
            ]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix in WATCH_EXTENSIONS:
                    files.append(path)
    files.sort()
    return files


def _snapshot() -> dict[Path, int]:
    snapshot: dict[Path, int] = {}
    for path in _iter_watch_files():
        try:
            snapshot[path] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def _find_changes(previous: dict[Path, int]) -> tuple[dict[Path, int], list[Path]]:
    current = _snapshot()
    changed = [
        path
        for path, mtime in current.items()
        if previous.get(path) != mtime
    ]
    removed = [path for path in previous if path not in current]
    return current, sorted(changed + removed)


def _spawn_gui() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "optiland_gui.run_gui"],
        cwd=_project_root(),
    )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Optiland GUI and restart when source files change."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.75,
        help="Polling interval in seconds. Default: 0.75",
    )
    return parser.parse_args()


def main() -> None:
    """Run the Optiland GUI with automatic restart on source changes."""
    args = _parse_args()
    print("Starting Optiland dev runner.")
    print("Watching for changes in:")
    for path in _watch_roots():
        print(f"  - {path}")

    snapshot = _snapshot()
    process = _spawn_gui()

    try:
        while True:
            time.sleep(args.interval)

            if process.poll() is not None:
                print("Optiland exited. Restarting.")
                process = _spawn_gui()
                snapshot = _snapshot()
                continue

            snapshot, changed_paths = _find_changes(snapshot)
            if not changed_paths:
                continue

            print("Detected changes:")
            for path in changed_paths[:8]:
                try:
                    rel_path = path.relative_to(_project_root())
                except ValueError:
                    rel_path = path
                print(f"  - {rel_path}")
            if len(changed_paths) > 8:
                print(f"  - ... and {len(changed_paths) - 8} more")

            print("Restarting Optiland.")
            _stop_process(process)
            process = _spawn_gui()
    except KeyboardInterrupt:
        print("\nStopping Optiland dev runner.")
    finally:
        _stop_process(process)


if __name__ == "__main__":
    main()
